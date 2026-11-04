"""
Biznes mantiq: AI ajratgan yozuvni tekshirish, tasdiqlash va bazaga yozish.
Bot ham, kelajakdagi agent tool'lari ham shu funksiyalardan foydalanadi.

Asosiy tamoyil: pul masalasida TAXMIN QILMAYMIZ — ism to'liq mos kelmasa so'raymiz,
narxni to'qimaymiz, har yozuv do'konchi tasdiqlagandan keyingina saqlanadi.
"""
from datetime import date
from decimal import Decimal
from functools import partial
from html import escape as _escape

from django.db import transaction as db_tx
from django.utils import timezone

from . import dates
from .i18n import lang_of, money, tr, unit
from .nlp import norm, parse_amount  # noqa: F401  (parse_amount bot uchun qayta eksport)
from .models import (Customer, KnownContact, PendingAction, Product, Promise, Shop, Transaction,
                     TransactionItem)

escape = partial(_escape, quote=False)

ITEM_ACTIONS = ("nasiya", "sotuv", "kirim")
CUSTOMER_ACTIONS = ("nasiya", "tolov", "vada")


def today() -> date:
    return timezone.localdate()


def fmt(n) -> str:
    """150000 -> '150 000'"""
    if n is None:
        return "?"
    n = Decimal(str(n))
    s = f"{n:,.0f}" if n == n.to_integral() else f"{n:,.2f}".rstrip("0").rstrip(".")
    return s.replace(",", " ")


# ---------- do'kon va mijozlar ----------

def get_or_create_shop(telegram_id: int, name: str = "") -> Shop:
    shop, _ = Shop.objects.get_or_create(telegram_id=telegram_id, defaults={"name": name})
    return shop


def resolve_user(user_id: int, create_shop: bool = False):
    """('shop', Shop) | ('customer', Customer) | (None, None). Yangi foydalanuvchi — do'konchi."""
    shop = Shop.objects.filter(telegram_id=user_id).first()
    if shop:
        return "shop", shop
    cust = Customer.objects.select_related("shop").filter(telegram_chat_id=user_id).first()
    if cust:
        return "customer", cust
    if create_shop:
        return "shop", get_or_create_shop(user_id, "")
    return None, None


def known_customer_names(shop: Shop) -> list[str]:
    return [str(c) for c in shop.customers.all()]


def resolve_customer(shop: Shop, name: str | None) -> tuple[Customer | None, list[Customer]]:
    """
    (aniq_mijoz, nomzodlar). Qarz noto'g'ri odamga yozilmasligi uchun faqat
    ISM TO'LIQ MOS kelsa avtomatik bog'laymiz; qisman moslikda — so'raymiz.
    """
    if not name:
        return None, []
    n = " ".join(norm(name).split())
    first = n.split()[0]
    cands = [c for c in shop.customers.all() if norm(c.name).split()[0] == first]
    full = [c for c in cands if norm(str(c)) == n]          # "Akmal (yosh)"
    if len(full) == 1:
        return full[0], cands
    exact = [c for c in cands if norm(c.name) == n]         # "Akmal aka"
    if len(exact) == 1 and (len(n.split()) > 1 or len(cands) == 1):
        return exact[0], cands
    return None, cands


def customer_candidates(shop: Shop, name: str | None) -> list[Customer]:
    exact, cands = resolve_customer(shop, name)
    return [exact] if exact else cands


def balance_of(customer: Customer) -> Decimal:
    return Customer.objects.with_balance().get(pk=customer.pk).balance


def set_customer_field(shop: Shop, name: str | None, **fields) -> tuple[Customer | None, list[Customer]]:
    """Telefon yoki limitni o'rnatish. Mijoz aniq topilmasa — (None, nomzodlar)."""
    exact, cands = resolve_customer(shop, name)
    if not exact:
        return None, cands
    for k, v in fields.items():
        setattr(exact, k, v)
    exact.save(update_fields=list(fields))
    if fields.get("phone"):
        link_known_contact(exact)
    return exact, cands


# ---------- telefon raqami orqali avtomatik ulash ----------

def remember_contact(chat_id: int, phone_raw: str, name: str = "", lang: str = "") -> tuple[list[Customer], list[Customer]]:
    """Mijoz botga o'z raqamini yuborganda: (shu raqamli barcha mijozlar, yangi ulanganlar)."""
    from .nlp import normalize_phone

    phone = normalize_phone(phone_raw)
    if not phone:
        return [], []
    KnownContact.objects.update_or_create(phone=phone, defaults={"chat_id": chat_id, "name": name[:200], "lang": lang})
    found, new = [], []
    for c in Customer.objects.select_related("shop").filter(phone=phone):
        changed = []
        if c.telegram_chat_id != chat_id:
            c.telegram_chat_id = chat_id
            changed.append("telegram_chat_id")
            new.append(c)
        if lang and c.lang != lang:
            c.lang = lang
            changed.append("lang")
        if changed:
            c.save(update_fields=changed)
        found.append(c)
    return found, new


def link_known_contact(customer: Customer) -> bool:
    """Do'konchi telefon kiritganda: bu raqam egasi botga avval yozgan bo'lsa — darhol ulaymiz."""
    if not customer.phone or customer.telegram_chat_id:
        return False
    kc = KnownContact.objects.filter(phone=customer.phone).first()
    if not kc:
        return False
    customer.telegram_chat_id = kc.chat_id
    customer.lang = kc.lang or customer.lang
    customer.save(update_fields=["telegram_chat_id", "lang"])
    return True


def set_chat_lang(chat_id: int, lang: str) -> None:
    """Mijoz tilni o'zgartirsa — uning barcha do'konlardagi yozuvlariga."""
    Customer.objects.filter(telegram_chat_id=chat_id).update(lang=lang)
    KnownContact.objects.filter(chat_id=chat_id).update(lang=lang)


def customers_of_chat(chat_id: int) -> list[Customer]:
    return list(Customer.objects.select_related("shop").filter(telegram_chat_id=chat_id))


# ---------- kutilayotgan yozuv (PendingAction) ----------

def _price_field(action: str) -> str:
    return "cost_price" if action == "kirim" else "sell_price"


def create_pending(shop: Shop, payload: dict, source_type: str, source_text: str) -> PendingAction:
    p = {
        "action": payload.get("action"),
        "customer": payload.get("customer"),
        "customer_id": None,
        "amount": payload.get("amount"),
        "due_date": payload.get("due_date"),
        "items": [dict(it) for it in payload.get("items") or []],
    }
    # Narxi aytilmagan mahsulotlarga oxirgi ma'lum narxni qo'yamiz (kirim -> tannarx, sotuv -> sotuv narxi)
    field = _price_field(p["action"])
    for it in p["items"]:
        it["name"] = it["name"].strip().lower()
        if it.get("price") in (None, "", 0):
            prod = shop.products.filter(name=it["name"]).first()
            val = getattr(prod, field) if prod else None
            it["price"] = float(val) if val else None
            it["price_from_history"] = it["price"] is not None
    exact, _ = resolve_customer(shop, p["customer"])
    if exact:
        p["customer_id"] = exact.pk
    pa = PendingAction.objects.create(shop=shop, payload=p, source_type=source_type,
                                      source_text=source_text)
    _recalc(pa)
    return pa


def _recalc(pa: PendingAction):
    p = pa.payload
    if p["action"] in ITEM_ACTIONS and p["items"] and \
            all(it.get("price") is not None for it in p["items"]):
        p["amount"] = sum(float(it["qty"]) * float(it["price"]) for it in p["items"])
    pa.payload = p
    pa.save(update_fields=["payload"])


def missing_price_index(pa: PendingAction):
    if pa.payload["action"] not in ITEM_ACTIONS:
        return None
    for i, it in enumerate(pa.payload["items"]):
        if it.get("price") is None:
            return i
    return None


def set_item_price(pa: PendingAction, idx: int, price) -> None:
    pa.payload["items"][idx]["price"] = float(price)
    pa.payload["items"][idx]["price_from_history"] = False
    _recalc(pa)


def needs_customer_choice(pa: PendingAction) -> list[Customer]:
    """Ism aniq mos kelmasa-yu, o'xshash mijozlar bo'lsa — tanlash uchun ro'yxat."""
    p = pa.payload
    if p["action"] not in CUSTOMER_ACTIONS or p.get("customer_id") or p.get("new_customer"):
        return []
    _, cands = resolve_customer(pa.shop, p["customer"])
    return cands


def choose_customer(pa: PendingAction, customer_id: int | None) -> None:
    if customer_id:
        pa.payload["customer_id"] = customer_id
    else:
        pa.payload["new_customer"] = True
    pa.save(update_fields=["payload"])


def render_card(pa: PendingAction) -> str:
    p = pa.payload
    L = lang_of(pa.shop)
    lines = []
    title = tr(L, f"kind.{p['action']}") if p["action"] in ITEM_ACTIONS + CUSTOMER_ACTIONS else p["action"]
    customer, bal = None, None
    if p["action"] in CUSTOMER_ACTIONS:
        if p.get("customer_id"):
            customer = Customer.objects.get(pk=p["customer_id"])
            who = f"<b>{escape(str(customer))}</b>"
            bal = balance_of(customer)
        else:
            who = f"<b>{escape(p.get('customer') or '?')}</b> {tr(L, 'card.new_customer')}"
            bal = Decimal("0")
        lines.append(f"{title} — {who}")
    else:
        lines.append(title)

    for it in p["items"]:
        u = unit(L, it.get("unit"))
        price = it.get("price")
        hist = f" <i>{tr(L, 'card.last_price')}</i>" if it.get("price_from_history") else ""
        total = fmt(float(it["qty"]) * price) if price is not None else "?"
        lines.append(f"• {escape(it['name'])} {fmt(it['qty'])} {u} × {fmt(price)}{hist} = {total}")

    if p["action"] == "vada":
        lines.append(tr(L, "card.due", when=dates.human(p.get("due_date"), today(), L)))
        amt = money(L, p["amount"]) if p.get("amount") else tr(L, "card.whole", bal=money(L, bal))
        lines.append(tr(L, "card.amount", amt=amt))
    else:
        lines.append(tr(L, "card.total", amt=money(L, p.get("amount"))))

    if p["action"] in ("nasiya", "tolov") and p.get("amount") is not None:
        amt = Decimal(str(p["amount"]))
        new = bal + amt if p["action"] == "nasiya" else bal - amt
        lines.append(tr(L, "card.debt", old=fmt(bal), new=money(L, new)))
        if p["action"] == "nasiya" and customer and customer.credit_limit and new > customer.credit_limit:
            lines.append(tr(L, "card.limit", limit=money(L, customer.credit_limit)))
        if p["action"] == "tolov" and new < 0:
            lines.append(tr(L, "card.overpay"))
    if p["action"] == "sotuv":
        lines.append(tr(L, "card.cash_in"))
    if pa.source_text:
        icon = {"voice": "🎤", "photo": "📷"}.get(pa.source_type, "💬")
        lines.append(f"\n{icon} <i>{escape(pa.source_text[:300])}</i>")
    return "\n".join(lines)


@db_tx.atomic
def confirm(pa: PendingAction):
    """Tasdiqlangan yozuvni saqlaydi. Transaction yoki Promise qaytaradi."""
    pa = PendingAction.objects.select_for_update().get(pk=pa.pk)
    if pa.status != PendingAction.Status.PENDING:
        raise ValueError("Bu yozuv allaqachon ko'rib chiqilgan")
    p, shop = pa.payload, pa.shop

    customer = None
    if p["action"] in CUSTOMER_ACTIONS:
        if p.get("customer_id"):
            customer = Customer.objects.get(pk=p["customer_id"], shop=shop)
        else:
            customer = Customer.objects.create(shop=shop, name=(p.get("customer") or "Noma'lum").strip())

    if p["action"] == "vada":
        obj = Promise.objects.create(
            shop=shop, customer=customer, due_date=date.fromisoformat(p["due_date"]),
            amount=Decimal(str(p["amount"])) if p.get("amount") else None,
            source_text=pa.source_text)
    else:
        obj = Transaction.objects.create(
            shop=shop, customer=customer, kind=p["action"],
            amount=Decimal(str(p.get("amount") or 0)),
            source_type=pa.source_type, source_text=pa.source_text,
        )
        field = _price_field(p["action"])
        for it in p["items"]:
            qty = Decimal(str(it["qty"]))
            price = Decimal(str(it["price"])) if it.get("price") is not None else None
            product, _ = Product.objects.get_or_create(
                shop=shop, name=it["name"], defaults={"unit": it.get("unit") or ""})
            if price is not None:
                setattr(product, field, price)
            cost = price if p["action"] == "kirim" else product.cost_price
            product.stock += qty if p["action"] == "kirim" else -qty
            product.save()
            TransactionItem.objects.create(
                transaction=obj, product=product, qty=qty, unit=it.get("unit") or "",
                price=price, cost=cost, total=(qty * price) if price is not None else 0,
            )
        if p["action"] == "tolov":
            _settle_promises(customer, obj.amount)

    pa.status = PendingAction.Status.CONFIRMED
    pa.save(update_fields=["status"])
    return obj


def _settle_promises(customer: Customer, paid: Decimal):
    """To'lov kelganda ochiq va'dalarni tekshiradi: va'da qilingan summa to'langan bo'lsa — bajarildi."""
    from django.db.models import Sum

    balance = balance_of(customer)
    for pr in customer.promises.filter(status=Promise.Status.OPEN):
        paid_since = customer.transactions.filter(
            kind="tolov", created_at__gte=pr.created_at).aggregate(s=Sum("amount"))["s"] or 0
        if balance <= 0 or (pr.amount is not None and paid_since >= pr.amount):
            pr.status = Promise.Status.KEPT
            pr.save(update_fields=["status"])


def cancel(pa: PendingAction) -> None:
    pa.status = PendingAction.Status.CANCELLED
    pa.save(update_fields=["status"])


# ---------- ikki tomonlama daftar: mijoz o'z qarzini ko'radi ----------

def link_url(customer: Customer, bot_username: str) -> str:
    return f"https://t.me/{bot_username}?start=c_{customer.link_token}"


def link_customer_chat(token: str, chat_id: int, lang: str = "") -> Customer | None:
    c = Customer.objects.select_related("shop").filter(link_token=token).first()
    if c:
        c.telegram_chat_id = chat_id
        if lang:
            c.lang = lang
        c.save(update_fields=["telegram_chat_id", "lang"])
    return c


def customer_statement(customer: Customer, limit: int = 10, lang: str | None = None) -> str:
    """Mijozning hisobi — mijozning tilida (yoki do'konchi so'rasa, do'konchi tilida)."""
    L = lang or lang_of(customer)
    bal = balance_of(customer)
    lines = [f"🏪 <b>{escape(str(customer.shop))}</b>",
             f"👤 {escape(customer.name)}",
             tr(L, "st.balance", amt=money(L, bal)), ""]
    for tx in customer.transactions.prefetch_related("items__product")[:limit]:
        d = timezone.localtime(tx.created_at).strftime("%d.%m %H:%M")
        if tx.kind == "nasiya":
            what = ", ".join(f"{i.product.name} {fmt(i.qty)}" for i in tx.items.all()) or tr(L, "st.credit")
            mark = {"confirmed": " ✅", "disputed": " ❌"}.get(tx.customer_status, "")
            lines.append(f"{d}  ➕ {fmt(tx.amount)} — {escape(what)}{mark}")
        elif tx.kind == "tolov":
            lines.append(f"{d}  ➖ {fmt(tx.amount)} — {tr(L, 'st.payment')}")
    promise = customer.promises.filter(status=Promise.Status.OPEN).first()
    if promise:
        lines.append("\n" + tr(L, "st.promise", when=dates.human(promise.due_date, today(), L)))
    return "\n".join(lines)


def customer_notice(tx: Transaction) -> str:
    """Nasiya yoki to'lov yozilganda mijozga boradigan xabar — mijozning tilida."""
    L = lang_of(tx.customer)
    bal = balance_of(tx.customer)
    shop = escape(str(tx.shop))
    if tx.kind == "nasiya":
        what = ", ".join(f"{i.product.name} {fmt(i.qty)} {unit(L, i.unit)}".strip() for i in tx.items.all())
        return tr(L, "nt.credit", shop=shop, what=escape(what), amt=money(L, tx.amount), bal=money(L, bal))
    return tr(L, "nt.paid", shop=shop, amt=money(L, tx.amount), bal=money(L, bal))


def set_customer_status(tx_id: int, chat_id: int, status: str) -> Transaction | None:
    tx = Transaction.objects.select_related("customer", "shop").filter(
        pk=tx_id, customer__telegram_chat_id=chat_id).first()
    if tx:
        tx.customer_status = status
        tx.save(update_fields=["customer_status"])
    return tx


# ---------- savollar ----------

def debtors(shop: Shop, limit: int = 20) -> list[Customer]:
    return list(shop.customers.with_balance().filter(balance__gt=0).order_by("-balance")[:limit])


def render_debtors(shop: Shop) -> str:
    L = lang_of(shop)
    rows = debtors(shop)
    if not rows:
        return tr(L, "db.none")
    total = sum(c.balance for c in rows)
    lines = []
    for i, c in enumerate(rows, 1):
        flags = ""
        if c.credit_limit and c.balance > c.credit_limit:
            flags += " " + tr(L, "db.flag_limit")
        if c.telegram_chat_id:
            flags += " 📱"
        if c.transactions.filter(customer_status="disputed").exists():
            flags += " " + tr(L, "db.flag_disputed")
        lines.append(f"{i}. {escape(str(c))} — {money(L, c.balance)}{flags}")
    return tr(L, "db.title") + "\n" + "\n".join(lines) + "\n\n" + tr(L, "db.total", amt=money(L, total))


def render_promises(shop: Shop) -> str:
    L = lang_of(shop)
    rows = shop.promises.filter(status=Promise.Status.OPEN).select_related("customer")
    if not rows:
        return tr(L, "pr.none")
    t = today()
    lines = [tr(L, "pr.title")]
    for pr in rows:
        icon = "🔴" if pr.due_date < t else ("🟡" if pr.due_date == t else "⚪")
        amt = money(L, pr.amount) if pr.amount else tr(L, "whole_debt")
        lines.append(f"{icon} {escape(str(pr.customer))} — {amt}, {dates.human(pr.due_date, t, L)}")
    return "\n".join(lines)


Q_SALES = ("savdo", "sotuv", "daromad", "foyda", "kassa", "tushum", "hisobot",
           "продаж", "выручк", "прибыл", "касс", "отчёт", "отчет", "sales", "revenue", "profit", "cash", "report")
Q_STOCK = ("ombor", "qoldiq", "tugay", "tovar", "склад", "остат", "товар", "stock", "inventory")
Q_TIPS = ("maslahat", "tavsiya", "rivoj", "nima qilay", "совет", "рекоменд", "advice", "tips", "suggest")
Q_PROMISE = ("va'da", "обещ", "promise")
Q_PERIOD = {"bugun": ("bugun", "сегодня", "today"), "kecha": ("kecha", "вчера", "yesterday"),
            "hafta": ("hafta", "недел", "week"), "oy": ("oy", "месяц", "month")}


def answer_question(shop: Shop, question: str) -> str:
    """Qoidaga asoslangan yo'naltirish (uz/ru/en kalit so'zlar). Agent ulangach, u shu funksiyalarni chaqiradi."""
    from . import reports

    q = norm(question)
    words = set(q.replace("?", " ").replace(",", " ").split())
    period = next((p for p, keys in Q_PERIOD.items() if any(w.startswith(k) for w in words for k in keys)), None)
    if any(k in q for k in Q_SALES) or period:
        return reports.render_summary(shop, period or "bugun")
    if any(k in q for k in Q_STOCK):
        return reports.render_stock(shop)
    if any(k in q for k in Q_TIPS):
        return reports.render_insights(shop)
    if any(k in q for k in Q_PROMISE):
        return render_promises(shop)
    for c in shop.customers.with_balance():
        if norm(c.name).split()[0] in words:
            return customer_statement(c, lang=lang_of(shop))
    return render_debtors(shop)

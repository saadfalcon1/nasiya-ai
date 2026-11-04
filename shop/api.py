"""
Telegram Mini App uchun JSON API.

Xavfsizlik: har bir so'rov `X-Telegram-Init-Data` sarlavhasini yuboradi. Imzo bot tokeni bilan
HMAC-SHA256 orqali tekshiriladi (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).
Faqat DEBUG rejimida va WEBAPP_DEV_USER o'rnatilgan bo'lsa — brauzerda sinash uchun imzosiz kirish mumkin.
"""
import hashlib
import hmac
import json
import time
from decimal import Decimal
from functools import wraps
from urllib.parse import parse_qsl

from django.conf import settings
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import dates, notify, reports, services, shelf
from .i18n import LANGS, lang_of, money, tr
from .models import Customer, Promise, Transaction
from .nlp import normalize_phone, parse_amount

KIND_ICONS = {"nasiya": "📝", "tolov": "💵", "sotuv": "💰", "kirim": "📦"}


def kind_label(lang: str, kind: str) -> str:
    """'📝 Nasiya' -> 'Nasiya' (belgisiz)."""
    return tr(lang, f"kind.{kind}").split(" ", 1)[-1]


# ---------- auth ----------

def _check(pairs: dict, received_hash: str, bot_token: str) -> bool:
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, received_hash)


def verify_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict | None:
    """To'g'ri imzolangan bo'lsa Telegram user lug'atini qaytaradi, aks holda None."""
    if not init_data or not bot_token:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        return None
    ok = _check(pairs, received, bot_token)
    if not ok and "signature" in pairs:  # ba'zi mijozlar 'signature'ni hisobga olmaydi
        ok = _check({k: v for k, v in pairs.items() if k != "signature"}, received, bot_token)
    if not ok:
        return None
    try:
        if max_age and time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        return json.loads(pairs.get("user", "{}")) or None
    except (ValueError, TypeError):
        return None


def _auth_user(request) -> dict | None:
    user = verify_init_data(request.headers.get("X-Telegram-Init-Data", ""), settings.TELEGRAM_BOT_TOKEN)
    if user:
        return user
    if settings.DEBUG and settings.WEBAPP_DEV_USER:
        return {"id": int(request.GET.get("as") or settings.WEBAPP_DEV_USER)}
    return None


def tg_api(*roles, methods=("GET",)):
    def deco(fn):
        @csrf_exempt
        @require_http_methods(list(methods))
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            user = _auth_user(request)
            if not user or "id" not in user:
                return JsonResponse({"error": "auth"}, status=401)
            role, obj = services.resolve_user(int(user["id"]))
            if role not in roles:
                return JsonResponse({"error": "forbidden", "role": role}, status=403)
            request.role, request.obj = role, obj
            if request.method == "POST":
                try:
                    request.json = json.loads(request.body or b"{}")
                except ValueError:
                    return JsonResponse({"error": "bad_json"}, status=400)
            return fn(request, *args, **kwargs)
        return wrapper
    return deco


def _n(v):
    return float(v) if v is not None else None


def _dt(d) -> str:
    return timezone.localtime(d).strftime("%d.%m %H:%M")


# ---------- sahifa ----------

def app_page(request):
    return render(request, "shop/app.html", {"dev": settings.DEBUG and bool(settings.WEBAPP_DEV_USER)})


# ---------- umumiy ----------

@tg_api("shop", "customer", methods=("GET", "POST"))
def me(request):
    """GET: rol va til. POST {"lang": "ru"}: tilni o'zgartirish (Mini App'dagi til almashtirgich)."""
    obj = request.obj
    if request.method == "POST":
        lang = request.json.get("lang")
        if lang not in LANGS:
            return JsonResponse({"error": "bad_lang"}, status=400)
        if request.role == "shop":
            obj.lang = lang
            obj.save(update_fields=["lang"])
        else:
            services.set_chat_lang(obj.telegram_chat_id, lang)
            obj.refresh_from_db()
    if request.role == "customer":
        return JsonResponse({"role": "customer", "name": obj.name, "shop": str(obj.shop), "lang": lang_of(obj)})
    return JsonResponse({"role": "shop", "name": obj.name or tr(obj.lang, "rm.shop"), "lang": lang_of(obj)})


# ---------- do'konchi ----------

@tg_api("shop")
def dashboard(request):
    shop = request.obj
    L = lang_of(shop)
    period = request.GET.get("period", "bugun")
    if period not in reports.PERIODS:
        period = "bugun"
    t = services.today()
    s, e = reports.period_range(period, t)
    cur, prev = reports.summary(shop, s, e), reports.summary(shop, *reports.prev_range(s, e))
    debt, n_debtors = reports.outstanding(shop)
    delta = None
    if prev["revenue"]:
        delta = float((cur["revenue"] - prev["revenue"]) / prev["revenue"] * 100)

    promises = []
    for pr in shop.promises.filter(status=Promise.Status.OPEN, due_date__lte=t).select_related("customer"):
        promises.append({"customer_id": pr.customer_id, "name": str(pr.customer), "amount": _n(pr.amount),
                         "late": (t - pr.due_date).days, "due": dates.label(pr.due_date, L)})
    days = {"bugun": 14, "kecha": 14, "hafta": 14, "oy": 30}[period]
    return JsonResponse({
        "shop": shop.name or tr(L, "rm.shop"), "lang": L,
        "period": period, "title": reports.period_title(period, L), "range": reports._range_label(s, e),
        "kpi": {
            "revenue": _n(cur["revenue"]), "delta": delta, "cash": _n(cur["sotuv"]), "credit": _n(cur["nasiya"]),
            "cash_in": _n(cur["cash_in"]), "paid": _n(cur["tolov"]), "profit": _n(cur["profit"]),
            "profit_known": cur["profit_known"], "purchases": _n(cur["kirim"]),
            "outstanding": _n(debt), "debtors": n_debtors,
        },
        "series": reports.daily_series(shop, days),
        "top": [{"name": n, "amount": _n(v)} for n, v in cur["top"]],
        "promises": promises,
        "insights": reports.insights(shop),
    })


def _customer_row(c: Customer, t, L: str = "uz") -> dict:
    last_pay = c.transactions.filter(kind="tolov").aggregate(m=Max("created_at"))["m"]
    first = c.transactions.filter(kind="nasiya").aggregate(m=Max("created_at"))["m"]
    ref = last_pay or c.transactions.filter(kind="nasiya").order_by("created_at").values_list(
        "created_at", flat=True).first()
    days = (t - timezone.localtime(ref).date()).days if ref else None
    pr = c.promises.filter(status=Promise.Status.OPEN).order_by("due_date").first()
    return {
        "id": c.pk, "name": str(c), "balance": _n(c.balance), "limit": _n(c.credit_limit),
        "over_limit": bool(c.credit_limit and c.balance > c.credit_limit),
        "linked": bool(c.telegram_chat_id), "phone": c.phone,
        "days_since_pay": days, "overdue": bool(days is not None and days >= 30 and c.balance > 0),
        "last_purchase": _dt(first) if first else None,
        "disputed": c.transactions.filter(customer_status="disputed").count(),
        "promise": {"due": dates.label(pr.due_date, L), "late": (t - pr.due_date).days,
                    "amount": _n(pr.amount)} if pr else None,
    }


@tg_api("shop")
def debtors(request):
    shop = request.obj
    t = services.today()
    qs = shop.customers.with_balance()
    if request.GET.get("all") != "1":
        qs = qs.filter(balance__gt=0)
    rows = [_customer_row(c, t, lang_of(shop)) for c in qs.order_by("-balance")]
    debt, n = reports.outstanding(shop)
    return JsonResponse({"customers": rows, "outstanding": _n(debt), "count": n})


def _tx_json(tx: Transaction, L: str = "uz") -> dict:
    items = [{"name": i.product.name, "qty": _n(i.qty), "unit": i.unit, "price": _n(i.price)}
             for i in tx.items.all()]
    return {
        "id": tx.pk, "kind": tx.kind, "icon": KIND_ICONS.get(tx.kind, ""), "label": kind_label(L, tx.kind),
        "amount": _n(tx.amount), "date": _dt(tx.created_at), "customer": str(tx.customer) if tx.customer else None,
        "customer_id": tx.customer_id, "items": items, "status": tx.customer_status,
        "source": tx.source_text[:200], "source_type": tx.source_type,
    }


@tg_api("shop", methods=("GET", "POST"))
def customer_detail(request, pk: int):
    shop = request.obj
    try:
        c = shop.customers.with_balance().get(pk=pk)
    except Customer.DoesNotExist:
        return JsonResponse({"error": "not_found"}, status=404)

    if request.method == "POST":
        data, errors = request.json, {}
        if "phone" in data:
            phone = normalize_phone(str(data["phone"])) if data["phone"] else ""
            if data["phone"] and not phone:
                errors["phone"] = "Raqam noto'g'ri. Masalan: 90 123 45 67"
            else:
                c.phone = phone or ""
        if "limit" in data:
            raw = data["limit"]
            val = None if raw in (None, "", 0, "0") else parse_amount(str(raw))
            if raw not in (None, "", 0, "0") and not val:
                errors["limit"] = "Summani son bilan yozing"
            else:
                c.credit_limit = Decimal(str(val)) if val else None
        if errors:
            return JsonResponse({"error": "validation", "fields": errors}, status=400)
        c.save(update_fields=["phone", "credit_limit"])
        if services.link_known_contact(c):  # raqam egasi botda bor -> darhol ulandi
            CL = lang_of(c)
            notify.send_telegram(
                c.telegram_chat_id,
                tr(CL, "b.added_by_shop", shop=services.escape(str(shop))) + "\n\n" + services.customer_statement(c),
                notify.account_button(CL))
        c = shop.customers.with_balance().get(pk=pk)

    t = services.today()
    L = lang_of(shop)
    txs = c.transactions.prefetch_related("items__product")[:60]
    return JsonResponse({
        **_customer_row(c, t, L),
        "note": c.note,
        "link_url": services.link_url(c, settings.BOT_USERNAME),
        "channel": notify.reminder_channel(c),
        "auto_remind": shop.auto_remind, "remind_hour": shop.remind_hour,
        "draft": notify.draft_reminder(c),
        "customer_lang": lang_of(c),
        "transactions": [_tx_json(tx, L) for tx in txs],
        "promises": [{"due": dates.label(p.due_date, L), "late": (t - p.due_date).days, "amount": _n(p.amount),
                      "status": p.status} for p in c.promises.order_by("-due_date")[:10]],
        "reminders": [{"date": _dt(m.created_at), "channel": m.channel, "ok": m.ok}
                      for m in c.messages.order_by("-created_at")[:10]],
    })


@tg_api("shop", methods=("POST",))
def customer_remind(request, pk: int):
    c = request.obj.customers.filter(pk=pk).first()
    if not c:
        return JsonResponse({"error": "not_found"}, status=404)
    res = notify.deliver_reminder(c)
    if not res["ok"] and res["channel"] is None:
        res["link_url"] = services.link_url(c, settings.BOT_USERNAME)
    return JsonResponse(res, status=200)


@tg_api("shop")
def stock(request):
    shop = request.obj
    t = services.today()
    st = reports.stock_insights(shop, t)
    margins = {m["product"].pk: m for m in reports.margins(shop, t)}
    low = {p.pk for p, _, _ in st["low"]}
    slow = {p.pk: frozen for p, frozen in st["slow"]}
    rows = []
    for p, avg, days_left in st["rows"]:
        m = margins.get(p.pk)
        status = ("negative" if p.stock < 0 else "low" if p.pk in low else "slow" if p.pk in slow
                  else "loss" if m and m["unit_profit"] < 0 else "daily" if p.is_daily else "ok")
        rows.append({
            "id": p.pk, "name": p.name, "unit": p.unit, "stock": _n(p.stock), "avg": round(float(avg), 2),
            "days_left": round(float(days_left), 1) if days_left is not None else None,
            "status": status, "daily": p.is_daily,
            "cost": _n(p.cost_price), "sell": _n(p.sell_price),
            "margin_pct": round(float(m["pct"]), 1) if m else None,
            "profit30": _n(m["profit"]) if m else None,
            "frozen": _n(slow.get(p.pk)),
            "value": _n(p.stock * p.cost_price) if p.cost_price and p.stock > 0 else None,
        })
    order = {"negative": 0, "low": 1, "loss": 2, "slow": 3, "ok": 4, "daily": 5}
    rows.sort(key=lambda r: (order[r["status"]], r["days_left"] if r["days_left"] is not None else 1e9))
    total_value = sum(r["value"] or 0 for r in rows)
    return JsonResponse({"products": rows, "total_value": total_value,
                         "shelf": shelf.audit_json(shop.shelf_audits.first())})


@tg_api("shop")
def transactions(request):
    shop = request.obj
    qs = shop.transactions.select_related("customer").prefetch_related("items__product")
    kind = request.GET.get("kind")
    if kind in KIND_ICONS:
        qs = qs.filter(kind=kind)
    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except ValueError:
        offset = 0
    page = list(qs[offset:offset + 40])
    L = lang_of(shop)
    return JsonResponse({"transactions": [_tx_json(tx, L) for tx in page], "next": offset + 40 if len(page) == 40 else None})


# ---------- mijoz ----------

@tg_api("customer")
def my_statement(request):
    c = Customer.objects.with_balance().select_related("shop").get(pk=request.obj.pk)
    t = services.today()
    L = lang_of(c)
    pr = c.promises.filter(status=Promise.Status.OPEN).order_by("due_date").first()
    txs = c.transactions.prefetch_related("items__product")[:60]
    return JsonResponse({
        "shop": str(c.shop), "name": c.name, "balance": _n(c.balance), "limit": _n(c.credit_limit), "lang": L,
        "promise": {"due": dates.label(pr.due_date, L), "late": (t - pr.due_date).days, "amount": _n(pr.amount)}
        if pr else None,
        "transactions": [{**_tx_json(tx, L), "can_review": tx.kind == "nasiya" and not tx.customer_status}
                         for tx in txs],
    })


@tg_api("customer", methods=("POST",))
def my_review(request, pk: int):
    status = request.json.get("status")
    if status not in ("confirmed", "disputed"):
        return JsonResponse({"error": "bad_status"}, status=400)
    tx = services.set_customer_status(pk, request.obj.telegram_chat_id, status)
    if not tx:
        return JsonResponse({"error": "not_found"}, status=404)
    if status == "disputed":
        SL = lang_of(tx.shop)
        notify.send_telegram(
            tx.shop.telegram_id,
            tr(SL, "b.disputed", name=services.escape(str(tx.customer)), when=_dt(tx.created_at),
               amt=money(SL, tx.amount), src=services.escape(tx.source_text[:200])))
    return JsonResponse({"ok": True, "status": status})

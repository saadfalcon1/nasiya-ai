"""
Hisobotlar va "do'kon menejeri": savdo, foyda, nasiya, ombor tahlili, ertalabki brifing.
Hamma raqamlar do'konning O'Z ma'lumotlaridan hisoblanadi — umumiy maslahat emas.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Max, Min, Sum
from django.utils import timezone

from . import dates
from .models import Customer, Promise, Shop, TransactionItem
from .i18n import lang_of, money, tr, unit
from .services import debtors, escape, fmt, today

SALE_KINDS = ("nasiya", "sotuv")
PERIODS = ("bugun", "kecha", "hafta", "oy")


def period_title(period: str, lang: str) -> str:
    return tr(lang, f"period.{period}")


# ---------- davrlar ----------

def period_range(name: str, t: date) -> tuple[date, date]:
    if name == "kecha":
        d = t - timedelta(days=1)
        return d, d
    if name == "hafta":
        return t - timedelta(days=6), t
    if name == "oy":
        return t - timedelta(days=29), t
    return t, t


def prev_range(start: date, end: date) -> tuple[date, date]:
    n = (end - start).days + 1
    return start - timedelta(days=n), end - timedelta(days=n)


def _delta(cur, prev) -> str:
    if not prev:
        return ""
    pct = (Decimal(cur) - Decimal(prev)) / Decimal(prev) * 100
    return f"  {'📈' if pct >= 0 else '📉'} {pct:+.0f}%"


def _range_label(s: date, e: date) -> str:
    return f"{s:%d.%m}" if s == e else f"{s:%d.%m}–{e:%d.%m}"


# ---------- hisob-kitoblar ----------

def summary(shop: Shop, start: date, end: date) -> dict:
    txs = shop.transactions.filter(created_at__date__range=(start, end))
    by_kind = {k: Decimal(0) for k in ("nasiya", "tolov", "sotuv", "kirim")}
    for row in txs.values("kind").annotate(s=Sum("amount")):
        by_kind[row["kind"]] = row["s"] or Decimal(0)

    items = TransactionItem.objects.filter(transaction__in=txs, transaction__kind__in=SALE_KINDS) \
        .select_related("product")
    profit, covered, item_rev = Decimal(0), Decimal(0), Decimal(0)
    prod_rev = defaultdict(Decimal)
    for it in items:
        item_rev += it.total
        prod_rev[it.product.name] += it.total
        if it.cost is not None and it.price is not None:
            profit += (it.price - it.cost) * it.qty
            covered += it.total

    return {
        **by_kind,
        "revenue": by_kind["sotuv"] + by_kind["nasiya"],
        "cash_in": by_kind["sotuv"] + by_kind["tolov"],
        "profit": profit,
        "profit_known": covered > 0,
        "profit_partial": covered > 0 and covered < by_kind["sotuv"] + by_kind["nasiya"],
        "top": sorted(prod_rev.items(), key=lambda kv: -kv[1])[:3],
        "count": txs.count(),
    }


def outstanding(shop: Shop) -> tuple[Decimal, int]:
    rows = debtors(shop, limit=100000)
    return sum((c.balance for c in rows), Decimal(0)), len(rows)


def overdue_debtors(shop: Shop, t: date, days: int = 30) -> list[tuple[Customer, int]]:
    """Qarzi bor va `days` kundan beri to'lamagan mijozlar."""
    out = []
    for c in debtors(shop, limit=100000):
        last_pay = c.transactions.filter(kind="tolov").aggregate(m=Max("created_at"))["m"]
        first_debt = c.transactions.filter(kind="nasiya").aggregate(m=Min("created_at"))["m"]
        ref = last_pay or first_debt
        if ref is None:
            continue
        d = (t - timezone.localtime(ref).date()).days
        if d >= days:
            out.append((c, d))
    return out


def _shop_age_days(shop: Shop, t: date) -> int:
    first = shop.transactions.aggregate(m=Min("created_at"))["m"]
    return (t - timezone.localtime(first).date()).days + 1 if first else 1


def stock_insights(shop: Shop, t: date, window: int = 14) -> dict:
    """Tugayotgan, turib qolgan va manfiy qoldiqli tovarlar."""
    window = max(1, min(window, _shop_age_days(shop, t)))
    start = t - timedelta(days=window - 1)
    sold = {r["product"]: r["q"] for r in TransactionItem.objects.filter(
        transaction__shop=shop, transaction__kind__in=SALE_KINDS,
        transaction__created_at__date__gte=start).values("product").annotate(q=Sum("qty"))}
    last_in = {r["product"]: timezone.localtime(r["m"]).date() for r in TransactionItem.objects.filter(
        transaction__shop=shop, transaction__kind="kirim").values("product").annotate(m=Max("transaction__created_at"))}
    # Har kuni keladigan tovarlar (non, sut): oynaning yarmidan ko'p kunida kirim bo'lgan
    in_days = defaultdict(set)
    for pid, dt in TransactionItem.objects.filter(
            transaction__shop=shop, transaction__kind="kirim",
            transaction__created_at__date__gte=start).values_list("product", "transaction__created_at"):
        in_days[pid].add(timezone.localtime(dt).date())
    daily = {pid for pid, ds in in_days.items() if window >= 4 and len(ds) >= window * 0.5}

    low, slow, negative, rows = [], [], [], []
    for p in shop.products.all():
        q = sold.get(p.id, Decimal(0))
        avg = q / window
        days_left = (p.stock / avg) if avg > 0 and p.stock > 0 else None
        p.is_daily = p.id in daily
        rows.append((p, avg, days_left))
        if p.stock < 0:
            negative.append(p)
        elif p.is_daily:
            continue
        elif avg > 0 and (days_left is None or days_left <= 3):
            low.append((p, days_left or Decimal(0), avg))
        elif avg == 0 and p.stock > 0:
            li = last_in.get(p.id)
            if li is None or (t - li).days >= 7:
                slow.append((p, p.stock * (p.cost_price or 0)))
    return {"low": low, "slow": slow, "negative": negative, "rows": rows, "window": window}


def margins(shop: Shop, t: date, window: int = 30) -> list[dict]:
    start = t - timedelta(days=window - 1)
    sold = {r["product"]: r["q"] for r in TransactionItem.objects.filter(
        transaction__shop=shop, transaction__kind__in=SALE_KINDS,
        transaction__created_at__date__gte=start).values("product").annotate(q=Sum("qty"))}
    out = []
    for p in shop.products.exclude(sell_price=None).exclude(cost_price=None):
        unit_profit = p.sell_price - p.cost_price
        out.append({"product": p, "unit_profit": unit_profit,
                    "pct": unit_profit / p.cost_price * 100 if p.cost_price else Decimal(0),
                    "profit": unit_profit * sold.get(p.id, 0)})
    return sorted(out, key=lambda m: -m["profit"])


# ---------- matnlar ----------

def render_summary(shop: Shop, period: str = "bugun") -> str:
    L = lang_of(shop)
    t = today()
    s, e = period_range(period, t)
    cur, prev = summary(shop, s, e), summary(shop, *prev_range(s, e))
    total_debt, n_debtors = outstanding(shop)
    lines = [f"📊 <b>{period_title(period, L)}</b> ({_range_label(s, e)})",
             tr(L, "rs.sales", amt=money(L, cur["revenue"]), delta=_delta(cur["revenue"], prev["revenue"])),
             tr(L, "rs.cash", amt=fmt(cur["sotuv"])),
             tr(L, "rs.credit", amt=fmt(cur["nasiya"])),
             tr(L, "rs.cash_in", amt=fmt(cur["cash_in"]), paid=fmt(cur["tolov"]))]
    if cur["profit_known"]:
        note = tr(L, "rs.profit_note") if cur["profit_partial"] else ""
        lines.append(tr(L, "rs.profit", amt=money(L, cur["profit"]), note=note))
    if cur["kirim"]:
        lines.append(tr(L, "rs.purchases", amt=fmt(cur["kirim"])))
    if cur["top"]:
        lines.append(tr(L, "rs.top", list=", ".join(f"{escape(n)} ({fmt(v)})" for n, v in cur["top"])))
    if cur["revenue"] and cur["nasiya"] / cur["revenue"] > Decimal("0.4"):
        lines.append(tr(L, "rs.credit_warn", pct=f"{cur['nasiya'] / cur['revenue'] * 100:.0f}"))
    lines.append("\n" + tr(L, "rs.outstanding", amt=money(L, total_debt), n=n_debtors))
    if not cur["count"]:
        lines.append(tr(L, "rs.empty"))
    return "\n".join(lines)


def render_stock(shop: Shop) -> str:
    L = lang_of(shop)
    st = stock_insights(shop, today())
    if not st["rows"]:
        return tr(L, "sk.empty")
    lines = [tr(L, "sk.title")]
    for p, avg, days_left in sorted(st["rows"], key=lambda r: (r[0].is_daily, r[2] is None, r[2] or 0)):
        if p.is_daily:
            tail, warn = tr(L, "sk.daily"), ""
        else:
            tail = tr(L, "sk.days", d=f"{days_left:.0f}") if days_left is not None else ""
            warn = " 🔴" if days_left is not None and days_left <= 3 else ""
        lines.append(f"• {escape(p.name)}: {fmt(p.stock)} {unit(L, p.unit)}{tail}{warn}")
    if st["negative"]:
        lines.append("\n" + tr(L, "sk.negative", list=", ".join(escape(p.name) for p in st["negative"])))
    return "\n".join(lines)


def insights(shop: Shop) -> list[str]:
    """Aniq, raqamli tavsiyalar ro'yxati (muhimlik tartibida) — do'konchi tilida."""
    L = lang_of(shop)
    t = today()
    tips = []
    st = stock_insights(shop, t)
    for p, days_left, avg in sorted(st["low"], key=lambda x: x[1])[:3]:
        order = (avg * 7).quantize(Decimal("1"))
        cost = tr(L, "in.cost", p=money(L, p.cost_price)) if p.cost_price else ""
        tips.append(tr(L, "in.low", name=escape(p.name), d=f"{days_left:.0f}", avg=fmt(avg.quantize(Decimal("0.1"))),
                       unit=unit(L, p.unit), order=fmt(order), cost=cost))
    for pr in shop.promises.filter(status=Promise.Status.OPEN, due_date__lt=t).select_related("customer")[:3]:
        amt = money(L, pr.amount) if pr.amount else tr(L, "in.debt_word")
        tips.append(tr(L, "in.broken", name=escape(str(pr.customer)), date=dates.label(pr.due_date, L), amt=amt,
                       late=(t - pr.due_date).days))
    for c, d in sorted(overdue_debtors(shop, t), key=lambda x: -x[0].balance)[:3]:
        tips.append(tr(L, "in.overdue", name=escape(str(c)), d=d, amt=money(L, c.balance)))
    for p, frozen in sorted(st["slow"], key=lambda x: -x[1])[:2]:
        frozen_txt = tr(L, "in.frozen", amt=money(L, frozen)) if frozen else ""
        tips.append(tr(L, "in.slow", name=escape(p.name), qty=fmt(p.stock), unit=unit(L, p.unit), w=st["window"],
                       money=frozen_txt))
    ms = margins(shop, t)
    for m in [m for m in ms if m["unit_profit"] < 0][:2]:
        p = m["product"]
        tips.append(tr(L, "in.loss", name=escape(p.name), cost=fmt(p.cost_price), sell=fmt(p.sell_price)))
    best = [m for m in ms if m["profit"] > 0][:3]
    if best:
        tips.append(tr(L, "in.best", list=", ".join(f"{escape(m['product'].name)} (+{fmt(m['profit'])})" for m in best)))
    s7 = summary(shop, t - timedelta(days=6), t)
    if s7["revenue"] and s7["nasiya"] / s7["revenue"] > Decimal("0.4"):
        tips.append(tr(L, "in.credit", pct=f"{s7['nasiya'] / s7['revenue'] * 100:.0f}"))
    return tips


def render_insights(shop: Shop) -> str:
    L = lang_of(shop)
    tips = insights(shop)
    if not tips:
        return tr(L, "in.none")
    return tr(L, "in.title") + "\n\n" + "\n\n".join(f"{i}. {tip}" for i, tip in enumerate(tips, 1))


def morning_brief(shop: Shop) -> tuple[str, list[Customer]]:
    """Ertalabki brifing matni + eslatma yuborish tavsiya qilinadigan mijozlar."""
    L = lang_of(shop)
    t = today()
    y = t - timedelta(days=1)
    cur, prev = summary(shop, y, y), summary(shop, y - timedelta(days=1), y - timedelta(days=1))
    total_debt, n_debtors = outstanding(shop)
    lines = [tr(L, "br.hello", date=dates.label(t, L)), ""]
    if cur["count"]:
        profit = tr(L, "br.profit", p=fmt(cur["profit"])) if cur["profit_known"] else ""
        lines.append(tr(L, "br.yesterday", rev=fmt(cur["revenue"]), delta=_delta(cur["revenue"], prev["revenue"]),
                        profit=profit, cash=money(L, cur["cash_in"])))
    else:
        lines.append(tr(L, "br.no_records"))

    remind: list[Customer] = []
    due_today = list(shop.promises.filter(status=Promise.Status.OPEN, due_date=t).select_related("customer"))
    late = list(shop.promises.filter(status=Promise.Status.OPEN, due_date__lt=t).select_related("customer"))
    if due_today:
        lines.append(tr(L, "br.due_today", list=", ".join(
            escape(str(p.customer)) + (f" ({fmt(p.amount)})" if p.amount else "") for p in due_today)))
    if late:
        lines.append(tr(L, "br.late", list=", ".join(escape(str(p.customer)) for p in late)))
    remind += [p.customer for p in due_today + late]

    st = stock_insights(shop, t)
    if st["low"]:
        lines.append(tr(L, "br.low", list=", ".join(
            f"{escape(p.name)} ({tr(L, 'br.days', d=f'{d:.0f}')})" for p, d, _ in sorted(st["low"], key=lambda x: x[1])[:4])))
    lines.append(tr(L, "br.outstanding", amt=money(L, total_debt), n=n_debtors))
    for c, _ in overdue_debtors(shop, t):
        remind.append(c)
    if shop.auto_remind:
        from .notify import auto_reminder_targets
        n = len(auto_reminder_targets(shop))
        if n:
            lines.append(tr(L, "br.auto", h=shop.remind_hour, n=n))
    if not shop.shelf_audits.filter(created_at__date=t).exists():
        lines.append(tr(L, "br.shelf"))
    lines.append("\n" + tr(L, "br.more"))

    seen, uniq = set(), []
    for c in remind:
        if c.pk not in seen:
            seen.add(c.pk)
            uniq.append(c)
    return "\n".join(lines), uniq[:5]


def daily_series(shop: Shop, days: int = 14) -> list[dict]:
    """Grafik uchun: har kunlik naqd savdo, nasiya, kassaga tushgan pul va foyda."""
    from django.db.models.functions import TruncDate

    t = today()
    start = t - timedelta(days=days - 1)
    rows = {start + timedelta(days=i): {"naqd": Decimal(0), "nasiya": Decimal(0), "tolov": Decimal(0),
                                        "profit": Decimal(0)} for i in range(days)}
    for r in shop.transactions.filter(created_at__date__gte=start).annotate(d=TruncDate("created_at")) \
            .values("d", "kind").annotate(s=Sum("amount")):
        key = {"sotuv": "naqd", "nasiya": "nasiya", "tolov": "tolov"}.get(r["kind"])
        if key and r["d"] in rows:
            rows[r["d"]][key] += r["s"] or 0
    for it in TransactionItem.objects.filter(
            transaction__shop=shop, transaction__kind__in=SALE_KINDS,
            transaction__created_at__date__gte=start).exclude(cost=None).exclude(price=None) \
            .values("transaction__created_at", "price", "cost", "qty"):
        d = timezone.localtime(it["transaction__created_at"]).date()
        if d in rows:
            rows[d]["profit"] += (it["price"] - it["cost"]) * it["qty"]
    L = lang_of(shop)
    return [{"date": d.isoformat(), "label": f"{d.day}", "weekday": dates.weekday_short(d, L),
             **{k: float(v) for k, v in vals.items()}} for d, vals in rows.items()]

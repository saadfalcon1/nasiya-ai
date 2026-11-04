"""
Javon tahlili: do'konchi javonni suratga oladi -> AI tovarlarni sanaydi -> baza bilan solishtiramiz.

Eng qimmatli signal — ERTALAB va KECHQURUN suratlari farqi:
    suratga ko'ra kamaygan  -  yozilgan sotuv (nasiya + naqd)  =  yozilmagan sotuv / yo'qotish
Bu do'konchi uchun "kassada pul kam chiqdi, nega?" savoliga javob.

Sanoq taxminiy (rasmdan) — shuning uchun hisobotda shunday deb aytamiz va kichik farqlarni e'tiborsiz qoldiramiz.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import Product, ShelfAudit, ShelfItem, Shop, TransactionItem
from .nlp import norm
from .i18n import lang_of, money, tr, unit
from .services import escape, fmt, today

SALE_KINDS = ("nasiya", "sotuv")


def _match(name: str, products: list[Product]) -> Product | None:
    n = " ".join(norm(name).split())
    if not n:
        return None
    for p in products:
        if norm(p.name) == n:
            return p
    for p in products:
        pn = norm(p.name)
        if n.startswith(pn + " ") or pn.startswith(n + " "):
            return p
    words = set(n.split())
    hits = [p for p in products if words & set(norm(p.name).split())]
    return hits[0] if len(hits) == 1 else None


def create_audit(shop: Shop, payload: dict, photo_file_id: str = "") -> ShelfAudit:
    products = list(shop.products.all())
    audit = ShelfAudit.objects.create(
        shop=shop, photo_file_id=photo_file_id or "",
        empty_spots=int(payload.get("empty_spots") or 0),
        observations=[str(o)[:200] for o in (payload.get("observations") or [])][:5],
        raw=payload,
    )
    merged: dict[str, dict] = {}
    for it in payload.get("items") or []:
        try:
            count = Decimal(str(it.get("count") or 0))
        except Exception:  # noqa: BLE001
            continue
        name = str(it.get("name") or "").strip().lower()
        if not name:
            continue
        product = _match(name, products)
        key = f"p{product.pk}" if product else f"n{name}"
        row = merged.setdefault(key, {"product": product, "name": product.name if product else name,
                                      "count": Decimal(0), "confidence": it.get("confidence") or ""})
        row["count"] += count
    ShelfItem.objects.bulk_create([ShelfItem(audit=audit, **row) for row in merged.values()])
    return audit


def _sold_between(product: Product, start, end) -> Decimal:
    return TransactionItem.objects.filter(
        product=product, transaction__kind__in=SALE_KINDS,
        transaction__created_at__gt=start, transaction__created_at__lte=end,
    ).aggregate(q=Sum("qty"))["q"] or Decimal(0)


def compare(audit: ShelfAudit) -> dict:
    """Surat natijasini baza va shu kungi oldingi surat bilan solishtiradi."""
    shop = audit.shop
    day = timezone.localtime(audit.created_at).date()
    prev = shop.shelf_audits.filter(created_at__date=day, created_at__lt=audit.created_at) \
        .order_by("created_at").first()
    prev_counts = {i.product_id: i.count for i in prev.items.all() if i.product_id} if prev else {}

    t = today()
    since = t - timedelta(days=13)
    selling = set(TransactionItem.objects.filter(
        transaction__shop=shop, transaction__kind__in=SALE_KINDS,
        transaction__created_at__date__gte=since).values_list("product_id", flat=True))

    rows, unrecorded, low, unknown, stock_gap = [], [], [], [], []
    seen = set()
    for it in audit.items.select_related("product").order_by("name"):
        p = it.product
        row = {"name": it.name, "count": float(it.count), "confidence": it.confidence,
               "product_id": p.pk if p else None, "unit": p.unit if p else "",
               "db_stock": float(p.stock) if p else None, "prev": None, "photo_sold": None,
               "recorded": None, "unrecorded": None}
        if not p:
            unknown.append(it.name)
            rows.append(row)
            continue
        seen.add(p.pk)
        if p.pk in prev_counts:
            photo_sold = prev_counts[p.pk] - it.count
            recorded = _sold_between(p, prev.created_at, audit.created_at)
            row.update(prev=float(prev_counts[p.pk]), photo_sold=float(photo_sold), recorded=float(recorded))
            gap = photo_sold - recorded
            if gap >= max(Decimal(2), photo_sold * Decimal("0.2")):
                row["unrecorded"] = float(gap)
                money = gap * (p.sell_price or 0)
                unrecorded.append({"name": p.name, "unit": p.unit, "gap": gap, "photo_sold": photo_sold,
                                   "recorded": recorded, "money": money})
        if it.count <= 2 and p.pk in selling:
            low.append({"name": p.name, "unit": p.unit, "count": it.count, "stock": p.stock,
                        "reorder": p.stock <= it.count})
        if p.stock < it.count:
            stock_gap.append({"name": p.name, "unit": p.unit, "count": it.count, "stock": p.stock})
        rows.append(row)

    # Ertalabki suratda bor edi, endi ko'rinmaydi (birinchi suratda — hech narsa: javonga qo'yilmagan tovarlar shovqin)
    missing = [p for p in shop.products.filter(pk__in=prev_counts.keys()).exclude(pk__in=seen)][:6] if prev else []
    return {"audit": audit, "prev": prev, "rows": rows, "unrecorded": unrecorded, "low": low,
            "unknown": unknown, "missing": missing, "stock_gap": stock_gap}


def render(audit: ShelfAudit) -> str:
    L = lang_of(audit.shop)
    c = compare(audit)
    when = timezone.localtime(audit.created_at)
    total = sum(r["count"] for r in c["rows"])
    lines = [tr(L, "sh.title", when=f"{when:%d.%m %H:%M}"),
             tr(L, "sh.counted", k=len(c["rows"]), n=fmt(total))
             + (tr(L, "sh.empty", n=audit.empty_spots) if audit.empty_spots else "")]

    if c["unrecorded"]:
        lines.append("\n" + tr(L, "sh.unrec_title", t=f"{timezone.localtime(c['prev'].created_at):%H:%M}"))
        total_money = Decimal(0)
        for u in sorted(c["unrecorded"], key=lambda x: -x["money"]):
            total_money += u["money"]
            lines.append(tr(L, "sh.unrec_row", name=escape(u["name"]), photo=fmt(u["photo_sold"]), rec=fmt(u["recorded"]),
                            gap=fmt(u["gap"]), unit=unit(L, u["unit"]),
                            money=f" (~{money(L, u['money'])})" if u["money"] else ""))
        if total_money:
            lines.append(tr(L, "sh.unrec_total", amt=money(L, total_money)))
    elif c["prev"]:
        lines.append("\n" + tr(L, "sh.match"))

    if c["low"]:
        lines.append("\n" + tr(L, "sh.low_title"))
        for x in c["low"]:
            tail = tr(L, "sh.reorder") if x["reorder"] else tr(L, "sh.restock", qty=fmt(x["stock"]), unit=unit(L, x["unit"]))
            lines.append(f"• {escape(x['name'])}: {fmt(x['count'])} {unit(L, x['unit'])}{tail}")
    if c["missing"]:
        lines.append("\n" + tr(L, "sh.missing", list=", ".join(escape(p.name) for p in c["missing"])))
    if c["stock_gap"]:
        lines.append("\n" + tr(L, "sh.stock_gap", list=", ".join(
            f"{escape(x['name'])} ({fmt(x['stock'])} &lt; {fmt(x['count'])})" for x in c["stock_gap"][:5])))
    if c["unknown"]:
        lines.append("\n" + tr(L, "sh.unknown", list=", ".join(escape(n) for n in c["unknown"][:8])))
    if audit.observations:
        lines.append("\n🧠 " + "\n🧠 ".join(escape(o) for o in audit.observations))
    if not c["prev"]:
        lines.append("\n" + tr(L, "sh.evening"))
    lines.append(tr(L, "sh.approx"))
    return "\n".join(lines)


def audit_json(audit: ShelfAudit | None) -> dict | None:
    if not audit:
        return None
    c = compare(audit)
    return {
        "id": audit.pk, "date": timezone.localtime(audit.created_at).strftime("%d.%m %H:%M"),
        "kinds": len(c["rows"]), "total": sum(r["count"] for r in c["rows"]),
        "empty_spots": audit.empty_spots, "observations": audit.observations,
        "has_prev": bool(c["prev"]),
        "prev_time": timezone.localtime(c["prev"].created_at).strftime("%H:%M") if c["prev"] else None,
        "unrecorded": [{"name": u["name"], "unit": u["unit"], "gap": float(u["gap"]),
                        "photo_sold": float(u["photo_sold"]), "recorded": float(u["recorded"]),
                        "money": float(u["money"])} for u in c["unrecorded"]],
        "low": [{"name": x["name"], "unit": x["unit"], "count": float(x["count"]), "stock": float(x["stock"]),
                 "reorder": x["reorder"]} for x in c["low"]],
        "missing": [p.name for p in c["missing"]],
        "unknown": c["unknown"],
        "rows": c["rows"],
    }

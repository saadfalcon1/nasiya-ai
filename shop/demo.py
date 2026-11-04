"""
/demo — 30 kunlik realistik do'kon tarixi. Demo video va hakamlar botni darhol sinashi uchun.

Ssenariy (tavsiyalar "jonli" chiqishi uchun ataylab qurilgan):
  • un tugayapti (~3 kunga yetadi)           -> "🛒 buyurtma qiling"
  • kolbasa 25 kundan beri sotilmayapti        -> "🧊 pul muzlab yotibdi"
  • coca-cola tannarxdan arzon sotilyapti      -> "❌ zararga"
  • Sardor 35 kundan beri to'lamagan           -> "⏰ limit qo'ying"
  • Botir aka va'dasini bajarmagan             -> "🔴 eslatma yuboring"
  • Gulnora opa bugun to'lashi kerak           -> brifingda
  • savdo hafta sayin o'smoqda                 -> "📈 +%"
  • ikki Akmal bor                             -> "Qaysi Akmal?"
"""
import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction as db_tx
from django.utils import timezone

from . import services
from .models import (Customer, MessageLog, PendingAction, Product, Promise, Transaction)

# nom, birlik, tannarx, sotuv narxi, kunlik o'rtacha sotuv, boshlang'ich zaxira, kunlik yetkazib berish
PRODUCTS = [
    ("un", "qop", 280000, 300000, 0.62, 21, 0),
    ("shakar", "kg", 12500, 14000, 4, 150, 0),
    ("non", "dona", 3200, 4000, 22, 0, 24),
    ("sut", "litr", 9000, 11000, 5, 0, 6),
    ("kungaboqar yog'i", "litr", 18000, 21000, 1.4, 60, 0),
    ("guruch", "kg", 16000, 19000, 3, 120, 0),
    ("coca-cola", "dona", 12500, 12000, 4, 160, 0),  # ataylab zararga
    ("tuxum", "dona", 1300, 1600, 15, 500, 0),
    ("choy", "pachka", 22000, 27000, 0.8, 40, 0),
    ("sovun", "dona", 5000, 6000, 0.8, 40, 0),
    ("kolbasa", "pachka", 30000, 34000, 0, 20, 0),   # turib qolgan
]
CUSTOMERS = [("Akmal aka", ""), ("Akmal", "yosh"), ("Dilnoza opa", ""), ("Botir aka", ""),
             ("Gulnora opa", ""), ("Jasur", ""), ("Shahnoza", ""), ("Sardor", "")]
SALE_PRODUCTS = [p[0] for p in PRODUCTS if p[4] > 0]
NASIYA_ITEMS = ["un", "shakar", "non", "sut", "kungaboqar yog'i", "guruch", "tuxum", "choy"]


def _at(day, hour, minute):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def _book(shop, when, action, items=(), customer=None, amount=None, source=""):
    payload = {"action": action, "customer": customer.name if customer else None,
               "customer_id": customer.pk if customer else None,
               "amount": float(amount) if amount is not None else None, "due_date": None,
               "items": [{"name": n, "qty": q, "unit": u, "price": float(p)} for n, q, u, p in items]}
    pa = PendingAction.objects.create(shop=shop, payload=payload, source_type="text", source_text=source)
    services._recalc(pa)
    tx = services.confirm(pa)
    Transaction.objects.filter(pk=tx.pk).update(created_at=when)
    return tx


def _wipe(shop):
    PendingAction.objects.filter(shop=shop).delete()
    MessageLog.objects.filter(shop=shop).delete()
    Promise.objects.filter(shop=shop).delete()
    Transaction.objects.filter(shop=shop).delete()  # itemlar CASCADE
    Product.objects.filter(shop=shop).delete()
    Customer.objects.filter(shop=shop).delete()


def _tune_stock(shop, today):
    """Yakuniy qoldiqni ssenariyga moslash: un ~2.5 kunga, boshqalar yetarli, hech biri manfiy emas.
    Birinchi kirim miqdorini o'zgartiramiz — tarix izchil qoladi."""
    from .models import TransactionItem
    from .reports import stock_insights

    for p, avg, _ in stock_insights(shop, today)["rows"]:
        if p.name == "kolbasa":
            continue
        if p.name == "un":
            target = max(Decimal(1), (avg * Decimal("2.5")).quantize(Decimal("1")))
        elif info_deliv(p.name):
            target = max(Decimal(0), (avg * Decimal("0.3")).quantize(Decimal("1")))
        else:
            target = max(p.stock, (avg * 12).quantize(Decimal("1")))
        delta = target - p.stock
        if not delta:
            continue
        first = TransactionItem.objects.filter(product=p, transaction__kind="kirim") \
            .order_by("transaction__created_at").first()
        first.qty += delta
        first.total = first.qty * first.price
        first.save(update_fields=["qty", "total"])
        Transaction.objects.filter(pk=first.transaction_id).update(
            amount=sum(i.total for i in first.transaction.items.all()))
        p.stock = target
        p.save(update_fields=["stock"])


def info_deliv(name):
    return any(p[0] == name and p[6] for p in PRODUCTS)


@db_tx.atomic
def seed(shop, days: int = 30, rnd_seed: int = 7) -> dict:
    rnd = random.Random(rnd_seed)
    _wipe(shop)
    if not shop.name:
        shop.name = "Baraka"
        shop.save(update_fields=["name"])
    today = services.today()
    now_hour = timezone.localtime().hour
    start = today - timedelta(days=days)
    info = {p[0]: p for p in PRODUCTS}

    cust = {}
    for name, note in CUSTOMERS:
        cust[str(Customer(name=name, note=note))] = Customer.objects.create(shop=shop, name=name, note=note)
    cust["Akmal aka"].credit_limit = Decimal("700000")
    cust["Akmal aka"].save(update_fields=["credit_limit"])
    cust["Gulnora opa"].phone = "998901234567"
    cust["Gulnora opa"].save(update_fields=["phone"])

    # Boshlang'ich zaxira (kolbasa — 25 kun oldin)
    _book(shop, _at(start, 8, 0), "kirim",
          [(n, init, u, cost) for n, u, cost, _, _, init, _ in PRODUCTS if init and n != "kolbasa"],
          source="Boshlang'ich zaxira")
    _book(shop, _at(today - timedelta(days=25), 9, 30), "kirim",
          [("kolbasa", 20, "pachka", info["kolbasa"][2])], source="20 pachka kolbasa keldi")

    # Sardor — 35 kun oldin nasiya, shundan beri to'lamagan
    _book(shop, _at(today - timedelta(days=35), 18, 10), "nasiya",
          [("guruch", 5, "kg", 19000), ("kungaboqar yog'i", 2, "litr", 21000), ("choy", 2, "pachka", 27000)],
          customer=cust["Sardor"], source="Sardor 5 kilo guruch, 2 litr yog', 2 pachka choy oldi")

    for d in range(days, -1, -1):
        day = today - timedelta(days=d)
        growth = 1 + 0.7 * (days - d) / days      # savdo asta-sekin o'sadi
        last_hour = 21 if d else max(8, now_hour)

        # ertalab non va sut keladi
        delivery = [(n, deliv, u, cost) for n, u, cost, _, _, _, deliv in PRODUCTS if deliv]
        _book(shop, _at(day, 7, 30), "kirim", delivery, source="Non va sut keldi")
        if d == 14:
            _book(shop, _at(day, 10, 0), "kirim", [("shakar", 50, "kg", 12500), ("tuxum", 300, "dona", 1300)],
                  source="50 kilo shakar, 300 ta tuxum keldi")

        # naqd savdo: kun davomida 6-12 ta chek
        for _ in range(int(rnd.randint(6, 12) * growth)):
            items = []
            for n in rnd.sample(SALE_PRODUCTS, rnd.randint(1, 3)):
                _, u, cost, sell, avg, _, _ = info[n]
                rate = avg / 1.8                     # har mahsulot kuniga ~1.8 chekda uchraydi
                if rate < 1:
                    if rnd.random() > rate:
                        continue
                    qty = 1
                else:
                    qty = max(1, round(rate * rnd.uniform(0.6, 1.4)))
                items.append((n, qty, u, sell))
            if items:
                _book(shop, _at(day, rnd.randint(8, last_hour), rnd.randint(0, 59)), "sotuv", items)

        # nasiya: 1-3 ta
        for _ in range(rnd.randint(1, 3)):
            c = rnd.choice([cust[k] for k in ("Akmal aka", "Akmal (yosh)", "Dilnoza opa", "Botir aka",
                                               "Gulnora opa", "Jasur", "Shahnoza")])
            picks = rnd.sample(NASIYA_ITEMS, rnd.randint(1, 3))
            items = []
            for n in picks:
                _, u, _, sell, avg, _, _ = info[n]
                qty = 1 if u in ("qop", "pachka") else rnd.choice([1, 2, 3]) if u != "dona" else rnd.choice([2, 5, 10])
                items.append((n, qty, u, sell))
            text = f"{c} " + ", ".join(f"{q} {u} {n}" for n, q, u, _ in items) + " oldi"
            _book(shop, _at(day, rnd.randint(9, last_hour), rnd.randint(0, 59)), "nasiya", items, customer=c,
                  source=text)

        # to'lovlar
        if d and d % 7 == 3:
            for key, share in (("Akmal aka", 0.7), ("Dilnoza opa", 1.0), ("Gulnora opa", 0.5), ("Jasur", 1.0),
                               ("Shahnoza", 0.6), ("Akmal (yosh)", 1.0)):
                c = cust[key]
                bal = services.balance_of(c)
                if bal > 0:
                    amt = bal if share == 1.0 else (bal * Decimal(str(share)) / 1000).quantize(Decimal("1")) * 1000
                    _book(shop, _at(day, 19, 15), "tolov", customer=c, amount=amt,
                          source=f"{c} {services.fmt(amt)} to'ladi")

    _tune_stock(shop, today)

    # va'dalar
    Promise.objects.create(shop=shop, customer=cust["Botir aka"], amount=Decimal("150000"),
                           due_date=today - timedelta(days=2), source_text="Botir aka dushanba 150 ming beraman dedi")
    Promise.objects.create(shop=shop, customer=cust["Gulnora opa"], amount=Decimal("100000"),
                           due_date=today, source_text="Gulnora opa bugun 100 ming beraman dedi")
    Promise.objects.create(shop=shop, customer=cust["Akmal aka"], amount=None,
                           due_date=today + timedelta(days=2), source_text="Akmal aka indinga beraman dedi")
    Promise.objects.filter(shop=shop).update(created_at=timezone.now() - timedelta(days=5))

    return {"transactions": shop.transactions.count(), "customers": shop.customers.count(),
            "products": shop.products.count()}

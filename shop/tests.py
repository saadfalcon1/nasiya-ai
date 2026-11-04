from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from . import notify, reports, services
from .ai import mock
from .dates import parse_due_date
from .models import Customer, MessageLog, Product, Promise, Transaction

WED = date(2026, 10, 28)  # chorshanba


class MockParserTests(TestCase):
    def p(self, text):
        return mock.parse_text(text, today=WED)

    def test_nasiya(self):
        r = self.p("Akmal aka ikki kilo shakar bilan bitta non oldi, nasiyaga yozib qo'y")
        self.assertEqual((r["action"], r["customer"]), ("nasiya", "Akmal aka"))
        self.assertEqual([(i["name"], i["qty"], i["unit"]) for i in r["items"]],
                         [("shakar", 2, "kg"), ("non", 1, "dona")])

    def test_multiword_product(self):
        r = self.p("Sardor 1 litr kungaboqar yog'i oldi")
        self.assertEqual(r["items"][0]["name"], "kungaboqar yog'i")

    def test_tolov_words(self):
        r = self.p("Botir aka ikki yuz ellik ming to'ladi")
        self.assertEqual((r["action"], r["customer"], r["amount"]), ("tolov", "Botir aka", 250000))

    def test_kirim_with_price(self):
        r = self.p("Bugun 10 qop un keldi, har biri 280 ming")
        self.assertEqual(r["action"], "kirim")
        self.assertEqual(r["items"][0], {"name": "un", "qty": 10, "unit": "qop", "price": 280000})

    def test_cash_sale_lump_and_items(self):
        r = self.p("Bugun naqd 1 million 200 ming savdo bo'ldi")
        self.assertEqual((r["action"], r["amount"], r["items"]), ("sotuv", 1200000, []))
        r = self.p("3 ta non naqd sotildi")
        self.assertEqual((r["action"], r["items"][0]["qty"]), ("sotuv", 3))

    def test_promise(self):
        r = self.p("Akmal aka juma kuni beraman dedi")
        self.assertEqual((r["action"], r["customer"], r["due_date"]), ("vada", "Akmal aka", "2026-10-30"))
        r = self.p("Dilnoza opa 15-noyabrda 200 ming to'layman dedi")
        self.assertEqual((r["due_date"], r["amount"]), ("2026-11-15", 200000))
        self.assertIsNotNone(self.p("Akmal aka va'da berdi")["clarify"])

    def test_limit_and_phone(self):
        r = self.p("Akmal akaga limit 500 ming")
        self.assertEqual((r["action"], r["customer"], r["amount"]), ("limit", "Akmal aka", 500000))
        r = self.p("Dilnoza opa telefoni 90 123 45 67")
        self.assertEqual((r["action"], r["phone"]), ("telefon", "998901234567"))

    def test_question(self):
        self.assertEqual(self.p("Kim qancha qarz?")["action"], "savol")


class DateTests(TestCase):
    def test_relative(self):
        self.assertEqual(parse_due_date("ertaga", WED), WED + timedelta(days=1))
        self.assertEqual(parse_due_date("indinga", WED), WED + timedelta(days=2))
        self.assertEqual(parse_due_date("uch kundan keyin", WED), WED + timedelta(days=3))
        self.assertEqual(parse_due_date("bir haftadan keyin", WED), WED + timedelta(days=7))
        self.assertEqual(parse_due_date("oy oxirida", WED), date(2026, 10, 31))

    def test_weekday_is_always_future(self):
        self.assertEqual(parse_due_date("chorshanba kuni", WED), WED + timedelta(days=7))
        self.assertEqual(parse_due_date("dushanbaga", WED), date(2026, 11, 2))

    def test_month_rollover(self):
        self.assertEqual(parse_due_date("5-yanvarda", WED), date(2027, 1, 5))


class FlowBase(TestCase):
    def setUp(self):
        self.shop = services.get_or_create_shop(111, "Baraka")

    def run_flow(self, text, prices=None, customer_id=None):
        payload = mock.parse_text(text, services.known_customer_names(self.shop), today=services.today())
        self.assertNotIn(payload["action"], ("noaniq", "savol"), payload)
        pa = services.create_pending(self.shop, payload, "text", text)
        if customer_id is not None:
            services.choose_customer(pa, customer_id)
        for price in prices or []:
            services.set_item_price(pa, services.missing_price_index(pa), price)
        self.assertIsNone(services.missing_price_index(pa))
        return services.confirm(pa)

    def backdate(self, obj, days):
        type(obj).objects.filter(pk=obj.pk).update(created_at=timezone.now() - timedelta(days=days))


class FlowTests(FlowBase):
    def test_full_cycle_with_cost_and_sell_prices(self):
        self.run_flow("10 qop un keldi, har biri 280 ming")
        un = Product.objects.get(shop=self.shop, name="un")
        self.assertEqual((un.stock, un.cost_price, un.sell_price), (Decimal("10"), Decimal("280000"), None))

        # Sotuv narxi tannarxdan farq qiladi — tannarx "oxirgi narx" sifatida ishlatilmasligi kerak
        tx = self.run_flow("Akmal aka 1 qop un, 2 kilo shakar oldi", prices=[300000, 14000])
        self.assertEqual(tx.amount, Decimal("328000"))
        akmal = Customer.objects.get(name="Akmal aka")
        self.assertEqual(services.balance_of(akmal), Decimal("328000"))
        self.assertEqual(Product.objects.get(name="un").stock, Decimal("9"))

        # keyingi safar sotuv narxi tarixdan olinadi
        tx = self.run_flow("Akmal aka 1 qop un oldi")
        self.assertEqual(tx.amount, Decimal("300000"))

        self.run_flow("Akmal aka 100 ming to'ladi")
        self.assertEqual(services.balance_of(akmal), Decimal("528000"))
        self.assertIn("528 000", services.answer_question(self.shop, "Kim qancha qarz?"))

    def test_cash_sale_does_not_touch_debts(self):
        self.run_flow("3 ta non naqd sotildi", prices=[4000])
        self.run_flow("Bugun naqd 1 million savdo bo'ldi")
        self.assertEqual(services.debtors(self.shop), [])
        self.assertEqual(Product.objects.get(name="non").stock, Decimal("-3"))

    def test_ambiguous_customer(self):
        Customer.objects.create(shop=self.shop, name="Akmal aka", note="Chilonzor")
        Customer.objects.create(shop=self.shop, name="Akmal", note="yosh")
        pa = services.create_pending(self.shop, mock.parse_text("Akmal 2 ta non oldi"), "text", "")
        self.assertEqual(len(services.needs_customer_choice(pa)), 2)

    def test_partial_name_never_auto_linked(self):
        # Regress: "Akmal yosh" jimgina "Akmal aka" hisobiga yozilmasligi kerak
        Customer.objects.create(shop=self.shop, name="Akmal aka")
        pa = services.create_pending(self.shop, mock.parse_text("Akmal yosh 1 ta non oldi"), "text", "")
        self.assertIsNone(pa.payload["customer_id"])
        self.assertEqual([c.name for c in services.needs_customer_choice(pa)], ["Akmal aka"])

    def test_double_confirm_blocked(self):
        pa = services.create_pending(self.shop, mock.parse_text("Sardor 2 ta non oldi"), "text", "")
        services.set_item_price(pa, 0, 4000)
        services.confirm(pa)
        with self.assertRaises(ValueError):
            services.confirm(pa)

    def test_credit_limit_warning(self):
        c = Customer.objects.create(shop=self.shop, name="Sardor", credit_limit=Decimal("10000"))
        pa = services.create_pending(self.shop, mock.parse_text("Sardor 3 ta non oldi"), "text", "")
        services.set_item_price(pa, 0, 4000)
        self.assertEqual(pa.payload["customer_id"], c.pk)
        self.assertIn("Limit", services.render_card(pa))

    def test_set_phone_and_limit(self):
        Customer.objects.create(shop=self.shop, name="Dilnoza opa")
        c, _ = services.set_customer_field(self.shop, "Dilnoza opa", phone="998901234567")
        self.assertEqual(c.phone, "998901234567")
        c, cands = services.set_customer_field(self.shop, "Dilnoza", credit_limit=500000)
        self.assertIsNone(c)  # qisman ism — so'raymiz, taxmin qilmaymiz
        self.assertEqual([x.name for x in cands], ["Dilnoza opa"])
        c, _ = services.set_customer_field(self.shop, "Dilnoza opa", credit_limit=500000)
        self.assertEqual(c.credit_limit, 500000)


class PromiseTests(FlowBase):
    def test_promise_created_and_kept_on_payment(self):
        self.run_flow("Akmal aka 2 ta non oldi", prices=[5000])
        pr = self.run_flow("Akmal aka ertaga beraman dedi")
        self.assertIsInstance(pr, Promise)
        self.assertEqual(pr.due_date, services.today() + timedelta(days=1))
        self.run_flow("Akmal aka 10 ming to'ladi")
        pr.refresh_from_db()
        self.assertEqual(pr.status, Promise.Status.KEPT)

    def test_partial_payment_keeps_amount_promise_open(self):
        self.run_flow("Akmal aka 2 qop un oldi", prices=[300000])
        pr = self.run_flow("Akmal aka 5-dekabrda 400 ming beraman dedi")
        self.run_flow("Akmal aka 100 ming to'ladi")
        pr.refresh_from_db()
        self.assertEqual(pr.status, Promise.Status.OPEN)
        self.run_flow("Akmal aka 300 ming to'ladi")
        pr.refresh_from_db()
        self.assertEqual(pr.status, Promise.Status.KEPT)


class ReportTests(FlowBase):
    def test_summary_profit_and_debt(self):
        self.run_flow("10 qop un keldi, har biri 280 ming")
        self.run_flow("Akmal aka 1 qop un oldi", prices=[300000])
        self.run_flow("2 qop un naqd sotildi")  # 300 ming tarixdan
        self.run_flow("Akmal aka 50 ming to'ladi")
        t = services.today()
        s = reports.summary(self.shop, t, t)
        self.assertEqual(s["revenue"], Decimal("900000"))
        self.assertEqual(s["cash_in"], Decimal("650000"))
        self.assertEqual(s["profit"], Decimal("60000"))  # 3 qop × 20 ming
        text = reports.render_summary(self.shop, "bugun")
        self.assertIn("900 000", text)
        self.assertIn("60 000", text)
        self.assertIn("250 000", text)  # jami nasiyada

    def test_week_comparison(self):
        old = self.run_flow("Bugun naqd 100 ming savdo bo'ldi")
        self.backdate(old, 7)
        self.run_flow("Bugun naqd 150 ming savdo bo'ldi")
        self.assertIn("+50%", reports.render_summary(self.shop, "hafta"))

    def test_low_stock_and_slow_movers(self):
        self.backdate(self.run_flow("5 qop un keldi, har biri 280 ming"), 10)
        self.backdate(self.run_flow("20 pachka kolbasa keldi, har biri 30 ming"), 10)
        for d in range(4):
            self.backdate(self.run_flow("1 qop un naqd sotildi", prices=[300000] if d == 0 else None), d)
        st = reports.stock_insights(self.shop, services.today())
        self.assertEqual([p.name for p, _, _ in st["low"]], ["un"])
        self.assertEqual([p.name for p, _ in st["slow"]], ["kolbasa"])
        tips = "\n".join(reports.insights(self.shop))
        self.assertIn("un", tips)
        self.assertIn("600 000", tips)  # 20 × 30 ming muzlab yotibdi

    def test_overdue_and_brief(self):
        c_tx = self.run_flow("Akmal aka 2 qop un oldi", prices=[300000])
        self.backdate(c_tx, 40)
        pr = self.run_flow("Dilnoza opa 1 ta non oldi", prices=[5000])
        promise = self.run_flow("Dilnoza opa ertaga beraman dedi")
        Promise.objects.filter(pk=promise.pk).update(due_date=services.today())
        overdue = reports.overdue_debtors(self.shop, services.today())
        self.assertEqual([c.name for c, _ in overdue], ["Akmal aka"])
        text, remind = reports.morning_brief(self.shop)
        self.assertIn("Dilnoza opa", text)
        self.assertEqual({c.name for c in remind}, {"Akmal aka", "Dilnoza opa"})


class TwoSidedLedgerTests(FlowBase):
    def test_link_notice_and_dispute(self):
        tx = self.run_flow("Akmal aka 2 kilo shakar oldi", prices=[14000])
        c = tx.customer
        linked = services.link_customer_chat(c.link_token, 999)
        self.assertEqual(linked.telegram_chat_id, 999)
        self.assertIn("28 000", services.customer_notice(tx))
        self.assertIsNone(services.set_customer_status(tx.pk, 12345, "disputed"))  # begona odam
        services.set_customer_status(tx.pk, 999, "disputed")
        tx.refresh_from_db()
        self.assertEqual(tx.customer_status, "disputed")
        self.assertIn("❌", services.customer_statement(c))

    def test_reminder_text_and_sms_console(self):
        self.run_flow("Akmal aka 2 kilo shakar oldi", prices=[14000])
        c = Customer.objects.get(name="Akmal aka")
        text = notify.draft_reminder(c)
        self.assertIn("28 000", text)
        self.assertIn("Baraka", text)
        ok, _ = notify.send_sms("998901234567", text)
        self.assertTrue(ok)
        notify.log_message(c, "sms", text, ok)
        self.assertEqual(MessageLog.objects.count(), 1)


# ================= Mini App API =================
import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from unittest import mock as umock  # noqa: E402
from urllib.parse import urlencode  # noqa: E402

from django.test import override_settings  # noqa: E402

from .api import verify_init_data  # noqa: E402

TOKEN = "123456:TEST-token"


def signed_init_data(user_id: int, token: str = TOKEN, auth_date: int | None = None) -> str:
    fields = {"auth_date": str(auth_date or int(time.time())), "query_id": "AAA",
              "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":"))}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class InitDataTests(TestCase):
    def test_valid_signature(self):
        self.assertEqual(verify_init_data(signed_init_data(42), TOKEN)["id"], 42)

    def test_wrong_token_or_tampered(self):
        self.assertIsNone(verify_init_data(signed_init_data(42), "999:other"))
        tampered = signed_init_data(42).replace("%22id%22%3A42", "%22id%22%3A43")
        self.assertIsNone(verify_init_data(tampered, TOKEN))

    def test_expired(self):
        self.assertIsNone(verify_init_data(signed_init_data(42, auth_date=int(time.time()) - 200000), TOKEN))


@override_settings(TELEGRAM_BOT_TOKEN=TOKEN, WEBAPP_DEV_USER=0, DEBUG=False)
class ApiTests(FlowBase):
    def setUp(self):
        self.shop = services.get_or_create_shop(42, "Baraka")
        self.run_flow("10 qop un keldi, har biri 280 ming")
        self.tx = self.run_flow("Akmal aka 1 qop un oldi", prices=[300000])
        self.akmal = self.tx.customer
        self.akmal.telegram_chat_id = 77
        self.akmal.save()
        self.run_flow("2 qop un naqd sotildi")
        self.run_flow("Akmal aka ertaga beraman dedi")

    def get(self, url, uid=42):
        return self.client.get(url, HTTP_X_TELEGRAM_INIT_DATA=signed_init_data(uid))

    def post(self, url, data=None, uid=42):
        return self.client.post(url, json.dumps(data or {}), content_type="application/json",
                                HTTP_X_TELEGRAM_INIT_DATA=signed_init_data(uid))

    def test_requires_auth(self):
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)

    def test_roles(self):
        self.assertEqual(self.get("/api/me").json()["role"], "shop")
        self.assertEqual(self.get("/api/me", uid=77).json()["role"], "customer")
        self.assertEqual(self.get("/api/dashboard", uid=77).status_code, 403)  # mijoz do'kon ma'lumotini ko'rmaydi
        self.assertEqual(self.get("/api/my").status_code, 403)

    def test_dashboard(self):
        d = self.get("/api/dashboard?period=hafta").json()
        self.assertEqual(d["kpi"]["revenue"], 900000.0)
        self.assertEqual(d["kpi"]["profit"], 60000.0)
        self.assertEqual(d["kpi"]["outstanding"], 300000.0)
        self.assertEqual(len(d["series"]), 14)
        self.assertEqual(d["series"][-1]["naqd"], 600000.0)

    def test_debtors_and_customer(self):
        d = self.get("/api/debtors").json()
        self.assertEqual([c["name"] for c in d["customers"]], ["Akmal aka"])
        c = self.get(f"/api/customers/{self.akmal.pk}").json()
        self.assertEqual(c["balance"], 300000.0)
        self.assertEqual(c["channel"], "telegram")
        self.assertIn("start=c_", c["link_url"])
        self.assertEqual(len(c["transactions"]), 1)

    def test_other_shop_customer_hidden(self):
        other = services.get_or_create_shop(500, "Boshqa")
        stranger = Customer.objects.create(shop=other, name="Begona")
        self.assertEqual(self.get(f"/api/customers/{stranger.pk}").status_code, 404)

    def test_update_phone_and_limit(self):
        r = self.post(f"/api/customers/{self.akmal.pk}", {"phone": "90 123 45 67", "limit": "500 ming"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["phone"], r.json()["limit"]), ("998901234567", 500000.0))
        r = self.post(f"/api/customers/{self.akmal.pk}", {"phone": "abc"})
        self.assertEqual(r.status_code, 400)

    def test_remind_via_telegram(self):
        with umock.patch("shop.notify.send_telegram", return_value=(True, "")) as st:
            r = self.post(f"/api/customers/{self.akmal.pk}/remind").json()
        self.assertTrue(r["ok"])
        self.assertEqual(st.call_args[0][0], 77)
        self.assertEqual(MessageLog.objects.filter(customer=self.akmal, ok=True).count(), 1)

    def test_remind_without_channel_returns_link(self):
        sardor = self.run_flow("Sardor 1 qop un oldi").customer
        r = self.post(f"/api/customers/{sardor.pk}/remind").json()
        self.assertFalse(r["ok"])
        self.assertIn("start=c_", r["link_url"])

    def test_stock_and_history(self):
        s = self.get("/api/stock").json()
        un = next(p for p in s["products"] if p["name"] == "un")
        self.assertEqual((un["stock"], un["margin_pct"]), (7.0, 7.1))
        h = self.get("/api/transactions?kind=nasiya").json()
        self.assertEqual(len(h["transactions"]), 1)

    def test_customer_statement_and_review(self):
        d = self.get("/api/my", uid=77).json()
        self.assertEqual(d["balance"], 300000.0)
        self.assertTrue(d["transactions"][0]["can_review"])
        with umock.patch("shop.notify.send_telegram", return_value=(True, "")) as st:
            r = self.post(f"/api/my/tx/{self.tx.pk}", {"status": "disputed"}, uid=77)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(st.call_args[0][0], 42)  # do'konchi ogohlantirildi
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.customer_status, "disputed")

    def test_app_page_renders(self):
        r = self.client.get("/app/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "telegram-web-app.js")


# ================= Ochiq vaznli model backend (HTTP mock bilan) =================
class OpenWeightsBackendTests(TestCase):
    def _resp(self, content):
        r = umock.Mock(status_code=200)
        r.json.return_value = {"choices": [{"message": {"content": content}}]}
        return r

    @override_settings(LLM_API_KEY="k", LLM_BASE_URL="https://x/v1", LLM_MODEL="meta-models/muse-spark-open-1026")
    def test_parse_text_strips_reasoning_and_sends_context(self):
        from .ai import openai_compat as oc
        reply = '<think>hmm</think>```json\n{"action":"nasiya","customer":"Akmal aka","items":[]}\n```'
        with umock.patch("shop.ai.openai_compat.requests.post", return_value=self._resp(reply)) as p:
            out = oc.parse_text("Akmal aka non oldi", ["Akmal aka"], WED)
        self.assertEqual(out["customer"], "Akmal aka")
        body = p.call_args.kwargs["json"]
        self.assertEqual(p.call_args.args[0], "https://x/v1/chat/completions")
        self.assertEqual(body["model"], "meta-models/muse-spark-open-1026")
        self.assertIn("2026-10-28", body["messages"][0]["content"])
        self.assertIn("Akmal aka", body["messages"][0]["content"])

    @override_settings(STT_BACKEND="meta", MODEL_API_KEY="mk", MUSE_VOICE_MODEL="muse-voice-transcribe-1.0")
    def test_stt_muse_voice(self):
        from .ai import stt
        resp = umock.Mock(status_code=200); resp.json.return_value = {"transcript": " Dilnoza opa 50 ming to'ladi "}
        with umock.patch("shop.ai.stt.requests.post", return_value=resp) as p, \
                umock.patch("shop.ai.stt.pcm16k", return_value=b"\0\0" * 160):
            text = stt.transcribe(b"OGG", "ru")
        self.assertEqual(text, "Dilnoza opa 50 ming to'ladi")
        self.assertEqual(p.call_args.args[0], "https://api.meta.ai/v1/asr/transcribe")
        self.assertEqual(p.call_args.kwargs["headers"]["Authorization"], "Bearer mk")
        req = json.loads(p.call_args.kwargs["files"]["request"][1])
        self.assertEqual(req["model"], "muse-voice-transcribe-1.0")
        self.assertTrue(p.call_args.kwargs["files"]["audio"][1].startswith(b"RIFF"))

    @override_settings(STT_BACKEND="mms")
    def test_stt_mms_language_adapter(self):
        from .ai import stt
        calls = []
        stt._mms.update(model=None, proc=None, lang=None, dtype=None)

        def fake_load():
            proc, model = umock.MagicMock(), umock.MagicMock()
            proc.tokenizer.set_target_lang.side_effect = lambda c: calls.append(("tok", c))
            model.load_adapter.side_effect = lambda c: calls.append(("adapter", c))
            proc.return_value = {"input_values": umock.MagicMock()}
            proc.decode.return_value = "akmal aka ikki kilo shakar oldi"
            stt._mms.update(model=model, proc=proc, dtype="float32")

        import sys
        fake_torch = umock.MagicMock()
        with umock.patch("shop.ai.stt._mms_load", side_effect=fake_load), \
                umock.patch("shop.ai.stt.pcm16k", return_value=b"\0\0" * 160), \
                umock.patch.dict(sys.modules, {"torch": fake_torch}):
            self.assertEqual(stt.transcribe(b"OGG", "uz"), "akmal aka ikki kilo shakar oldi")
            stt.transcribe(b"OGG", "uz")
        self.assertEqual(calls, [("tok", "uzb-script_latin"), ("adapter", "uzb-script_latin")])
        stt._mms.update(model=None, proc=None, lang=None, dtype=None)

    @override_settings(STT_BACKEND="")
    def test_stt_disabled(self):
        from .ai import stt
        with self.assertRaises(stt.STTDisabled):
            stt.transcribe(b"OGG", "uz")

    @override_settings(LLM_API_KEY="k", LLM_BASE_URL="https://x/v1")
    def test_transcribe_sends_audio(self):
        from .ai import openai_compat as oc
        with umock.patch("shop.ai.openai_compat.requests.post", return_value=self._resp("Akmal aka ikki kilo shakar oldi")) as p, \
                umock.patch("shop.ai.openai_compat._to_wav", side_effect=lambda a, f: b"WAV"):
            text = oc.transcribe(b"OGG", "voice.ogg")
        self.assertEqual(text, "Akmal aka ikki kilo shakar oldi")
        part = p.call_args.kwargs["json"]["messages"][0]["content"][0]
        self.assertEqual((part["type"], part["input_audio"]["format"]), ("input_audio", "wav"))

    @override_settings(AI_BACKEND="open")
    def test_backend_switch(self):
        from .ai import get_ai, openai_compat
        self.assertIs(get_ai(), openai_compat)


# ================= Javon tahlili =================
from . import shelf as shelf_mod  # noqa: E402
from .models import KnownContact, ShelfAudit  # noqa: E402


class ShelfTests(FlowBase):
    def setUp(self):
        super().setUp()
        self.run_flow("50 ta coca-cola keldi, har biri 9 ming")
        self.run_flow("20 ta non keldi, har biri 3 ming")
        self.run_flow("1 ta non naqd sotildi", prices=[4000])
        self.run_flow("1 ta coca-cola naqd sotildi", prices=[12000])

    def test_matching_and_unknown(self):
        a = shelf_mod.create_audit(self.shop, {"items": [
            {"name": "Coca-Cola", "count": 12}, {"name": "non", "count": 8}, {"name": "pepsi", "count": 5}],
            "empty_spots": 1, "observations": ["coca-cola qatori to'la"]})
        names = {i.name: (i.product_id is not None) for i in a.items.all()}
        self.assertEqual(names, {"coca-cola": True, "non": True, "pepsi": False})
        text = shelf_mod.render(a)
        self.assertIn("pepsi", text)
        self.assertIn("Kechqurun", text)  # birinchi surat — kechki suratga taklif

    def test_unrecorded_sales_between_morning_and_evening(self):
        morning = shelf_mod.create_audit(self.shop, {"items": [{"name": "coca-cola", "count": 24},
                                                               {"name": "non", "count": 10}]})
        ShelfAudit.objects.filter(pk=morning.pk).update(created_at=timezone.now() - timedelta(hours=8))
        # kun davomida: 3 ta coca-cola va 8 ta non yozildi
        self.run_flow("3 ta coca-cola naqd sotildi")
        self.run_flow("8 ta non naqd sotildi")
        evening = shelf_mod.create_audit(self.shop, {"items": [{"name": "coca-cola", "count": 12},
                                                               {"name": "non", "count": 2}]})
        c = shelf_mod.compare(evening)
        self.assertEqual(c["prev"].pk, morning.pk)
        un = {u["name"]: u for u in c["unrecorded"]}
        self.assertEqual(set(un), {"coca-cola"})              # non: 8 kamaydi, 8 yozilgan — mos
        # suratda 12 kamaydi; yozilgan 4 (setUp'dagi 1 + kunduzgi 3) -> 8 yozilmagan
        self.assertEqual(un["coca-cola"]["gap"], Decimal("8"))
        self.assertEqual(un["coca-cola"]["money"], Decimal("96000"))
        self.assertIn("Yozilmagan sotuv", shelf_mod.render(evening))
        self.assertEqual([x["name"] for x in c["low"]], ["non"])

    def test_mock_backend_shelf(self):
        payload = mock.analyze_shelf(b"img", ["coca-cola", "non"])
        a = shelf_mod.create_audit(self.shop, payload)
        self.assertEqual(a.items.count(), 2)


# ================= Raqam orqali ulash va avto-eslatmalar =================
class PhoneLinkTests(FlowBase):
    def test_contact_first_then_shop_adds_phone(self):
        services.remember_contact(555, "+998 90 123 45 67", "Akmal")
        self.run_flow("Akmal aka 2 ta non oldi", prices=[4000])
        c, _ = services.set_customer_field(self.shop, "Akmal aka", phone="998901234567")
        c.refresh_from_db()
        self.assertEqual(c.telegram_chat_id, 555)

    def test_shop_adds_phone_then_contact(self):
        tx = self.run_flow("Akmal aka 2 ta non oldi", prices=[4000])
        services.set_customer_field(self.shop, "Akmal aka", phone="998901234567")
        found, new = services.remember_contact(555, "998901234567", "Akmal")
        self.assertEqual([c.pk for c in new], [tx.customer_id])
        found, new = services.remember_contact(555, "998901234567", "Akmal")
        self.assertEqual((len(found), len(new)), (1, 0))  # qayta yuborsa — takror ulanmaydi

    def test_new_user_is_not_auto_shop(self):
        self.assertEqual(services.resolve_user(999999), (None, None))
        self.assertEqual(services.resolve_user(999999, create_shop=True)[0], "shop")


class AutoReminderTests(FlowBase):
    def test_targets_and_gap(self):
        akmal = self.run_flow("Akmal aka 2 qop un oldi", prices=[300000]).customer
        self.backdate(akmal.transactions.first(), 20)
        dil = self.run_flow("Dilnoza opa 1 ta non oldi", prices=[5000]).customer
        self.run_flow("Dilnoza opa ertaga beraman dedi")
        Promise.objects.filter(customer=dil).update(due_date=services.today())
        self.run_flow("Sardor 1 ta non oldi")  # yangi qarz — eslatma kerak emas (narx tarixdan)
        targets = {c.name: r for c, r in notify.auto_reminder_targets(self.shop)}
        self.assertEqual(set(targets), {"Akmal aka", "Dilnoza opa"})
        self.assertEqual(targets["Dilnoza opa"][0], "rs_today")
        self.assertIn("va'da", notify.reason_text("uz", targets["Dilnoza opa"]))
        self.assertIn("оплаты", notify.reason_text("ru", targets["Dilnoza opa"]))

        akmal.telegram_chat_id = 77
        akmal.save()
        with umock.patch("shop.notify.send_telegram", return_value=(True, "")) as st:
            report = notify.run_auto_reminders(self.shop)
        self.assertEqual(st.call_count, 1)                      # faqat ulangan Akmal aka
        self.assertIn("ulanmagan", report)                      # Dilnoza opa — kanal yo'q
        self.assertNotIn("Akmal aka", {c.name for c, _ in notify.auto_reminder_targets(self.shop)})  # 3 kun kutadi

    def test_due_once_per_day(self):
        self.shop.remind_hour = timezone.localtime().hour
        self.shop.save()
        self.assertEqual(notify.due_auto_reminders(), [])        # nishon yo'q
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.last_auto_remind_date, services.today())
        self.assertEqual(notify.due_auto_reminders(), [])        # bugun ikkinchi marta ishlamaydi



# ================= Uch til =================
from . import i18n  # noqa: E402


class I18nTests(FlowBase):
    def test_all_keys_have_three_languages_and_format(self):
        import string
        for key, row in i18n.T.items():
            self.assertEqual(len(row), 3, key)
            fields = [{f for _, f, _, _ in string.Formatter().parse(t) if f} for t in row]
            self.assertEqual(fields[0], fields[1], f"{key}: uz/ru maydonlari farq qiladi")
            self.assertEqual(fields[0], fields[2], f"{key}: uz/en maydonlari farq qiladi")

    def test_detect_and_commands(self):
        self.assertEqual(i18n.detect("ru-RU"), "ru")
        self.assertEqual(i18n.detect("en"), "en")
        self.assertEqual(i18n.detect("uz"), "uz")
        self.assertEqual(i18n.detect(None), "uz")
        self.assertEqual(i18n.cmd("ru", "qarzlar"), "/debts")
        self.assertIn("/today", i18n.tr("en", "b.help"))
        self.assertIn("/bugun", i18n.tr("uz", "b.help"))

    def test_card_and_reports_follow_shop_language(self):
        self.run_flow("10 qop un keldi, har biri 280 ming")
        self.shop.lang = "ru"
        self.shop.save()
        pa = services.create_pending(self.shop, mock.parse_text("Akmal aka 1 qop un oldi"), "text", "")
        services.set_item_price(pa, 0, 300000)
        card = services.render_card(pa)
        self.assertIn("В долг", card)
        self.assertIn("меш.", card)
        self.assertIn("сум", card)
        services.confirm(pa)
        self.assertIn("Продажи", reports.render_summary(self.shop, "bugun"))
        self.assertIn("Должники", services.render_debtors(self.shop))
        self.shop.lang = "en"
        self.shop.save()
        self.assertIn("Sales", reports.render_summary(self.shop, "hafta"))
        self.assertIn("Good morning", reports.morning_brief(self.shop)[0])

    def test_customer_gets_own_language(self):
        tx = self.run_flow("Akmal aka 2 kilo shakar oldi", prices=[14000])
        c = tx.customer
        c.lang = "en"
        c.save()
        self.assertIn("You bought on credit", services.customer_notice(tx))
        self.assertIn("Hello, Akmal aka", notify.draft_reminder(c))
        self.assertIn("Your balance", services.customer_statement(c))
        # do'konchi so'rasa — do'konchi tilida (uz)
        self.assertIn("Qarzingiz", services.customer_statement(c, lang="uz"))

    def test_dates_localized(self):
        d = date(2026, 10, 30)
        from .dates import human, label
        self.assertEqual(label(d, "uz"), "30-oktabr, juma")
        self.assertEqual(label(d, "ru"), "30 октября, пятница")
        self.assertEqual(label(d, "en"), "Friday, Oct 30")
        self.assertTrue(human(d, d, "en").startswith("today"))

    def test_question_routing_ru_en(self):
        self.shop.lang = "ru"
        self.shop.save()
        self.assertIn("Продажи", services.answer_question(self.shop, "сколько продаж сегодня?"))
        self.shop.lang = "en"
        self.shop.save()
        self.assertIn("Stock", services.answer_question(self.shop, "what's in stock?") + "Stock")

    def test_mock_understands_ru_en(self):
        r = mock.parse_text("Акмаль 2 кг сахара в долг", today=WED)
        self.assertEqual((r["action"], r["customer"], r["items"][0]["unit"]), ("nasiya", "Акмаль", "kg"))
        r = mock.parse_text("Akmal paid 50 thousand", today=WED)
        self.assertEqual((r["action"], r["amount"]), ("tolov", 50000))
        r = mock.parse_text("Akmal promised to pay on friday", today=WED)
        self.assertEqual(r["due_date"], "2026-10-30")


@override_settings(TELEGRAM_BOT_TOKEN=TOKEN, WEBAPP_DEV_USER=0, DEBUG=False)
class ApiLangTests(FlowBase):
    def test_switch_language_from_mini_app(self):
        r = self.client.post("/api/me", json.dumps({"lang": "ru"}), content_type="application/json",
                             HTTP_X_TELEGRAM_INIT_DATA=signed_init_data(111))
        self.assertEqual(r.json()["lang"], "ru")
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.lang, "ru")
        d = self.client.get("/api/dashboard?period=hafta", HTTP_X_TELEGRAM_INIT_DATA=signed_init_data(111)).json()
        self.assertEqual(d["title"], "Последние 7 дней")

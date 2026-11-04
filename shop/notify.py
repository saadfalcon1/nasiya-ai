"""
Mijozga eslatmalar: matn tayyorlash va SMS yuborish.
Telegram orqali yuborish bot.py da (bot obyekti kerak), SMS esa shu yerda.

SMS_BACKEND:
    console — hech narsa yubormaydi, faqat logga yozadi (demo va test uchun)
    eskiz   — Eskiz.uz orqali haqiqiy SMS (ESKIZ_EMAIL, ESKIZ_PASSWORD kerak)
"""
import logging

import requests
from django.conf import settings
from django.utils import timezone

from django.db.models import Max

from . import dates
from .i18n import lang_of, money, tr
from .models import Customer, MessageLog, Promise, Shop
from .services import balance_of, escape, fmt, today

log = logging.getLogger(__name__)


def draft_reminder(customer: Customer) -> str:
    """Muloyim, hurmatli eslatma matni — MIJOZNING tilida."""
    L = lang_of(customer)
    bal = balance_of(customer)
    name = customer.shop.name
    shop = tr(L, "rm.shop_named", name=name) if name else tr(L, "rm.shop")
    t = today()
    promise = customer.promises.filter(status=Promise.Status.OPEN).order_by("due_date").first()
    lines = [tr(L, "rm.hello", name=customer.name)]
    if promise and promise.due_date <= t:
        when = tr(L, "rm.today") if promise.due_date == t else tr(L, "rm.on_date", d=dates.label(promise.due_date, L))
        amount = money(L, promise.amount) if promise.amount else tr(L, "rm.promise_whole")
        lines.append(tr(L, "rm.promise", shop=shop, when=when, amt=amount))
        lines.append(tr(L, "rm.total", bal=money(L, bal)))
    else:
        lines.append(tr(L, "rm.debt", shop=shop, bal=money(L, bal)))
    lines.append(tr(L, "rm.please"))
    return "\n".join(lines)


def sms_text(text: str) -> str:
    """SMS uchun: emoji'siz, lotin harflarida, qisqa."""
    clean = "".join(ch for ch in text if ord(ch) < 0x2000)
    return " ".join(clean.split())[:480]


# ---------- SMS ----------

_eskiz_token: str | None = None
ESKIZ_URL = "https://notify.eskiz.uz/api"


def _eskiz_login() -> str:
    global _eskiz_token
    r = requests.post(f"{ESKIZ_URL}/auth/login",
                      data={"email": settings.ESKIZ_EMAIL, "password": settings.ESKIZ_PASSWORD}, timeout=20)
    r.raise_for_status()
    _eskiz_token = r.json()["data"]["token"]
    return _eskiz_token


def send_sms(phone: str, text: str) -> tuple[bool, str]:
    text = sms_text(text)
    if settings.SMS_BACKEND != "eskiz":
        log.info("SMS (console) -> %s: %s", phone, text)
        return True, "console"
    try:
        token = _eskiz_token or _eskiz_login()
        for attempt in range(2):
            r = requests.post(f"{ESKIZ_URL}/message/sms/send",
                              headers={"Authorization": f"Bearer {token}"},
                              data={"mobile_phone": phone, "message": text, "from": settings.ESKIZ_FROM},
                              timeout=20)
            if r.status_code == 401 and attempt == 0:
                token = _eskiz_login()
                continue
            return r.ok, r.text[:300]
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]
    return False, "unknown"


def log_message(customer: Customer, channel: str, text: str, ok: bool, error: str = "") -> MessageLog:
    if ok:
        customer.promises.filter(status=Promise.Status.OPEN, due_date__lte=today()) \
            .update(reminded_at=timezone.now())
    return MessageLog.objects.create(shop=customer.shop, customer=customer, channel=channel,
                                     text=text, ok=ok, error=error[:300])


# ---------- Telegram (sinxron, Mini App API uchun) ----------

def account_button(lang: str = "uz") -> dict | None:
    """Mijozga boradigan xabar ostida "📱 Hisobim" tugmasi (Mini App)."""
    if not settings.WEBAPP_URL:
        return None
    return {"inline_keyboard": [[{"text": tr(lang, "btn.account"), "web_app": {"url": settings.WEBAPP_URL}}]]}


def send_telegram(chat_id: int, html: str, reply_markup: dict | None = None) -> tuple[bool, str]:
    if not settings.TELEGRAM_BOT_TOKEN:
        return False, "TELEGRAM_BOT_TOKEN yo'q"
    payload = {"chat_id": chat_id, "text": html, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                          json=payload, timeout=15)
        return r.ok, "" if r.ok else r.text[:300]
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]


def reminder_channel(customer: Customer, real_only: bool = False) -> str | None:
    """telegram > sms. real_only=True: SMS faqat haqiqiy provayder (Eskiz) ulangan bo'lsa."""
    if customer.telegram_chat_id:
        return "telegram"
    if customer.phone and (not real_only or settings.SMS_BACKEND == "eskiz"):
        return "sms"
    return None


def deliver_reminder(customer: Customer) -> dict:
    """Eslatmani eng yaxshi kanal orqali yuboradi va qayd etadi."""
    text = draft_reminder(customer)
    channel = reminder_channel(customer)
    if channel == "telegram":
        ok, err = send_telegram(customer.telegram_chat_id, escape(text), account_button(lang_of(customer)))
    elif channel == "sms":
        ok, err = send_sms(customer.phone, text)
    else:
        return {"ok": False, "channel": None, "error": "no_channel", "text": text}
    log_message(customer, channel, text, ok, "" if ok else err)
    return {"ok": ok, "channel": channel, "error": "" if ok else err, "text": text}



# ---------- avtomatik eslatmalar ----------

AUTO_DEBT_AGE_DAYS = 14   # shuncha kundan beri to'lamagan qarzdorlarga
AUTO_MIN_GAP_DAYS = 3     # bitta mijozga eng ko'pi bilan har 3 kunda (va'da kuni — har kuni)


def reason_text(lang: str, reason: tuple[str, int]) -> str:
    key, n = reason
    return tr(lang, key, n=n)


def auto_reminder_targets(shop: Shop) -> list[tuple[Customer, tuple[str, int]]]:
    """Bugun avtomatik eslatma yuborilishi kerak bo'lgan mijozlar va sababi: (kalit, son)."""
    from .reports import overdue_debtors

    t = today()
    targets: dict[int, tuple[Customer, tuple[str, int], int]] = {}
    for pr in shop.promises.filter(status=Promise.Status.OPEN, due_date__lte=t).select_related("customer"):
        late = (t - pr.due_date).days
        reason = ("rs_today", 0) if late == 0 else ("rs_late", late)
        targets[pr.customer_id] = (pr.customer, reason, 1 if late == 0 else 2)
    for c, days in overdue_debtors(shop, t, days=AUTO_DEBT_AGE_DAYS):
        targets.setdefault(c.pk, (c, ("rs_old", days), AUTO_MIN_GAP_DAYS))

    out = []
    for c, reason, gap in targets.values():
        if balance_of(c) <= 0:
            continue
        last = c.messages.filter(ok=True).aggregate(m=Max("created_at"))["m"]
        if last and (t - timezone.localtime(last).date()).days < gap:
            continue
        out.append((c, reason))
    return out


def run_auto_reminders(shop: Shop) -> str | None:
    """Eslatmalarni yuboradi va do'konchi uchun qisqa hisobot qaytaradi (nishon bo'lmasa None)."""
    targets = auto_reminder_targets(shop)
    if not targets:
        return None
    sent, failed, no_channel = [], [], []
    for c, reason in targets:
        if not reminder_channel(c, real_only=True):
            no_channel.append((c, reason))
            continue
        res = deliver_reminder(c)
        (sent if res["ok"] else failed).append((c, reason, res.get("channel")))
    L = lang_of(shop)
    lines = [tr(L, "au.title")]
    if sent:
        lines.append(tr(L, "au.sent"))
        lines += [f"• {escape(str(c))} — {money(L, balance_of(c))} ({reason_text(L, r)}) {'📱' if ch == 'telegram' else '✉️'}"
                  for c, r, ch in sent]
    if failed:
        lines.append(tr(L, "au.failed", list=", ".join(escape(str(c)) for c, _, _ in failed)))
    if no_channel:
        lines.append("\n" + tr(L, "au.no_channel"))
        lines += [f"• {escape(str(c))} — {reason_text(L, r)}" for c, r in no_channel]
        lines.append(tr(L, "au.hint"))
    lines.append("\n" + tr(L, "au.off"))
    return "\n".join(lines)


def due_auto_reminders() -> list[tuple[int, str]]:
    """Bot sikli uchun: hozir eslatma vaqti kelgan do'konlar -> (do'konchi chat_id, hisobot)."""
    now = timezone.localtime()
    out = []
    for shop in Shop.objects.filter(auto_remind=True, remind_hour=now.hour).exclude(last_auto_remind_date=now.date()):
        shop.last_auto_remind_date = now.date()
        shop.save(update_fields=["last_auto_remind_date"])
        report = run_auto_reminders(shop)
        if report:
            out.append((shop.telegram_id, report))
    return out

"""
Telegram bot (aiogram 3). Ishga tushirish: python manage.py runbot

Uch til: o'zbek / rus / ingliz. Do'konchi o'z tilini (Shop.lang), mijoz o'z tilini (Customer.lang) tanlaydi.
Buyruqlar: uz -> /bugun /qarzlar ..., ru/en -> /today /debts ... (ikkalasi ham hamma uchun ishlaydi).

Do'konchi uchun:
    xabar (matn / ovoz / rasm) -> AI JSON'ga ajratadi -> kerak bo'lsa so'raydi
    ("Qaysi Akmal?", "Shakar narxi?") -> tasdiqlash kartasi -> bazaga yoziladi
    + hisobotlar, menejer tavsiyalari, ertalabki brifing, javon tahlili, avto-eslatmalar

Mijoz uchun (ikki tomonlama daftar):
    raqami yoki havola orqali ulanadi -> har bir nasiya/to'lov unga keladi,
    u "✅" yoki "❌" bosadi -> xato bo'lsa do'konchiga ogohlantirish
"""
import asyncio
import io
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.utils.chat_action import ChatActionSender
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, MenuButtonWebApp, Message,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo)
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from . import dates, notify, reports, services, shelf
from .ai import get_ai
from .ai import stt
from .i18n import BOT_COMMANDS, CMD, CMD_REVERSE, LANG_NAMES, LANGS, detect, lang_of, money, tr, unit
from .models import Customer, KnownContact, PendingAction, Promise, Shop, Transaction
from .nlp import norm
from .services import escape, fmt

log = logging.getLogger(__name__)
router = Router()
BOT_USERNAME = "NasiyaAIBot"

# Foydalanuvchi holati (hackathon uchun xotirada yetarli):
#   {"mode": "clarify", "text": "..."}            -> AI savoliga javob kutilmoqda
#   {"mode": "price", "pending": id, "idx": n}    -> mahsulot narxi kutilmoqda
#   {"mode": "shopname"} / {"mode": "shelf_next"} / {"mode": "photo", ...}
STATE: dict[int, dict] = {}
# Hali rol tanlamagan foydalanuvchining tanlagan tili
PENDING_LANG: dict[int, str] = {}


def C(*uz_names: str) -> Command:
    """Buyruq va uning ru/en nomi: C("bugun") -> /bugun va /today."""
    names = []
    for n in uz_names:
        names += [n, CMD.get(n, n)]
    return Command(*dict.fromkeys(names))


def cmd_key(command: CommandObject) -> str:
    return CMD_REVERSE.get(command.command, command.command)


# ---------- klaviaturalar ----------

def kb_lang() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=LANG_NAMES[x], callback_data=f"lang:{x}") for x in LANGS]])


def kb_confirm(L: str, pa_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=tr(L, "b.confirm"), callback_data=f"ok:{pa_id}"),
        InlineKeyboardButton(text=tr(L, "b.cancel"), callback_data=f"no:{pa_id}"),
    ]])


def kb_customers(L: str, pa_id: int, customers) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=str(c), callback_data=f"cu:{pa_id}:{c.pk}")] for c in customers]
    rows.append([InlineKeyboardButton(text=tr(L, "b.new_customer"), callback_data=f"cu:{pa_id}:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_remind(customers: list[tuple[int, str]]) -> InlineKeyboardMarkup | None:
    if not customers:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔔 {label}", callback_data=f"rem:{pk}")] for pk, label in customers[:8]])


def with_app(kb: InlineKeyboardMarkup | None, text: str) -> InlineKeyboardMarkup | None:
    """Mavjud klaviaturaga Mini App tugmasini qo'shadi (WEBAPP_URL bo'lsa)."""
    if not settings.WEBAPP_URL:
        return kb
    rows = list(kb.inline_keyboard) if kb else []
    return InlineKeyboardMarkup(inline_keyboard=rows + [[
        InlineKeyboardButton(text=text, web_app=WebAppInfo(url=settings.WEBAPP_URL))]])


def kb_customer_check(L: str, tx_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=tr(L, "b.correct"), callback_data=f"cs:ok:{tx_id}"),
        InlineKeyboardButton(text=tr(L, "b.wrong"), callback_data=f"cs:no:{tx_id}"),
    ]])


def kb_role(L: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(L, "b.role_shop"), callback_data="role:shop")],
        [InlineKeyboardButton(text=tr(L, "b.role_cust"), callback_data="role:cust")],
        [InlineKeyboardButton(text="🌐 " + " · ".join(LANG_NAMES.values()), callback_data="lang:menu")],
    ])


def kb_contact(L: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=tr(L, "b.share_contact"), request_contact=True)]],
                               resize_keyboard=True, one_time_keyboard=True)


# ---------- sync yordamchilar (ORM) ----------

def _who(user_id: int):
    return services.resolve_user(user_id)


def _debtor_buttons(shop: Shop) -> list[tuple[int, str]]:
    return [(c.pk, str(c)) for c in services.debtors(shop, limit=8)]


def _brief(shop: Shop):
    text, custs = reports.morning_brief(shop)
    return text, [(c.pk, str(c)) for c in custs]


def _reminder_plan(shop: Shop, cid: int):
    c = shop.customers.get(pk=cid)
    return c, notify.draft_reminder(c), notify.reminder_channel(c)


def _statements(chat_id: int) -> str:
    custs = services.customers_of_chat(chat_id)
    return "\n\n— — —\n\n".join(services.customer_statement(c) for c in custs)


def _chat_lang(chat_id: int, fallback: str) -> str:
    c = Customer.objects.filter(telegram_chat_id=chat_id).exclude(lang="").first()
    if c:
        return c.lang
    kc = KnownContact.objects.filter(chat_id=chat_id).exclude(lang="").first()
    return kc.lang if kc else fallback


def _set_phone(shop: Shop, name: str, phone: str):
    """Telefonni saqlaydi; agar bu raqam egasi botga avval yozgan bo'lsa — darhol ulanadi."""
    c, cands = services.set_customer_field(shop, name, phone=phone)
    return c, cands, bool(c and c.telegram_chat_id)


def _auto_status(shop: Shop) -> str:
    L = lang_of(shop)
    targets = notify.auto_reminder_targets(shop)
    state = tr(L, "b.auto_on", h=shop.remind_hour) if shop.auto_remind else tr(L, "b.auto_off")
    lines = [tr(L, "b.auto_status", state=state, age=notify.AUTO_DEBT_AGE_DAYS, gap=notify.AUTO_MIN_GAP_DAYS)]
    if targets:
        lines.append("\n" + tr(L, "b.auto_queue", n=len(targets)))
        for c, reason in targets[:10]:
            ch = notify.reminder_channel(c, real_only=True)
            icon = {"telegram": "📱", "sms": "✉️"}.get(ch, tr(L, "b.not_connected"))
            lines.append(f"• {escape(str(c))} — {notify.reason_text(L, reason)} {icon}")
    else:
        lines.append("\n" + tr(L, "b.auto_nobody"))
    lines.append("\n" + tr(L, "b.auto_help"))
    return "\n".join(lines)


def _shelf_run(shop: Shop, payload: dict, file_id: str) -> str:
    audit = shelf.create_audit(shop, payload, file_id)
    return shelf.render(audit)


def _after_confirm(obj):
    """Tasdiqdan keyin: mijozga xabar (mijoz tilida) va do'konchiga maslahat (do'konchi tilida)."""
    L = lang_of(obj.shop)
    if isinstance(obj, Promise):
        return None, None, tr(L, "b.promise_saved", when=dates.human(obj.due_date, services.today(), L))
    tip = None
    if obj.customer and obj.kind in ("nasiya", "tolov"):
        c = obj.customer
        if c.telegram_chat_id:
            kb = kb_customer_check(lang_of(c), obj.pk) if obj.kind == "nasiya" else None
            return c.telegram_chat_id, (services.customer_notice(obj), kb), None
        if c.transactions.count() == 1:
            tip = tr(L, "b.tip_link", name=escape(str(c)), short=escape(c.name))
    return None, None, tip


def _due_briefs():
    now = timezone.localtime()
    out = []
    for shop in Shop.objects.filter(brief_hour=now.hour).exclude(last_brief_date=now.date()):
        shop.last_brief_date = now.date()
        shop.save(update_fields=["last_brief_date"])
        if shop.transactions.exists():
            out.append((shop.telegram_id, lang_of(shop), *_brief(shop)))
    return out


a_who = sync_to_async(_who)
a_names = sync_to_async(services.known_customer_names)
a_products = sync_to_async(lambda shop: list(shop.products.values_list("name", flat=True)))
a_create = sync_to_async(services.create_pending)
a_card = sync_to_async(services.render_card)
a_missing = sync_to_async(services.missing_price_index)
a_choice = sync_to_async(lambda pa: list(services.needs_customer_choice(pa)))
a_get_pa = sync_to_async(lambda pk, shop: PendingAction.objects.select_related("shop").get(pk=pk, shop=shop))
a_answer = sync_to_async(services.answer_question)
a_statement = sync_to_async(services.customer_statement)


def guest_lang(message_or_cb) -> str:
    """Hali rol tanlamagan foydalanuvchi tili: tanlagani yoki Telegram tili."""
    chat_id = message_or_cb.message.chat.id if isinstance(message_or_cb, CallbackQuery) else message_or_cb.chat.id
    return PENDING_LANG.get(chat_id) or detect(message_or_cb.from_user.language_code)


async def ai_call(message: Message, fn, *args):
    """AI chaqiruvi davomida chatda "yozmoqda..." ko'rsatib turadi (model 5-10 s o'ylashi mumkin)."""
    bot = getattr(message, "bot", None)
    if bot is None:
        return await asyncio.to_thread(fn, *args)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        return await asyncio.to_thread(fn, *args)



async def send_welcome(message: Message, L: str):
    known = await sync_to_async(KnownContact.objects.filter(chat_id=message.chat.id).exists)()
    await message.answer(tr(L, "b.known_contact") if known else tr(L, "b.welcome"), reply_markup=kb_role(L))


async def shop_or_statement(message: Message):
    """Do'konchi -> Shop. Mijoz -> hisobini ko'rsatib None. Yangi foydalanuvchi -> til/rol tanlash, None."""
    role, obj = await a_who(message.from_user.id)
    if role == "customer":
        L = lang_of(obj)
        await message.answer(await sync_to_async(_statements)(message.chat.id),
                             reply_markup=with_app(None, tr(L, "b.btn_my")))
        return None
    if role is None:
        if message.chat.id in PENDING_LANG:
            await send_welcome(message, PENDING_LANG[message.chat.id])
        else:
            await message.answer(tr("uz", "b.choose_lang"), reply_markup=kb_lang())
        return None
    return obj


# ---------- asosiy oqim ----------

async def next_step(message: Message, pa: PendingAction):
    """Yozuvni to'liq qilish uchun keyingi qadamni tanlaydi."""
    L = lang_of(pa.shop)
    uid = message.chat.id
    customers = await a_choice(pa)
    if customers:
        STATE.pop(uid, None)
        await message.answer(tr(L, "b.which", name=escape(pa.payload.get("customer") or "")),
                             reply_markup=kb_customers(L, pa.pk, customers))
        return
    idx = await a_missing(pa)
    if idx is not None:
        it = pa.payload["items"][idx]
        STATE[uid] = {"mode": "price", "pending": pa.pk, "idx": idx}
        key = "b.ask_cost" if pa.payload["action"] == "kirim" else "b.ask_price"
        await message.answer(tr(L, key, name=escape(it["name"]), unit=unit(L, it.get("unit") or "dona")))
        return
    STATE.pop(uid, None)
    await message.answer(await a_card(pa), reply_markup=kb_confirm(L, pa.pk))


async def handle_text(message: Message, shop: Shop, text: str, source_type: str = "text"):
    L = lang_of(shop)
    names = await a_names(shop)
    products = await a_products(shop)
    try:
        payload = await ai_call(message, get_ai().parse_text, text, names, services.today(), L, products)
    except Exception as e:  # noqa: BLE001
        log.exception("AI xatosi")
        await message.answer(tr(L, "b.ai_error", e=escape(str(e))[:300]))
        return

    action = payload.get("action")
    if action == "savol":
        await message.answer(await a_answer(shop, payload.get("question") or text))
        return
    if action == "noaniq" or payload.get("clarify"):
        STATE[message.chat.id] = {"mode": "clarify", "text": text}
        await message.answer("🤔 " + escape(payload.get("clarify") or tr(L, "b.dont_understand")))
        return
    if action in ("telefon", "limit"):
        if action == "telefon":
            c, cands, linked = await sync_to_async(_set_phone)(shop, payload.get("customer"), payload.get("phone"))
        else:
            c, cands = await sync_to_async(services.set_customer_field)(
                shop, payload.get("customer"), credit_limit=payload.get("amount"))
        if not c:
            hint = tr(L, "b.candidates", list=", ".join(escape(str(x)) for x in cands)) if cands \
                else tr(L, "b.no_customer")
            await message.answer(f"🤔 {hint}\n{tr(L, 'b.full_name')}")
            return
        if action == "limit":
            await message.answer(tr(L, "b.limit_set", name=escape(str(c)), amt=money(L, payload["amount"])))
            return
        if linked:
            await message.answer(tr(L, "b.phone_linked", name=escape(str(c)), phone=payload["phone"]))
            CL = lang_of(c)
            try:
                await message.bot.send_message(
                    c.telegram_chat_id, tr(CL, "b.added_by_shop", shop=escape(str(shop))) + "\n\n"
                    + await a_statement(c), reply_markup=with_app(None, tr(CL, "b.btn_my")))
            except Exception:  # noqa: BLE001
                log.exception("Mijozga xabar yuborilmadi")
        else:
            await message.answer(tr(L, "b.phone_saved", name=escape(str(c)), phone=payload["phone"],
                                    bot=BOT_USERNAME, url=services.link_url(c, BOT_USERNAME)))
        return

    pa = await a_create(shop, payload, source_type, text)
    await next_step(message, pa)


# ---------- buyruqlar ----------

@router.message(CommandStart(deep_link=True))
async def cmd_start_link(message: Message, command: CommandObject):
    arg = command.args or ""
    if arg.startswith("c_"):
        L = await sync_to_async(_chat_lang)(message.chat.id, guest_lang(message))
        c = await sync_to_async(services.link_customer_chat)(arg[2:], message.chat.id, L)
        if c:
            await message.answer(tr(L, "b.linked") + "\n\n" + await a_statement(c),
                                 reply_markup=with_app(None, tr(L, "b.btn_my")))
            await message.bot.send_message(c.shop.telegram_id,
                                           tr(lang_of(c.shop), "b.cust_linked_link", name=escape(str(c))))
            return
        await message.answer(tr(L, "b.link_bad"))
        return
    await cmd_start(message)


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message):
    shop = await shop_or_statement(message)
    if not shop:
        return
    L = lang_of(shop)
    await message.answer(tr(L, "b.help"))
    if not shop.name:
        STATE[message.chat.id] = {"mode": "shopname"}
        await message.answer(tr(L, "b.ask_name"))


@router.message(C("til"))
async def cmd_lang(message: Message):
    await message.answer(tr("uz", "b.choose_lang"), reply_markup=kb_lang())


@router.callback_query(F.data.startswith("lang:"))
async def on_lang(cb: CallbackQuery, bot: Bot):
    await cb.answer()
    code = cb.data.split(":")[1]
    if code == "menu":
        await cb.message.answer(tr("uz", "b.choose_lang"), reply_markup=kb_lang())
        return
    if code not in LANGS:
        return
    chat_id = cb.message.chat.id
    role, obj = await a_who(cb.from_user.id)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await cb.message.answer(tr(code, "b.lang_set"))
    if role == "shop":
        obj.lang = code
        await sync_to_async(obj.save)(update_fields=["lang"])
        await set_commands(bot, chat_id, code)
        await cb.message.answer(tr(code, "b.help"))
    elif role == "customer":
        await sync_to_async(services.set_chat_lang)(chat_id, code)
        await set_commands(bot, chat_id, code)
        await cb.message.answer(await sync_to_async(_statements)(chat_id),
                                reply_markup=with_app(None, tr(code, "b.btn_my")))
    else:
        PENDING_LANG[chat_id] = code
        await send_welcome(cb.message, code)


@router.message(C("nom"))
async def cmd_name(message: Message, command: CommandObject):
    shop = await shop_or_statement(message)
    if not shop:
        return
    L = lang_of(shop)
    if command.args:
        shop.name = command.args.strip()[:100]
        await sync_to_async(shop.save)(update_fields=["name"])
        await message.answer(tr(L, "b.name_set", name=escape(shop.name)))
    else:
        STATE[message.chat.id] = {"mode": "shopname"}
        await message.answer(tr(L, "b.ask_name_short"))


@router.message(C("demo"))
async def cmd_demo(message: Message, command: CommandObject):
    shop = await shop_or_statement(message)
    if not shop:
        return
    L = lang_of(shop)
    has_data = await sync_to_async(shop.transactions.exists)()
    if has_data and (command.args or "").strip().lower() not in ("yangi", "new", "новый"):
        await message.answer(tr(L, "b.demo_has_data"))
        return
    await message.answer(tr(L, "b.demo_loading"))
    from .demo import seed
    stats = await sync_to_async(seed)(shop)
    await message.answer(tr(L, "b.demo_done", tx=stats["transactions"], cu=stats["customers"], pr=stats["products"]))


@router.message(C("bugun", "kecha", "hafta", "oy"))
async def cmd_period(message: Message, command: CommandObject):
    shop = await shop_or_statement(message)
    if shop:
        L = lang_of(shop)
        await message.answer(await sync_to_async(reports.render_summary)(shop, cmd_key(command)),
                             reply_markup=with_app(None, tr(L, "b.btn_chart")))


@router.message(C("qarzlar"))
async def cmd_debts(message: Message):
    shop = await shop_or_statement(message)
    if shop:
        L = lang_of(shop)
        text = await sync_to_async(services.render_debtors)(shop)
        buttons = await sync_to_async(_debtor_buttons)(shop)
        await message.answer(text + ("\n\n" + tr(L, "db.tap") if buttons else ""),
                             reply_markup=with_app(kb_remind(buttons), tr(L, "b.btn_debtors_app")))


@router.message(C("ombor"))
async def cmd_stock(message: Message):
    shop = await shop_or_statement(message)
    if shop:
        await message.answer(await sync_to_async(reports.render_stock)(shop),
                             reply_markup=with_app(None, tr(lang_of(shop), "b.btn_more")))


@router.message(C("maslahat"))
async def cmd_insights(message: Message):
    shop = await shop_or_statement(message)
    if shop:
        await message.answer(await sync_to_async(reports.render_insights)(shop),
                             reply_markup=with_app(None, tr(lang_of(shop), "b.btn_more")))


@router.message(C("vadalar"))
async def cmd_promises(message: Message):
    shop = await shop_or_statement(message)
    if shop:
        await message.answer(await sync_to_async(services.render_promises)(shop))


@router.message(C("avto"))
async def cmd_auto(message: Message, command: CommandObject):
    shop = await shop_or_statement(message)
    if not shop:
        return
    L = lang_of(shop)
    arg = norm(command.args or "").strip()
    if arg in ("off", "o'chir", "ochir", "yo'q", "stop", "выкл"):
        shop.auto_remind = False
        await sync_to_async(shop.save)(update_fields=["auto_remind"])
    elif arg in ("on", "yoq", "ha", "start", "вкл"):
        shop.auto_remind = True
        await sync_to_async(shop.save)(update_fields=["auto_remind"])
    elif arg.isdigit() and 6 <= int(arg) <= 22:
        shop.remind_hour, shop.auto_remind = int(arg), True
        await sync_to_async(shop.save)(update_fields=["remind_hour", "auto_remind"])
    elif arg in ("hozir", "now", "test", "сейчас"):
        await message.answer(tr(L, "b.auto_sending"))
        report = await sync_to_async(notify.run_auto_reminders)(shop)
        await message.answer(report or tr(L, "b.auto_none"))
        return
    await message.answer(await sync_to_async(_auto_status)(shop))


@router.message(C("javon"))
async def cmd_shelf(message: Message):
    shop = await shop_or_statement(message)
    if shop:
        STATE[message.chat.id] = {"mode": "shelf_next"}
        await message.answer(tr(lang_of(shop), "b.shelf_howto"))


@router.message(C("brifing"))
async def cmd_brief(message: Message):
    shop = await shop_or_statement(message)
    if shop:
        text, custs = await sync_to_async(_brief)(shop)
        await message.answer(text, reply_markup=with_app(kb_remind(custs), tr(lang_of(shop), "b.btn_open_shop")))


@router.message(C("ulash"))
async def cmd_link(message: Message, command: CommandObject):
    shop = await shop_or_statement(message)
    if not shop:
        return
    L = lang_of(shop)
    if not command.args:
        await message.answer(tr(L, "b.link_who"))
        return
    c, cands = await sync_to_async(services.resolve_customer)(shop, command.args)
    if not c:
        hint = tr(L, "b.candidates", list=", ".join(escape(str(x)) for x in cands)) if cands \
            else tr(L, "b.link_not_found")
        await message.answer(f"🤔 {hint}")
        return
    await message.answer(tr(L, "b.link_msg", name=escape(str(c)), url=services.link_url(c, BOT_USERNAME)))


# ---------- xabarlar ----------

@router.message(F.voice | F.audio)
async def on_voice(message: Message, bot: Bot):
    shop = await shop_or_statement(message)
    if not shop:
        return
    L = lang_of(shop)
    media = message.voice or message.audio
    buf = io.BytesIO()
    await bot.download(media, destination=buf)
    try:
        text = await ai_call(message, stt.transcribe, buf.getvalue(), L)
    except stt.STTDisabled:
        await message.answer(tr(L, "b.voice_off"))
        return
    except Exception as e:  # noqa: BLE001
        await message.answer(tr(L, "b.voice_fail", e=escape(str(e))[:300]))
        return
    await message.answer(f"🎤 <i>{escape(text)}</i>")
    await handle_text(message, shop, text, source_type="voice")


SHELF_WORDS = ("javon", "polka", "vitrina", "tahlil", "magazin", "do'kon", "dokon", "sanab", "sana",
               "полк", "витрин", "анализ", "посчитай", "shelf", "count", "audit")
INVOICE_WORDS = ("nakladnoy", "yuk", "kirim", "keldi", "faktura", "chek", "xat",
                 "накладн", "приход", "invoice", "delivery", "receipt")


async def do_shelf(message: Message, bot: Bot, shop: Shop, file_id: str):
    L = lang_of(shop)
    await message.answer(tr(L, "b.shelf_working"))
    buf = io.BytesIO()
    await bot.download(file_id, destination=buf)
    try:
        names = await a_products(shop)
        payload = await ai_call(message, get_ai().analyze_shelf, buf.getvalue(), names, L)
    except Exception as e:  # noqa: BLE001
        log.exception("Javon tahlili xatosi")
        await message.answer(tr(L, "b.shelf_fail", e=escape(str(e))[:300]))
        return
    text = await sync_to_async(_shelf_run)(shop, payload, file_id)
    await message.answer(text, reply_markup=with_app(None, tr(L, "b.btn_open_stock")))


async def do_invoice(message: Message, bot: Bot, shop: Shop, file_id: str, caption: str = ""):
    L = lang_of(shop)
    await message.answer(tr(L, "b.invoice_working"))
    buf = io.BytesIO()
    await bot.download(file_id, destination=buf)
    try:
        names = await a_names(shop)
        payload = await ai_call(message, get_ai().parse_image, buf.getvalue(), names, services.today(), L)
    except Exception as e:  # noqa: BLE001
        await message.answer(tr(L, "b.photo_fail", e=escape(str(e))[:300]))
        return
    if payload.get("action") == "noaniq":
        await message.answer("🤔 " + escape(payload.get("clarify") or tr(L, "b.photo_unclear")))
        return
    pa = await a_create(shop, payload, "photo", caption or tr(L, "b.invoice_source"))
    await next_step(message, pa)


@router.message(F.photo)
async def on_photo(message: Message, bot: Bot):
    shop = await shop_or_statement(message)
    if not shop:
        return
    L = lang_of(shop)
    uid = message.chat.id
    file_id = message.photo[-1].file_id
    cap = norm(message.caption or "")
    state = STATE.get(uid) or {}
    if state.get("mode") == "shelf_next" or any(w in cap for w in SHELF_WORDS):
        STATE.pop(uid, None)
        await do_shelf(message, bot, shop, file_id)
        return
    if any(w in cap for w in INVOICE_WORDS):
        await do_invoice(message, bot, shop, file_id, message.caption or "")
        return
    STATE[uid] = {"mode": "photo", "file_id": file_id, "caption": message.caption or ""}
    await message.answer(tr(L, "b.photo_kind"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(L, "b.photo_shelf"), callback_data="ph:shelf")],
        [InlineKeyboardButton(text=tr(L, "b.photo_invoice"), callback_data="ph:inv")],
    ]))


@router.callback_query(F.data.startswith("ph:"))
async def on_photo_kind(cb: CallbackQuery, bot: Bot):
    role, shop = await a_who(cb.from_user.id)
    state = STATE.pop(cb.message.chat.id, None) or {}
    await cb.answer()
    if role != "shop" or state.get("mode") != "photo":
        await cb.message.answer(tr(lang_of(shop) if role == "shop" else guest_lang(cb), "b.photo_again"))
        return
    await cb.message.edit_reply_markup(reply_markup=None)
    if cb.data == "ph:shelf":
        await do_shelf(cb.message, bot, shop, state["file_id"])
    else:
        await do_invoice(cb.message, bot, shop, state["file_id"], state.get("caption", ""))


# ---------- yangi foydalanuvchi: rol tanlash va raqam ----------

@router.callback_query(F.data.startswith("role:"))
async def on_role(cb: CallbackQuery, bot: Bot):
    await cb.answer()
    role, existing = await a_who(cb.from_user.id)
    L = guest_lang(cb)
    if cb.data == "role:shop":
        if role == "shop":
            await cb.message.answer(tr(lang_of(existing), "b.help"))
            return
        shop = await sync_to_async(services.get_or_create_shop)(cb.from_user.id, "")
        shop.lang = L
        await sync_to_async(shop.save)(update_fields=["lang"])
        PENDING_LANG.pop(cb.message.chat.id, None)
        await set_commands(bot, cb.message.chat.id, L)
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer(tr(L, "b.help"))
        STATE[cb.message.chat.id] = {"mode": "shopname"}
        await cb.message.answer(tr(L, "b.ask_name"))
        return
    await cb.message.answer(tr(L, "b.ask_contact"), reply_markup=kb_contact(L))


@router.message(F.contact)
async def on_contact(message: Message, bot: Bot):
    L = guest_lang(message)
    ct = message.contact
    if not ct.user_id or ct.user_id != message.from_user.id:
        await message.answer(tr(L, "b.own_contact"), reply_markup=kb_contact(L))
        return
    found, new = await sync_to_async(services.remember_contact)(
        message.chat.id, ct.phone_number, message.from_user.full_name, L)
    PENDING_LANG.pop(message.chat.id, None)
    if not found:
        await message.answer(tr(L, "b.contact_saved"), reply_markup=ReplyKeyboardRemove())
        return
    await set_commands(bot, message.chat.id, L)
    await message.answer(tr(L, "b.found"), reply_markup=ReplyKeyboardRemove())
    await message.answer(await sync_to_async(_statements)(message.chat.id),
                         reply_markup=with_app(None, tr(L, "b.btn_my")))
    for c in new:
        try:
            await bot.send_message(c.shop.telegram_id, tr(lang_of(c.shop), "b.cust_linked_phone", name=escape(str(c))))
        except Exception:  # noqa: BLE001
            log.exception("Do'konchiga xabar yuborilmadi")


@router.message(F.text)
async def on_text(message: Message):
    shop = await shop_or_statement(message)
    if not shop:
        return
    L = lang_of(shop)
    uid = message.chat.id
    state = STATE.get(uid)

    if state and state["mode"] == "price":
        price = services.parse_amount(message.text)
        if not price:
            await message.answer(tr(L, "b.price_number"))
            return
        pa = await a_get_pa(state["pending"], shop)
        await sync_to_async(services.set_item_price)(pa, state["idx"], price)
        await next_step(message, pa)
        return

    if state and state["mode"] == "shopname":
        STATE.pop(uid, None)
        shop.name = message.text.strip()[:100]
        await sync_to_async(shop.save)(update_fields=["name"])
        await message.answer(tr(L, "b.name_ready", name=escape(shop.name)))
        return

    if state and state["mode"] == "clarify":
        STATE.pop(uid, None)
        await handle_text(message, shop, f"{state['text']}. {message.text}")
        return

    await handle_text(message, shop, message.text)


# ---------- tugmalar ----------

@router.callback_query(F.data.startswith("cs:"))
async def on_customer_check(cb: CallbackQuery, bot: Bot):
    """Mijoz nasiyani tasdiqlaydi yoki rad etadi."""
    _, verdict, tx_id = cb.data.split(":")
    status = Transaction.CustomerStatus.CONFIRMED if verdict == "ok" else Transaction.CustomerStatus.DISPUTED
    tx = await sync_to_async(services.set_customer_status)(int(tx_id), cb.from_user.id, status)
    if not tx:
        await cb.answer(tr(guest_lang(cb), "b.not_found"), show_alert=True)
        return
    CL, SL = lang_of(tx.customer), lang_of(tx.shop)
    await cb.message.edit_reply_markup(reply_markup=None)
    if verdict == "ok":
        await cb.answer(tr(CL, "b.cust_ok_toast"))
        await cb.message.answer(tr(CL, "b.cust_ok"))
    else:
        await cb.answer(tr(CL, "b.cust_no_toast"))
        await cb.message.answer(tr(CL, "b.cust_no"))
        when = timezone.localtime(tx.created_at).strftime("%d.%m %H:%M")
        await bot.send_message(tx.shop.telegram_id, tr(SL, "b.disputed", name=escape(str(tx.customer)), when=when,
                                                       amt=money(SL, tx.amount), src=escape(tx.source_text[:200])))


@router.callback_query(F.data.startswith(("rem:", "rs:", "x")))
async def on_reminder(cb: CallbackQuery, bot: Bot):
    role, shop = await a_who(cb.from_user.id)
    if role != "shop":
        await cb.answer(tr(guest_lang(cb), "b.start_first"))
        return
    L = lang_of(shop)
    if cb.data == "x":
        await cb.message.delete()
        await cb.answer()
        return
    kind, cid = cb.data.split(":")
    c, text, channel = await sync_to_async(_reminder_plan)(shop, int(cid))

    if kind == "rem":
        via = {"telegram": tr(L, "b.via_tg"), "sms": tr(L, "b.via_sms", phone=c.phone)}.get(channel, tr(L, "b.via_none"))
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=tr(L, "b.send"), callback_data=f"rs:{c.pk}"),
            InlineKeyboardButton(text=tr(L, "b.close"), callback_data="x")]]) if channel else None
        extra = "" if channel else "\n\n" + tr(L, "b.rem_no_channel", url=services.link_url(c, BOT_USERNAME),
                                                name=escape(c.name))
        await cb.message.answer(f"{tr(L, 'b.rem_title', name=escape(str(c)))}\n{via}\n\n"
                                f"<blockquote>{escape(text)}</blockquote>{extra}", reply_markup=kb)
        await cb.answer()
        return

    # rs: yuborish (matn mijoz tilida, tugma ham)
    ok, err = False, ""
    if channel == "telegram":
        try:
            await bot.send_message(c.telegram_chat_id, escape(text),
                                   reply_markup=with_app(None, tr(lang_of(c), "btn.account")))
            ok = True
        except Exception as e:  # noqa: BLE001
            err = str(e)
    elif channel == "sms":
        ok, err = await asyncio.to_thread(notify.send_sms, c.phone, text)
    await sync_to_async(notify.log_message)(c, channel or "-", text, ok, "" if ok else err)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer(tr(L, "b.sent_toast") if ok else tr(L, "b.not_sent_toast"))
    await cb.message.answer(tr(L, "b.rem_sent", name=escape(str(c))) if ok
                            else tr(L, "b.rem_failed", e=escape(err)[:200]))


@router.callback_query(F.data.startswith(("ok:", "no:", "cu:")))
async def on_callback(cb: CallbackQuery, bot: Bot):
    role, shop = await a_who(cb.from_user.id)
    if role != "shop":
        await cb.answer(tr(guest_lang(cb), "b.start_first"))
        return
    L = lang_of(shop)
    parts = cb.data.split(":")
    try:
        pa = await a_get_pa(int(parts[1]), shop)
    except PendingAction.DoesNotExist:
        await cb.answer(tr(L, "b.not_found"), show_alert=True)
        return
    if pa.status != PendingAction.Status.PENDING:
        await cb.answer(tr(L, "b.already"))
        return

    if parts[0] == "cu":
        await sync_to_async(services.choose_customer)(pa, int(parts[2]) or None)
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer()
        await next_step(cb.message, pa)
        return

    if parts[0] == "no":
        await sync_to_async(services.cancel)(pa)
        await cb.message.edit_text(await a_card(pa) + "\n\n" + tr(L, "card.cancelled"))
        await cb.answer(tr(L, "b.cancelled_toast"))
        return

    card = await a_card(pa)  # saqlashdan oldin: "eski qarz → yangi qarz" to'g'ri chiqishi uchun
    obj = await sync_to_async(services.confirm)(pa)
    await cb.message.edit_text(card + "\n\n" + tr(L, "card.saved"))
    await cb.answer(tr(L, "b.saved_toast"))
    chat_id, notice, tip = await sync_to_async(_after_confirm)(obj)
    if chat_id:
        try:
            await bot.send_message(chat_id, notice[0], reply_markup=notice[1])
            await cb.message.answer(tr(L, "b.notice_sent"))
        except Exception:  # noqa: BLE001
            log.exception("Mijozga xabar yuborilmadi")
    if tip:
        await cb.message.answer(tip)


# ---------- buyruqlar menyusi, brifing sikli, ishga tushirish ----------

def bot_commands(lang: str) -> list[BotCommand]:
    return [BotCommand(command=c, description=d) for c, d in BOT_COMMANDS[lang]]


async def set_commands(bot: Bot, chat_id: int, lang: str):
    """Shu foydalanuvchi uchun buyruqlar menyusini uning tilida o'rnatadi."""
    from aiogram.types import BotCommandScopeChat
    try:
        await bot.set_my_commands(bot_commands(lang), scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception:  # noqa: BLE001
        log.exception("Buyruqlar menyusi o'rnatilmadi")


async def brief_loop(bot: Bot):
    """Har daqiqada: ertalabki brifing va avtomatik eslatmalar vaqti kelganmi?"""
    while True:
        try:
            for tg_id, L, text, custs in await sync_to_async(_due_briefs)():
                await bot.send_message(tg_id, text, reply_markup=with_app(kb_remind(custs), tr(L, "b.btn_open_shop")))
        except Exception:  # noqa: BLE001
            log.exception("Brifing xatosi")
        try:
            for tg_id, report in await sync_to_async(notify.due_auto_reminders)():
                await bot.send_message(tg_id, report)
        except Exception:  # noqa: BLE001
            log.exception("Avto-eslatma xatosi")
        await asyncio.sleep(60)


async def run():
    global BOT_USERNAME
    if not settings.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN .env faylida yo'q")
    bot = Bot(settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    me = await bot.get_me()
    BOT_USERNAME = me.username
    await bot.set_my_commands(bot_commands("uz"))
    await bot.set_my_commands(bot_commands("ru"), language_code="ru")
    await bot.set_my_commands(bot_commands("en"), language_code="en")
    if settings.WEBAPP_URL:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
            text=tr("uz", "b.menu"), web_app=WebAppInfo(url=settings.WEBAPP_URL)))
    print(f"Bot ishga tushdi: @{me.username}  (AI_BACKEND={settings.AI_BACKEND}, STT={settings.STT_BACKEND or "off"}, SMS={settings.SMS_BACKEND})")
    stt.preload()
    asyncio.create_task(brief_loop(bot))
    await dp.start_polling(bot)

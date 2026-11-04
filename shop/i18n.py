"""
Uch til: o'zbek (uz), rus (ru), ingliz (en).

    tr(lang, "card.total", amt=money(lang, 15000))

Har bir do'konchi (Shop.lang) va har bir mijoz (Customer.lang) o'z tilini tanlaydi.
Mijozga boradigan xabarlar — mijozning tilida, do'konchiga — do'konchining tilida.
Buyruqlar ham tilga qarab: uz -> /bugun, ru/en -> /today (ikkalasi ham hamma uchun ishlaydi).
"""
LANGS = ("uz", "ru", "en")
LANG_NAMES = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}
_IDX = {"uz": 0, "ru": 1, "en": 2}

# uz buyruq -> ru/en buyruq
CMD = {"bugun": "today", "kecha": "yesterday", "hafta": "week", "oy": "month", "qarzlar": "debts",
       "maslahat": "tips", "ombor": "stock", "vadalar": "promises", "brifing": "brief", "ulash": "link",
       "avto": "auto", "javon": "shelf", "demo": "demo", "nom": "name", "til": "lang", "help": "help"}
CMD_REVERSE = {v: k for k, v in CMD.items()}


def norm_lang(lang: str | None) -> str:
    return lang if lang in LANGS else "uz"


def detect(language_code: str | None) -> str:
    """Telegram language_code -> uz/ru/en."""
    code = (language_code or "").lower()
    if code.startswith("uz"):
        return "uz"
    if code.startswith(("ru", "uk", "be", "kk", "ky", "tg")):
        return "ru"
    if code.startswith("en"):
        return "en"
    return "uz"


def cmd(lang: str, key: str) -> str:
    return "/" + (key if norm_lang(lang) == "uz" else CMD.get(key, key))


class _Cmds(dict):
    def __init__(self, lang):
        super().__init__({k: cmd(lang, k) for k in CMD})


def tr(lang: str | None, key: str, **kw) -> str:
    row = T.get(key)
    if row is None:
        return key
    text = row[_IDX[norm_lang(lang)]]
    if "{c[" in text:
        kw.setdefault("c", _Cmds(lang))
    return text.format(**kw) if kw else text


def som(lang) -> str:
    return tr(lang, "som")


def money(lang, n) -> str:
    from .services import fmt
    return f"{fmt(n)} {som(lang)}"


UNITS = {
    "dona": ("dona", "шт", "pcs"), "kg": ("kg", "кг", "kg"), "litr": ("litr", "л", "L"),
    "qop": ("qop", "меш.", "bags"), "pachka": ("pachka", "пач.", "packs"), "quti": ("quti", "кор.", "boxes"),
    "blok": ("blok", "блок", "blocks"), "shisha": ("shisha", "бут.", "btl"), "g": ("g", "г", "g"),
}


def unit(lang, u: str | None) -> str:
    if not u:
        return ""
    row = UNITS.get(u)
    return row[_IDX[norm_lang(lang)]] if row else u


def lang_of(obj) -> str:
    """Shop yoki Customer uchun til."""
    lang = getattr(obj, "lang", "") or ""
    if not lang and hasattr(obj, "shop"):
        lang = obj.shop.lang
    return norm_lang(lang)


# fmt: off
T = {
    # ---------- umumiy ----------
    "som": ("so'm", "сум", "UZS"),
    "customers_n": ("{n} mijoz", "{n} клиентов", "{n} customers"),
    "whole_debt": ("butun qarz", "весь долг", "full balance"),

    # ---------- sanalar ----------
    "date.today": ("bugun ({d})", "сегодня ({d})", "today ({d})"),
    "date.tomorrow": ("ertaga ({d})", "завтра ({d})", "tomorrow ({d})"),
    "date.ago": ("{d} — {n} kun o'tdi", "{d} — {n} дн. назад", "{d} — {n} days ago"),

    # ---------- yozuv kartasi ----------
    "kind.nasiya": ("📝 Nasiya", "📝 В долг", "📝 On credit"),
    "kind.tolov": ("💵 To'lov", "💵 Оплата долга", "💵 Payment"),
    "kind.sotuv": ("💰 Naqd savdo", "💰 Продажа за наличные", "💰 Cash sale"),
    "kind.kirim": ("📦 Kirim", "📦 Приход товара", "📦 Stock in"),
    "kind.vada": ("🤝 Va'da", "🤝 Обещание оплаты", "🤝 Payment promise"),
    "card.new_customer": ("🆕 yangi mijoz", "🆕 новый клиент", "🆕 new customer"),
    "card.last_price": ("(oxirgi narx)", "(последняя цена)", "(last price)"),
    "card.due": ("📅 Muddat: <b>{when}</b>", "📅 Срок: <b>{when}</b>", "📅 Due: <b>{when}</b>"),
    "card.amount": ("Summa: <b>{amt}</b>", "Сумма: <b>{amt}</b>", "Amount: <b>{amt}</b>"),
    "card.whole": ("butun qarz ({bal})", "весь долг ({bal})", "full balance ({bal})"),
    "card.total": ("<b>Jami: {amt}</b>", "<b>Итого: {amt}</b>", "<b>Total: {amt}</b>"),
    "card.debt": ("Qarz: {old} → <b>{new}</b>", "Долг: {old} → <b>{new}</b>", "Balance: {old} → <b>{new}</b>"),
    "card.limit": ("⚠️ <b>Limit ({limit}) oshadi!</b>", "⚠️ <b>Превышен лимит ({limit})!</b>",
                   "⚠️ <b>Credit limit ({limit}) exceeded!</b>"),
    "card.overpay": ("⚠️ To'lov qarzdan ko'p — ortiqcha summa avans bo'lib qoladi.",
                     "⚠️ Оплата больше долга — излишек останется авансом.",
                     "⚠️ Payment exceeds the debt — the extra stays as an advance."),
    "card.cash_in": ("💵 Kassaga tushadi", "💵 Поступит в кассу", "💵 Goes to the cash box"),
    "card.saved": ("✅ <b>Saqlandi</b>", "✅ <b>Сохранено</b>", "✅ <b>Saved</b>"),
    "card.cancelled": ("❌ <i>Bekor qilindi</i>", "❌ <i>Отменено</i>", "❌ <i>Cancelled</i>"),

    # ---------- mijoz hisobi va xabarlari ----------
    "st.balance": ("Qarzingiz: <b>{amt}</b>", "Ваш долг: <b>{amt}</b>", "Your balance: <b>{amt}</b>"),
    "st.credit": ("nasiya", "в долг", "credit"),
    "st.payment": ("to'lov", "оплата", "payment"),
    "st.promise": ("🤝 Va'da: {when}", "🤝 Обещание: {when}", "🤝 Promise: {when}"),
    "nt.credit": ("🏪 <b>{shop}</b>\nSiz nasiyaga oldingiz: {what}\nSumma: <b>{amt}</b>\n"
                  "Umumiy qarzingiz: <b>{bal}</b>\n\nHammasi to'g'rimi?",
                  "🏪 <b>{shop}</b>\nВы взяли в долг: {what}\nСумма: <b>{amt}</b>\n"
                  "Общий долг: <b>{bal}</b>\n\nВсё верно?",
                  "🏪 <b>{shop}</b>\nYou bought on credit: {what}\nAmount: <b>{amt}</b>\n"
                  "Total balance: <b>{bal}</b>\n\nIs this correct?"),
    "nt.paid": ("🏪 <b>{shop}</b>\nTo'lovingiz qabul qilindi: <b>{amt}</b> 🙏\nQolgan qarz: <b>{bal}</b>",
                "🏪 <b>{shop}</b>\nОплата получена: <b>{amt}</b> 🙏\nОстаток долга: <b>{bal}</b>",
                "🏪 <b>{shop}</b>\nPayment received: <b>{amt}</b> 🙏\nRemaining balance: <b>{bal}</b>"),
    "btn.account": ("📱 Hisobimni ko'rish", "📱 Мой счёт", "📱 My account"),

    # ---------- qarzdorlar, va'dalar ----------
    "db.none": ("Hozircha hech kim qarzdor emas 🎉", "Пока должников нет 🎉", "No one owes anything right now 🎉"),
    "db.title": ("<b>Qarzdorlar:</b>", "<b>Должники:</b>", "<b>Debtors:</b>"),
    "db.total": ("<b>Jami nasiyada: {amt}</b>", "<b>Всего в долг: {amt}</b>", "<b>Total on credit: {amt}</b>"),
    "db.flag_limit": ("⚠️limit", "⚠️лимит", "⚠️limit"),
    "db.flag_disputed": ("❗rad etilgan yozuv", "❗оспорено", "❗disputed"),
    "db.tap": ("🔔 Eslatma yuborish uchun bosing:", "🔔 Нажмите, чтобы отправить напоминание:",
               "🔔 Tap to send a reminder:"),
    "pr.none": ("Ochiq va'dalar yo'q.", "Открытых обещаний нет.", "No open promises."),
    "pr.title": ("<b>To'lov va'dalari:</b>", "<b>Обещания оплаты:</b>", "<b>Payment promises:</b>"),

    # ---------- hisobotlar ----------
    "period.bugun": ("Bugun", "Сегодня", "Today"),
    "period.kecha": ("Kecha", "Вчера", "Yesterday"),
    "period.hafta": ("So'nggi 7 kun", "Последние 7 дней", "Last 7 days"),
    "period.oy": ("So'nggi 30 kun", "Последние 30 дней", "Last 30 days"),
    "rs.sales": ("Savdo: <b>{amt}</b>{delta}", "Продажи: <b>{amt}</b>{delta}", "Sales: <b>{amt}</b>{delta}"),
    "rs.cash": ("   • naqd: {amt}", "   • наличными: {amt}", "   • cash: {amt}"),
    "rs.credit": ("   • nasiyaga: {amt}", "   • в долг: {amt}", "   • on credit: {amt}"),
    "rs.cash_in": ("💵 Kassaga tushdi: <b>{amt}</b> (shundan qarz to'lovlari {paid})",
                   "💵 Поступило в кассу: <b>{amt}</b> (из них возврат долгов {paid})",
                   "💵 Cash collected: <b>{amt}</b> (incl. debt repayments {paid})"),
    "rs.profit": ("📈 Foyda (taxminan): <b>{amt}</b>{note}", "📈 Прибыль (примерно): <b>{amt}</b>{note}",
                  "📈 Profit (approx.): <b>{amt}</b>{note}"),
    "rs.profit_note": (" <i>(tannarxi ma'lum tovarlar bo'yicha)</i>", " <i>(по товарам с известной себестоимостью)</i>",
                       " <i>(items with known cost)</i>"),
    "rs.purchases": ("📦 Tovar xaridi: {amt}", "📦 Закупка товара: {amt}", "📦 Purchases: {amt}"),
    "rs.top": ("🏆 Eng ko'p: {list}", "🏆 Топ продаж: {list}", "🏆 Top sellers: {list}"),
    "rs.credit_warn": ("⚠️ Savdoning {pct}% nasiyaga ketdi — naqd pul kam aylanmoqda.",
                       "⚠️ {pct}% продаж ушло в долг — мало живых денег.",
                       "⚠️ {pct}% of sales went on credit — cash flow is tight."),
    "rs.outstanding": ("📝 Jami nasiyada: <b>{amt}</b> ({n} mijoz)", "📝 Всего в долг: <b>{amt}</b> ({n} клиентов)",
                       "📝 Total on credit: <b>{amt}</b> ({n} customers)"),
    "rs.empty": ("<i>Bu davrda yozuvlar yo'q.</i>", "<i>За этот период записей нет.</i>",
                 "<i>No records for this period.</i>"),

    "sk.empty": ("Omborda hali tovar yozilmagan. Masalan: <i>10 qop un keldi, har biri 280 ming</i>",
                 "На складе пока нет товаров. Например: <i>пришло 10 мешков муки по 280 тысяч</i>",
                 "No stock recorded yet. For example: <i>10 bags of flour arrived, 280,000 each</i>"),
    "sk.title": ("📦 <b>Ombor</b>", "📦 <b>Склад</b>", "📦 <b>Stock</b>"),
    "sk.daily": (" — har kuni keladi", " — привозят каждый день", " — delivered daily"),
    "sk.days": (" — ~{d} kunga yetadi", " — хватит на ~{d} дн.", " — ~{d} days left"),
    "sk.negative": ("❗ Qoldiq manfiy (kirim yozilmagan bo'lishi mumkin): {list}",
                    "❗ Отрицательный остаток (возможно, не записан приход): {list}",
                    "❗ Negative stock (a delivery may be unrecorded): {list}"),

    "in.low": ("🛒 <b>{name}</b> ~{d} kunda tugaydi (kuniga ~{avg} {unit} sotilyapti). "
               "Bir haftaga {order} {unit} buyurtma qiling.{cost}",
               "🛒 <b>{name}</b> закончится через ~{d} дн. (продаётся ~{avg} {unit} в день). "
               "Закажите {order} {unit} на неделю.{cost}",
               "🛒 <b>{name}</b> runs out in ~{d} days (~{avg} {unit} sold per day). "
               "Order {order} {unit} for a week.{cost}"),
    "in.cost": (" Oxirgi xarid narxi: {p}.", " Последняя закупочная цена: {p}.", " Last purchase price: {p}."),
    "in.broken": ("🔴 <b>{name}</b> {date} kuni {amt} to'lashga va'da bergan edi — {late} kun o'tdi, hali to'lamadi. "
                  "Eslatma yuboring.",
                  "🔴 <b>{name}</b> обещал(а) оплатить {amt} ({date}) — прошло {late} дн., оплаты нет. "
                  "Отправьте напоминание.",
                  "🔴 <b>{name}</b> promised to pay {amt} on {date} — {late} days ago, still unpaid. Send a reminder."),
    "in.debt_word": ("qarzini", "долг", "the balance"),
    "in.overdue": ("⏰ <b>{name}</b> {d} kundan beri to'lamadi ({amt}). Yangi nasiya berishdan oldin limit qo'ying.",
                   "⏰ <b>{name}</b> не платит {d} дн. ({amt}). Установите лимит, прежде чем давать в долг снова.",
                   "⏰ <b>{name}</b> hasn't paid for {d} days ({amt}). Set a credit limit before giving more."),
    "in.slow": ("🧊 <b>{name}</b>: {qty} {unit} turibdi, {w} kundan beri sotilmadi{money}. "
                "Chegirma qiling yoki ko'zga ko'rinadigan joyga qo'ying.",
                "🧊 <b>{name}</b>: {qty} {unit} лежит без продаж {w} дн.{money}. "
                "Сделайте скидку или переставьте на видное место.",
                "🧊 <b>{name}</b>: {qty} {unit} unsold for {w} days{money}. Discount it or move it to a visible spot."),
    "in.frozen": (" — {amt} muzlab yotibdi", " — заморожено {amt}", " — {amt} tied up"),
    "in.loss": ("❌ <b>{name}</b> zararga sotilyapti: tannarx {cost}, sotuv {sell}. Narxni ko'taring.",
                "❌ <b>{name}</b> продаётся в убыток: себестоимость {cost}, цена {sell}. Поднимите цену.",
                "❌ <b>{name}</b> is sold at a loss: cost {cost}, price {sell}. Raise the price."),
    "in.best": ("💎 Eng ko'p foyda keltirayotganlar (30 kun): {list}. Ularni hech qachon tugatib qo'ymang.",
                "💎 Самые прибыльные (30 дней): {list}. Не допускайте, чтобы они заканчивались.",
                "💎 Most profitable (30 days): {list}. Never let them run out."),
    "in.credit": ("💸 Haftalik savdoning {pct}% nasiya. Tovar olishga naqd pul yetmay qolishi mumkin — "
                  "eslatmalarni faolroq yuboring.",
                  "💸 {pct}% продаж за неделю — в долг. Может не хватить денег на закупку — "
                  "отправляйте напоминания активнее.",
                  "💸 {pct}% of this week's sales are on credit. You may run short of cash for restocking — "
                  "send reminders more actively."),
    "in.none": ("🧠 Hozircha hammasi joyida 👍\n<i>Savdo va kirimlar ko'paygan sari tavsiyalar aniqroq bo'ladi.</i>",
                "🧠 Пока всё в порядке 👍\n<i>Чем больше записей, тем точнее советы.</i>",
                "🧠 All good for now 👍\n<i>Tips get sharper as more sales and deliveries are recorded.</i>"),
    "in.title": ("🧠 <b>Do'kon menejeri tavsiyalari</b>", "🧠 <b>Советы менеджера магазина</b>",
                 "🧠 <b>Shop manager tips</b>"),

    "br.hello": ("☀️ <b>Xayrli tong!</b> {date}", "☀️ <b>Доброе утро!</b> {date}", "☀️ <b>Good morning!</b> {date}"),
    "br.yesterday": ("Kecha: savdo <b>{rev}</b>{delta}{profit}, kassaga {cash}",
                     "Вчера: продажи <b>{rev}</b>{delta}{profit}, в кассу {cash}",
                     "Yesterday: sales <b>{rev}</b>{delta}{profit}, cash in {cash}"),
    "br.profit": (", foyda ~{p}", ", прибыль ~{p}", ", profit ~{p}"),
    "br.no_records": ("Kecha yozuvlar bo'lmadi.", "Вчера записей не было.", "No records yesterday."),
    "br.due_today": ("🤝 Bugun to'lashi kerak: {list}", "🤝 Сегодня должны заплатить: {list}", "🤝 Due to pay today: {list}"),
    "br.late": ("🔴 Va'dasini bajarmagan: {list}", "🔴 Не выполнили обещание: {list}", "🔴 Broke their promise: {list}"),
    "br.low": ("🛒 Tugayapti: {list}", "🛒 Заканчивается: {list}", "🛒 Running low: {list}"),
    "br.days": ("~{d} kun", "~{d} дн.", "~{d} d"),
    "br.outstanding": ("📝 Nasiyada: <b>{amt}</b> ({n} mijoz)", "📝 В долг: <b>{amt}</b> ({n} клиентов)",
                       "📝 On credit: <b>{amt}</b> ({n} customers)"),
    "br.auto": ("🤖 Soat {h}:00 da {n} mijozga avtomatik eslatma boradi ({c[avto]})",
                "🤖 В {h}:00 {n} клиентам уйдут автонапоминания ({c[avto]})",
                "🤖 At {h}:00, {n} customers get automatic reminders ({c[avto]})"),
    "br.shelf": ("📸 Javonni suratga olib yuboring — ertalabki sanoq (kechqurun solishtiramiz)",
                 "📸 Сфотографируйте полку — утренний пересчёт (вечером сравним)",
                 "📸 Send a shelf photo — morning count (we'll compare tonight)"),
    "br.more": ("Batafsil: {c[maslahat]} · {c[bugun]} · {c[qarzlar]}", "Подробнее: {c[maslahat]} · {c[bugun]} · {c[qarzlar]}",
                "More: {c[maslahat]} · {c[bugun]} · {c[qarzlar]}"),

    # ---------- eslatmalar ----------
    "rm.hello": ("Assalomu alaykum, {name}!", "Здравствуйте, {name}!", "Hello, {name}!"),
    "rm.shop_named": ("{name} do'koni", "Магазин «{name}»", "{name} shop"),
    "rm.shop": ("Do'kon", "Магазин", "The shop"),
    "rm.today": ("bugun", "сегодня", "today"),
    "rm.on_date": ("{d} kuni", "{d}", "on {d}"),
    "rm.promise": ("{shop}dan eslatma: {when} {amt} to'lashni va'da qilgan edingiz.",
                   "Напоминание: {shop}. Вы обещали оплатить {amt} {when}.",
                   "A reminder from {shop}: you promised to pay {amt} {when}."),
    "rm.promise_whole": ("qarzni", "долг", "your balance"),
    "rm.total": ("Umumiy qarzingiz: {bal}.", "Общий долг: {bal}.", "Your total balance: {bal}."),
    "rm.debt": ("{shop}dagi qarzingiz {bal}.", "{shop}: ваш долг составляет {bal}.", "Your balance at {shop} is {bal}."),
    "rm.please": ("Imkoningiz bo'lganda to'lab qo'ysangiz, xursand bo'lardik. Rahmat! 🙏",
                  "Будем благодарны, если оплатите, когда будет возможность. Спасибо! 🙏",
                  "We'd appreciate it if you could pay when you have a chance. Thank you! 🙏"),
    "rs_today": ("bugun va'da kuni", "сегодня день оплаты", "promised to pay today"),
    "rs_late": ("va'dadan {n} kun o'tdi", "обещание просрочено на {n} дн.", "promise {n} days overdue"),
    "rs_old": ("{n} kundan beri to'lamagan", "не платит {n} дн.", "unpaid for {n} days"),
    "au.title": ("🤖 <b>Avtomatik eslatmalar</b>", "🤖 <b>Автонапоминания</b>", "🤖 <b>Automatic reminders</b>"),
    "au.sent": ("✅ Yuborildi:", "✅ Отправлено:", "✅ Sent:"),
    "au.failed": ("⚠️ Yuborilmadi: {list}", "⚠️ Не отправлено: {list}", "⚠️ Failed: {list}"),
    "au.no_channel": ("📵 Telegramga ulanmagan (eslatma bormadi):", "📵 Не подключены к Telegram (не отправлено):",
                      "📵 Not connected to Telegram (not sent):"),
    "au.hint": ("<i>Ularga ayting: botni ochib \"📱 Raqamimni yuborish\" tugmasini bossin — keyingi safar avtomatik "
                "boradi. Yoki: {c[ulash]} ism</i>",
                "<i>Попросите их открыть бота и нажать «📱 Отправить мой номер» — в следующий раз всё уйдёт "
                "автоматически. Или: {c[ulash]} имя</i>",
                "<i>Ask them to open the bot and tap \"📱 Share my number\" — next time it goes out automatically. "
                "Or: {c[ulash]} name</i>"),
    "au.off": ("O'chirish: {c[avto]} off", "Отключить: {c[avto]} off", "Turn off: {c[avto]} off"),

    # ---------- javon tahlili ----------
    "sh.title": ("📸 <b>Javon tahlili</b> · {when}", "📸 <b>Анализ полки</b> · {when}", "📸 <b>Shelf audit</b> · {when}"),
    "sh.counted": ("Sanaldi: {k} xil tovar, ~{n} dona", "Посчитано: {k} видов товара, ~{n} шт.",
                   "Counted: {k} products, ~{n} items"),
    "sh.empty": (", bo'sh joy: {n}", ", пустых мест: {n}", ", empty spots: {n}"),
    "sh.unrec_title": ("🚨 <b>Yozilmagan sotuv</b> (ertalab {t} dagi suratga nisbatan):",
                       "🚨 <b>Незаписанные продажи</b> (по сравнению с фото в {t}):",
                       "🚨 <b>Unrecorded sales</b> (vs. the {t} photo):"),
    "sh.unrec_row": ("• {name}: suratda −{photo}, yozilgan {rec} → <b>{gap} {unit} yozilmagan</b>{money}",
                     "• {name}: на фото −{photo}, записано {rec} → <b>{gap} {unit} не записано</b>{money}",
                     "• {name}: photo −{photo}, recorded {rec} → <b>{gap} {unit} unrecorded</b>{money}"),
    "sh.unrec_total": ("Jami ~<b>{amt}</b> kassaga tushmagan bo'lishi mumkin.",
                       "Итого ~<b>{amt}</b> могло не попасть в кассу.",
                       "Up to ~<b>{amt}</b> may be missing from the cash box."),
    "sh.match": ("✅ Ertalabki surat bilan farq yozilgan savdoga mos keladi.",
                 "✅ Разница с утренним фото совпадает с записанными продажами.",
                 "✅ The change since the morning photo matches recorded sales."),
    "sh.low_title": ("🛒 <b>Javonda kam qoldi:</b>", "🛒 <b>Мало на полке:</b>", "🛒 <b>Low on the shelf:</b>"),
    "sh.reorder": (" — <b>omborda ham yo'q, buyurtma bering</b>", " — <b>на складе тоже нет, закажите</b>",
                   " — <b>none in storage either, reorder</b>"),
    "sh.restock": (" — omborda {qty} {unit}, javonga chiqaring", " — на складе {qty} {unit}, выставьте на полку",
                   " — {qty} {unit} in storage, restock the shelf"),
    "sh.missing": ("👀 Oldingi suratda bor edi, endi ko'rinmayapti: {list}",
                   "👀 Было на прошлом фото, сейчас не видно: {list}",
                   "👀 On the earlier photo, not visible now: {list}"),
    "sh.stock_gap": ("❗ Bazadagi qoldiq suratdagidan kam (kirim yozilmagan bo'lishi mumkin): {list}",
                     "❗ Остаток в базе меньше, чем на фото (возможно, не записан приход): {list}",
                     "❗ Recorded stock is lower than the photo (a delivery may be unrecorded): {list}"),
    "sh.unknown": ("❔ Bazada yo'q tovarlar: {list}\n<i>Ularni kirim qilib yozing: \"20 ta ... keldi, har biri ...\"</i>",
                   "❔ Нет в базе: {list}\n<i>Запишите приход: «пришло 20 шт. ... по ...»</i>",
                   "❔ Not in the books: {list}\n<i>Record a delivery: \"20 ... arrived, ... each\"</i>"),
    "sh.evening": ("<i>💡 Kechqurun yana suratga oling — kun davomida yozilmagan sotuvni topib beraman.</i>",
                   "<i>💡 Сфотографируйте вечером ещё раз — найду незаписанные за день продажи.</i>",
                   "<i>💡 Take another photo tonight — I'll find sales that weren't recorded.</i>"),
    "sh.approx": ("<i>Sanoq rasm bo'yicha taxminiy.</i>", "<i>Подсчёт по фото — приблизительный.</i>",
                  "<i>Counts from a photo are approximate.</i>"),

    # ---------- bot ----------
    "b.choose_lang": ("🌐 Tilni tanlang · Выберите язык · Choose your language",) * 3,
    "b.lang_set": ("✅ Til: O'zbekcha", "✅ Язык: Русский", "✅ Language: English"),
    "b.welcome": ("Assalomu alaykum! <b>Nasiya AI</b> — mahalla do'konlari uchun aqlli daftar.\n\nSiz kimsiz?",
                  "Здравствуйте! <b>Nasiya AI</b> — умная тетрадь долгов для магазинов у дома.\n\nКто вы?",
                  "Hello! <b>Nasiya AI</b> — a smart credit ledger for neighborhood shops.\n\nWho are you?"),
    "b.role_shop": ("🏪 Do'kon egasiman", "🏪 Я владелец магазина", "🏪 I own a shop"),
    "b.role_cust": ("🛒 Xaridorman — qarzimni ko'rmoqchiman", "🛒 Я покупатель — хочу видеть свой долг",
                    "🛒 I'm a customer — show my balance"),
    "b.known_contact": ("📱 Raqamingiz saqlangan. Do'kon egasi sizni ro'yxatga qo'shgach, avtomatik ulanasiz va xabar "
                        "olasiz.\n\nDo'kon egasi bo'lsangiz:",
                        "📱 Ваш номер сохранён. Как только магазин добавит вас, вы подключитесь автоматически и получите "
                        "сообщение.\n\nЕсли вы владелец магазина:",
                        "📱 Your number is saved. Once a shop adds you, you'll be connected automatically and notified."
                        "\n\nIf you own a shop:"),
    "b.share_contact": ("📱 Raqamimni yuborish", "📱 Отправить мой номер", "📱 Share my number"),
    "b.ask_contact": ("📱 Pastdagi tugma orqali raqamingizni yuboring — qaysi do'konlarda hisobingiz borligini "
                      "topaman.\n\nShundan keyin har bir nasiya va to'lov sizga keladi, xohlagan payt qarzingizni "
                      "ko'rasiz.",
                      "📱 Отправьте свой номер кнопкой ниже — я найду магазины, где у вас есть счёт.\n\n"
                      "После этого каждая запись в долг и оплата будут приходить вам, а долг можно смотреть в любой момент.",
                      "📱 Share your number with the button below — I'll find the shops where you have an account.\n\n"
                      "After that, every credit purchase and payment is sent to you, and you can check your balance "
                      "any time."),
    "b.own_contact": ("Iltimos, <b>o'zingizning</b> raqamingizni pastdagi tugma orqali yuboring.",
                      "Пожалуйста, отправьте <b>свой</b> номер кнопкой ниже.",
                      "Please share <b>your own</b> number using the button below."),
    "b.contact_saved": ("✅ Raqamingiz saqlandi.\n\nHozircha bu raqam hech bir do'kon ro'yxatida yo'q. Do'kon egasi "
                        "raqamingizni kiritishi bilan <b>avtomatik ulanasiz</b> va xabar olasiz.",
                        "✅ Номер сохранён.\n\nПока этого номера нет ни в одном магазине. Как только магазин его добавит, "
                        "вы <b>подключитесь автоматически</b> и получите сообщение.",
                        "✅ Number saved.\n\nNo shop has this number yet. As soon as a shop adds it, you'll be "
                        "<b>connected automatically</b> and notified."),
    "b.found": ("✅ Topildi! Siz ulandingiz.", "✅ Нашёл! Вы подключены.", "✅ Found you! You're connected."),
    "b.cust_linked_phone": ("📱 <b>{name}</b> botga ulandi (raqami bo'yicha) — endi eslatmalar va yozuvlar unga "
                            "Telegram orqali avtomatik boradi.",
                            "📱 <b>{name}</b> подключился к боту (по номеру) — теперь записи и напоминания будут "
                            "приходить ему в Telegram автоматически.",
                            "📱 <b>{name}</b> connected to the bot (by phone number) — entries and reminders now go to "
                            "them on Telegram automatically."),
    "b.cust_linked_link": ("📱 <b>{name}</b> botga ulandi — endi yozuvlarni o'zi ko'radi.",
                           "📱 <b>{name}</b> подключился к боту — теперь сам видит записи.",
                           "📱 <b>{name}</b> connected to the bot — they can now see their entries."),
    "b.linked": ("✅ Siz ulandingiz! Endi har bir nasiya va to'lov sizga keladi.",
                 "✅ Вы подключены! Теперь каждая запись в долг и оплата будут приходить вам.",
                 "✅ You're connected! Every credit purchase and payment will now be sent to you."),
    "b.link_bad": ("Havola eskirgan yoki noto'g'ri. Do'kondan yangisini so'rang.",
                   "Ссылка устарела или неверна. Попросите в магазине новую.",
                   "This link is expired or invalid. Ask the shop for a new one."),
    "b.added_by_shop": ("🏪 <b>{shop}</b> do'koni sizni mijozlar ro'yxatiga qo'shdi.",
                        "🏪 Магазин <b>{shop}</b> добавил вас в список клиентов.",
                        "🏪 <b>{shop}</b> added you to their customer list."),
    "b.btn_my": ("📱 Hisobimni ochish", "📱 Открыть мой счёт", "📱 Open my account"),
    "b.btn_more": ("📊 Batafsil", "📊 Подробнее", "📊 Details"),
    "b.btn_chart": ("📊 Grafik va batafsil", "📊 График и детали", "📊 Chart & details"),
    "b.btn_debtors_app": ("👥 Qarzdorlar ilovada", "👥 Должники в приложении", "👥 Debtors in the app"),
    "b.btn_open_shop": ("📊 Do'konni ochish", "📊 Открыть магазин", "📊 Open shop"),
    "b.btn_open_stock": ("📦 Omborni ochish", "📦 Открыть склад", "📦 Open stock"),
    "b.menu": ("📊 Do'kon", "📊 Магазин", "📊 Shop"),
    "b.help": ("Assalomu alaykum! Men <b>Nasiya AI</b> — do'koningiz daftari va menejeri.\n\n"
               "Shunchaki yozing yoki 🎤 ovoz yuboring:\n"
               "• <i>Akmal aka 2 kilo shakar, bitta non oldi</i> — nasiya\n"
               "• <i>Dilnoza opa 50 ming to'ladi</i> — to'lov\n"
               "• <i>3 ta non naqd sotildi</i> yoki <i>bugun naqd 1 million savdo bo'ldi</i>\n"
               "• <i>10 qop un keldi, har biri 280 ming</i> — kirim\n"
               "• <i>Akmal aka juma kuni beraman dedi</i> — va'da, o'sha kuni eslataman\n"
               "• <i>Akmal akaga limit 500 ming</i> · <i>Akmal aka telefoni 90 123 45 67</i>\n\n"
               "📸 <b>Javonni suratga oling</b> — tovarlarni sanab, nima kam qolganini aytaman. "
               "Ertalab va kechqurun olsangiz, <b>yozilmagan sotuvni</b> topaman.\n"
               "📷 Yuk xati surati — omborga kiritaman.\n\n"
               "{c[bugun]} {c[hafta]} {c[oy]} — savdo va foyda\n"
               "{c[qarzlar]} — qarzdorlar va eslatmalar\n"
               "{c[maslahat]} — do'kon menejeri tavsiyalari\n"
               "{c[ombor]} · {c[vadalar]} · {c[brifing]}\n"
               "{c[ulash]} Akmal aka — mijoz o'z qarzini telefonida ko'rsin\n"
               "{c[avto]} — qarzdorlarga avtomatik eslatmalar (Telegram)\n"
               "{c[javon]} — javon tahlili\n"
               "{c[demo]} — 30 kunlik namuna do'kon bilan sinab ko'rish\n"
               "{c[til]} — tilni o'zgartirish",
               "Здравствуйте! Я <b>Nasiya AI</b> — тетрадь долгов и менеджер вашего магазина.\n\n"
               "Просто напишите или отправьте 🎤 голосовое:\n"
               "• <i>Акмаль-ака взял 2 кг сахара и одну лепёшку в долг</i> — в долг\n"
               "• <i>Дильноза-опа заплатила 50 тысяч</i> — оплата\n"
               "• <i>продали 3 лепёшки за наличные</i> или <i>сегодня наличными продали на 1 миллион</i>\n"
               "• <i>пришло 10 мешков муки по 280 тысяч</i> — приход\n"
               "• <i>Акмаль-ака обещал заплатить в пятницу</i> — обещание, напомню в тот день\n"
               "• <i>лимит Акмаль-аке 500 тысяч</i> · <i>телефон Акмаль-аки 90 123 45 67</i>\n\n"
               "📸 <b>Сфотографируйте полку</b> — посчитаю товары и скажу, чего мало. "
               "Утром и вечером — найду <b>незаписанные продажи</b>.\n"
               "📷 Фото накладной — внесу приход на склад.\n\n"
               "{c[bugun]} {c[hafta]} {c[oy]} — продажи и прибыль\n"
               "{c[qarzlar]} — должники и напоминания\n"
               "{c[maslahat]} — советы менеджера\n"
               "{c[ombor]} · {c[vadalar]} · {c[brifing]}\n"
               "{c[ulash]} Акмаль-ака — клиент видит свой долг в телефоне\n"
               "{c[avto]} — автонапоминания должникам (Telegram)\n"
               "{c[javon]} — анализ полки\n"
               "{c[demo]} — попробовать на примере магазина за 30 дней\n"
               "{c[til]} — сменить язык",
               "Hello! I'm <b>Nasiya AI</b> — your shop's credit ledger and manager.\n\n"
               "Just type or send a 🎤 voice message:\n"
               "• <i>Akmal took 2 kg of sugar and a bread on credit</i> — credit\n"
               "• <i>Dilnoza paid 50,000</i> — payment\n"
               "• <i>sold 3 breads for cash</i> or <i>cash sales today were 1 million</i>\n"
               "• <i>10 bags of flour arrived, 280,000 each</i> — stock in\n"
               "• <i>Akmal promised to pay on Friday</i> — promise, I'll remind you that day\n"
               "• <i>credit limit for Akmal 500,000</i> · <i>Akmal's phone 90 123 45 67</i>\n\n"
               "📸 <b>Photograph the shelf</b> — I'll count items and tell you what's running low. "
               "Morning and evening photos reveal <b>unrecorded sales</b>.\n"
               "📷 Supplier invoice photo — I'll add it to stock.\n\n"
               "{c[bugun]} {c[hafta]} {c[oy]} — sales and profit\n"
               "{c[qarzlar]} — debtors and reminders\n"
               "{c[maslahat]} — shop manager tips\n"
               "{c[ombor]} · {c[vadalar]} · {c[brifing]}\n"
               "{c[ulash]} Akmal — let a customer see their balance on their phone\n"
               "{c[avto]} — automatic reminders to debtors (Telegram)\n"
               "{c[javon]} — shelf audit\n"
               "{c[demo]} — try it with a 30-day sample shop\n"
               "{c[til]} — change language"),
    "b.ask_name": ("🏪 Do'koningiz nomi nima? (masalan: <i>Baraka</i>)\nMijozlarga boradigan xabarlarda shu nom "
                   "ko'rinadi.\n\nTezda sinab ko'rish uchun: {c[demo]} — 30 kunlik namuna do'kon",
                   "🏪 Как называется ваш магазин? (например: <i>Baraka</i>)\nЭто название увидят клиенты в "
                   "сообщениях.\n\nЧтобы быстро попробовать: {c[demo]} — пример магазина за 30 дней",
                   "🏪 What's your shop called? (e.g. <i>Baraka</i>)\nCustomers will see this name in messages.\n\n"
                   "To try it quickly: {c[demo]} — a 30-day sample shop"),
    "b.ask_name_short": ("🏪 Do'koningiz nomi nima?", "🏪 Как называется ваш магазин?", "🏪 What's your shop called?"),
    "b.name_set": ("✅ Do'kon nomi: <b>{name}</b>", "✅ Название магазина: <b>{name}</b>", "✅ Shop name: <b>{name}</b>"),
    "b.name_ready": ("✅ <b>{name}</b> — tayyor! Birinchi yozuvni ayting, masalan:\n<i>10 qop un keldi, har biri 280 ming</i>",
                     "✅ <b>{name}</b> — готово! Скажите первую запись, например:\n<i>пришло 10 мешков муки по 280 тысяч</i>",
                     "✅ <b>{name}</b> — ready! Tell me your first entry, e.g.:\n<i>10 bags of flour arrived, 280,000 each</i>"),
    "b.demo_has_data": ("Do'koningizda ma'lumot bor. Hammasini o'chirib, namuna yuklash uchun:\n<code>{c[demo]} yangi</code>",
                        "В магазине уже есть данные. Чтобы стереть всё и загрузить пример:\n<code>{c[demo]} new</code>",
                        "Your shop already has data. To erase it and load the sample:\n<code>{c[demo]} new</code>"),
    "b.demo_loading": ("⏳ 30 kunlik namuna do'kon yuklanyapti...", "⏳ Загружаю пример магазина за 30 дней...",
                       "⏳ Loading a 30-day sample shop..."),
    "b.demo_done": ("✅ Tayyor: {tx} ta yozuv, {cu} mijoz, {pr} tovar.\n\n"
                    "Endi sinab ko'ring: {c[brifing]} · {c[hafta]} · {c[maslahat]} · {c[qarzlar]} · {c[ombor]}\n"
                    "yoki yozing: <i>Akmal 2 ta non oldi</i>",
                    "✅ Готово: {tx} записей, {cu} клиентов, {pr} товаров.\n\n"
                    "Попробуйте: {c[brifing]} · {c[hafta]} · {c[maslahat]} · {c[qarzlar]} · {c[ombor]}\n"
                    "или напишите: <i>Akmal 2 ta non oldi</i>",
                    "✅ Done: {tx} entries, {cu} customers, {pr} products.\n\n"
                    "Now try: {c[brifing]} · {c[hafta]} · {c[maslahat]} · {c[qarzlar]} · {c[ombor]}\n"
                    "or type: <i>Akmal 2 ta non oldi</i>"),
    "b.ai_error": ("⚠️ AI xatosi: {e}", "⚠️ Ошибка AI: {e}", "⚠️ AI error: {e}"),
    "b.dont_understand": ("Tushunmadim, qaytadan ayting.", "Не понял, повторите, пожалуйста.",
                          "I didn't get that, please say it again."),
    "b.which": ("🤔 Qaysi <b>{name}</b>?", "🤔 Какой(ая) <b>{name}</b>?", "🤔 Which <b>{name}</b>?"),
    "b.new_customer": ("🆕 Yangi mijoz", "🆕 Новый клиент", "🆕 New customer"),
    "b.ask_price": ("💰 <b>{name}</b> narxi qancha? (1 {unit} uchun, masalan: 14 ming)",
                    "💰 Сколько стоит <b>{name}</b>? (за 1 {unit}, например: 14 тысяч)",
                    "💰 What's the price of <b>{name}</b>? (per 1 {unit}, e.g. 14000)"),
    "b.ask_cost": ("💰 <b>{name}</b> xarid narxi qancha? (1 {unit} uchun, masalan: 14 ming)",
                   "💰 Закупочная цена <b>{name}</b>? (за 1 {unit}, например: 14 тысяч)",
                   "💰 Purchase price of <b>{name}</b>? (per 1 {unit}, e.g. 14000)"),
    "b.price_number": ("Narxni son bilan yozing, masalan: <i>14 ming</i> yoki <i>14000</i>",
                       "Напишите цену числом, например: <i>14000</i>", "Please type the price as a number, e.g. <i>14000</i>"),
    "b.confirm": ("✅ Tasdiqlash", "✅ Подтвердить", "✅ Confirm"),
    "b.cancel": ("❌ Bekor", "❌ Отмена", "❌ Cancel"),
    "b.saved_toast": ("Saqlandi ✅", "Сохранено ✅", "Saved ✅"),
    "b.cancelled_toast": ("Bekor qilindi", "Отменено", "Cancelled"),
    "b.not_found": ("Yozuv topilmadi", "Запись не найдена", "Entry not found"),
    "b.already": ("Bu yozuv allaqachon ko'rib chiqilgan", "Эта запись уже обработана", "This entry was already handled"),
    "b.start_first": ("Avval /start bosing", "Сначала нажмите /start", "Please press /start first"),
    "b.notice_sent": ("📱 Mijozga xabar yuborildi.", "📱 Клиенту отправлено уведомление.", "📱 The customer was notified."),
    "b.tip_link": ("💡 <b>{name}</b> o'z qarzini telefonida ko'rib, tasdiqlab tursinmi? {c[ulash]} {short}",
                   "💡 Пусть <b>{name}</b> видит и подтверждает свой долг в телефоне: {c[ulash]} {short}",
                   "💡 Want <b>{name}</b> to see and confirm their balance on their phone? {c[ulash]} {short}"),
    "b.promise_saved": ("🤝 Va'da saqlandi. {when} eslataman.", "🤝 Обещание сохранено. Напомню {when}.",
                        "🤝 Promise saved. I'll remind you {when}."),
    "b.candidates": ("Mos mijozlar: {list}", "Похожие клиенты: {list}", "Matching customers: {list}"),
    "b.no_customer": ("Bunday mijoz topilmadi.", "Такой клиент не найден.", "No such customer."),
    "b.full_name": ("Ismni to'liq yozing.", "Напишите имя полностью.", "Please type the full name."),
    "b.phone_linked": ("📞 {name}: +{phone} saqlandi.\n📱 Bu raqam egasi botda bor — <b>Telegram orqali avtomatik "
                       "ulandi</b>. Endi eslatmalar va yozuvlar unga o'zi boradi.",
                       "📞 {name}: +{phone} сохранён.\n📱 Владелец номера уже есть в боте — <b>подключён к Telegram "
                       "автоматически</b>. Теперь записи и напоминания будут приходить ему сами.",
                       "📞 {name}: +{phone} saved.\n📱 This number's owner is already in the bot — <b>connected on "
                       "Telegram automatically</b>. Entries and reminders now go to them."),
    "b.phone_saved": ("📞 {name}: +{phone} saqlandi.\n\nEslatmalar <b>Telegram orqali avtomatik</b> borishi uchun mijoz "
                      "bir marta @{bot} botini ochib, <b>\"📱 Raqamimni yuborish\"</b> tugmasini bossin — bot uni shu raqam "
                      "bo'yicha o'zi topib ulaydi.\nYoki havola: {url}",
                      "📞 {name}: +{phone} сохранён.\n\nЧтобы напоминания приходили <b>в Telegram автоматически</b>, "
                      "клиенту нужно один раз открыть @{bot} и нажать <b>«📱 Отправить мой номер»</b> — бот сам найдёт "
                      "и подключит его по номеру.\nИли ссылка: {url}",
                      "📞 {name}: +{phone} saved.\n\nFor reminders to go <b>to Telegram automatically</b>, the customer "
                      "opens @{bot} once and taps <b>\"📱 Share my number\"</b> — the bot finds and connects them by "
                      "number.\nOr send this link: {url}"),
    "b.limit_set": ("🛡 {name}: nasiya limiti {amt}. Oshsa ogohlantiraman.",
                    "🛡 {name}: лимит долга {amt}. Предупрежу, если будет превышен.",
                    "🛡 {name}: credit limit {amt}. I'll warn you if it's exceeded."),
    "b.voice_fail": ("⚠️ Ovozni o'qib bo'lmadi: {e}\nMatn bilan yozib ko'ring.",
                     "⚠️ Не удалось распознать голос: {e}\nПопробуйте написать текстом.",
                     "⚠️ Couldn't read the voice message: {e}\nPlease try typing it."),
    "b.voice_off": ("🎤 Ovozli xabarlar hozircha o'chirilgan. Iltimos, matn bilan yozing.",
                    "🎤 Голосовые сообщения пока отключены. Пожалуйста, напишите текстом.",
                    "🎤 Voice messages are turned off for now. Please type your message."),
    "b.photo_kind": ("📷 Bu qanday rasm?", "📷 Что на фото?", "📷 What kind of photo is this?"),
    "b.photo_shelf": ("📸 Javon — tovarlarni sana", "📸 Полка — посчитать товары", "📸 Shelf — count items"),
    "b.photo_invoice": ("📦 Yuk xati — omborga kirim", "📦 Накладная — приход на склад", "📦 Invoice — add to stock"),
    "b.photo_again": ("Rasmni qaytadan yuboring.", "Отправьте фото ещё раз.", "Please send the photo again."),
    "b.shelf_working": ("📸 Javonni tahlil qilyapman...", "📸 Анализирую полку...", "📸 Analyzing the shelf..."),
    "b.shelf_fail": ("⚠️ Rasmni tahlil qilib bo'lmadi: {e}", "⚠️ Не удалось проанализировать фото: {e}",
                     "⚠️ Couldn't analyze the photo: {e}"),
    "b.invoice_working": ("📷 Yuk xatini o'qiyapman...", "📷 Читаю накладную...", "📷 Reading the invoice..."),
    "b.photo_fail": ("⚠️ Rasmni o'qib bo'lmadi: {e}", "⚠️ Не удалось прочитать фото: {e}", "⚠️ Couldn't read the photo: {e}"),
    "b.photo_unclear": ("Rasm tushunarsiz.", "Фото неразборчиво.", "The photo is unclear."),
    "b.invoice_source": ("yuk xati surati", "фото накладной", "invoice photo"),
    "b.shelf_howto": ("📸 Javonni (polkani) suratga olib yuboring.\n\n• Tovarlar yaxshi ko'rinsin, yorug' joyda oling\n"
                      "• Katta do'kon bo'lsa — har bir javonni alohida yuboring\n"
                      "• <b>Ertalab</b> va <b>kechqurun</b> olsangiz, kun davomida yozilmay qolgan sotuvni topaman",
                      "📸 Сфотографируйте полку и отправьте.\n\n• Товары должны быть хорошо видны, снимайте при "
                      "хорошем свете\n• В большом магазине — каждую полку отдельно\n• Снимайте <b>утром</b> и "
                      "<b>вечером</b> — найду незаписанные за день продажи",
                      "📸 Take a photo of the shelf and send it.\n\n• Make sure products are clearly visible, in good "
                      "light\n• In a big shop, send each shelf separately\n• Photos in the <b>morning</b> and "
                      "<b>evening</b> let me find sales that weren't recorded"),
    "b.link_who": ("Kimni ulaymiz? Masalan: <code>{c[ulash]} Akmal aka</code>",
                   "Кого подключить? Например: <code>{c[ulash]} Akmal aka</code>",
                   "Who should I link? E.g. <code>{c[ulash]} Akmal aka</code>"),
    "b.link_not_found": ("Topilmadi.", "Не найдено.", "Not found."),
    "b.link_msg": ("📱 <b>{name}</b> uchun havola:\n{url}\n\nShu havolani unga yuboring (Telegram yoki SMS). Bosgach, u har "
                   "bir yozuvni ko'radi va tasdiqlaydi — tushunmovchiliklar bo'lmaydi.",
                   "📱 Ссылка для <b>{name}</b>:\n{url}\n\nОтправьте её клиенту (Telegram или SMS). После перехода он "
                   "будет видеть и подтверждать каждую запись — без недоразумений.",
                   "📱 Link for <b>{name}</b>:\n{url}\n\nSend it to them (Telegram or SMS). Once opened, they'll see and "
                   "confirm every entry — no more misunderstandings."),
    "b.cust_ok_toast": ("Rahmat! ✅", "Спасибо! ✅", "Thank you! ✅"),
    "b.cust_ok": ("✅ Tasdiqlandi. Rahmat!", "✅ Подтверждено. Спасибо!", "✅ Confirmed. Thank you!"),
    "b.cust_no_toast": ("Do'konchiga xabar berildi", "Магазину сообщено", "The shop was notified"),
    "b.cust_no": ("❌ Do'konchiga xabar berdik — u tekshirib chiqadi.", "❌ Мы сообщили магазину — он проверит запись.",
                  "❌ We've told the shop — they'll check it."),
    "b.correct": ("✅ To'g'ri", "✅ Верно", "✅ Correct"),
    "b.wrong": ("❌ Xato", "❌ Ошибка", "❌ Wrong"),
    "b.disputed": ("⚠️ <b>{name}</b> yozuvni rad etdi:\n{when} — nasiya {amt}\n<i>{src}</i>\n\n"
                   "Iltimos, mijoz bilan gaplashib tekshiring.",
                   "⚠️ <b>{name}</b> оспорил(а) запись:\n{when} — в долг {amt}\n<i>{src}</i>\n\n"
                   "Пожалуйста, уточните у клиента.",
                   "⚠️ <b>{name}</b> disputed an entry:\n{when} — credit {amt}\n<i>{src}</i>\n\n"
                   "Please check with the customer."),
    "b.rem_title": ("🔔 <b>Eslatma — {name}</b>", "🔔 <b>Напоминание — {name}</b>", "🔔 <b>Reminder — {name}</b>"),
    "b.via_tg": ("📱 Telegram orqali", "📱 Через Telegram", "📱 Via Telegram"),
    "b.via_sms": ("✉️ SMS orqali ({phone})", "✉️ По SMS ({phone})", "✉️ Via SMS ({phone})"),
    "b.via_none": ("⚠️ Mijoz ulanmagan va telefoni yo'q", "⚠️ Клиент не подключён, телефона нет",
                   "⚠️ Customer not connected and no phone"),
    "b.send": ("📨 Yuborish", "📨 Отправить", "📨 Send"),
    "b.close": ("✖️ Yopish", "✖️ Закрыть", "✖️ Close"),
    "b.rem_no_channel": ("Matnni nusxalab o'zingiz yuborishingiz mumkin. Keyingi safar avtomatik yuborish uchun:\n"
                         "• ulash havolasini bering: {url}\n• yoki telefonini yozing: <i>{name} telefoni 90 123 45 67</i>",
                         "Можно скопировать текст и отправить самому. Чтобы в следующий раз отправлялось автоматически:\n"
                         "• дайте ссылку для подключения: {url}\n• или напишите телефон: <i>{name} telefoni 90 123 45 67</i>",
                         "You can copy the text and send it yourself. To send automatically next time:\n"
                         "• give them the link: {url}\n• or add their phone: <i>{name} telefoni 90 123 45 67</i>"),
    "b.sent_toast": ("Yuborildi ✅", "Отправлено ✅", "Sent ✅"),
    "b.not_sent_toast": ("Yuborilmadi", "Не отправлено", "Not sent"),
    "b.rem_sent": ("✅ {name}ga eslatma yuborildi.", "✅ Напоминание для {name} отправлено.", "✅ Reminder sent to {name}."),
    "b.rem_failed": ("⚠️ Yuborilmadi: {e}", "⚠️ Не отправлено: {e}", "⚠️ Not sent: {e}"),
    "b.auto_on": ("✅ yoqilgan, har kuni soat <b>{h}:00</b>", "✅ включены, каждый день в <b>{h}:00</b>",
                  "✅ on, every day at <b>{h}:00</b>"),
    "b.auto_off": ("⏸ o'chirilgan", "⏸ выключены", "⏸ off"),
    "b.auto_status": ("🤖 <b>Avtomatik eslatmalar:</b> {state}\n\nKimga boradi: va'da kuni kelgan yoki o'tgan mijozlarga, "
                      "va {age}+ kundan beri to'lamaganlarga. Bitta mijozga ko'pi bilan {gap} kunda bir marta (va'da kuni "
                      "— o'sha kuni).\nKanal: mijoz botga ulangan bo'lsa — Telegram; aks holda SMS (Eskiz ulangan bo'lsa).",
                      "🤖 <b>Автонапоминания:</b> {state}\n\nКому: клиентам, у которых наступил или прошёл день оплаты, "
                      "и тем, кто не платит {age}+ дней. Одному клиенту — не чаще раза в {gap} дня (в день оплаты — в "
                      "тот же день).\nКанал: Telegram, если клиент подключён; иначе SMS (если подключён Eskiz).",
                      "🤖 <b>Automatic reminders:</b> {state}\n\nWho gets them: customers whose promised date has come "
                      "or passed, and those unpaid for {age}+ days. At most once every {gap} days per customer (on the "
                      "promised day — that day).\nChannel: Telegram if the customer is connected; otherwise SMS (if "
                      "Eskiz is set up)."),
    "b.auto_queue": ("<b>Hozir navbatda ({n}):</b>", "<b>Сейчас в очереди ({n}):</b>", "<b>In the queue now ({n}):</b>"),
    "b.auto_nobody": ("Hozir navbatda hech kim yo'q 👍", "Сейчас в очереди никого нет 👍", "No one in the queue right now 👍"),
    "b.not_connected": ("📵 ulanmagan", "📵 не подключён", "📵 not connected"),
    "b.auto_help": ("{c[avto]} off — o'chirish · {c[avto]} on — yoqish · {c[avto]} 18 — soatni o'zgartirish · "
                    "{c[avto]} hozir — hoziroq yuborish",
                    "{c[avto]} off — выключить · {c[avto]} on — включить · {c[avto]} 18 — сменить час · "
                    "{c[avto]} now — отправить сейчас",
                    "{c[avto]} off — turn off · {c[avto]} on — turn on · {c[avto]} 18 — change the hour · "
                    "{c[avto]} now — send now"),
    "b.auto_sending": ("⏳ Eslatmalar yuborilmoqda...", "⏳ Отправляю напоминания...", "⏳ Sending reminders..."),
    "b.auto_none": ("Hozir eslatma kerak bo'lgan mijoz yo'q 👍", "Сейчас некому напоминать 👍", "No one needs a reminder right now 👍"),
}
# fmt: on

BOT_COMMANDS = {
    "uz": [("bugun", "Bugungi savdo va foyda"), ("hafta", "Haftalik hisobot"), ("qarzlar", "Qarzdorlar va eslatmalar"),
           ("maslahat", "Do'kon menejeri tavsiyalari"), ("ombor", "Tovar qoldig'i"), ("vadalar", "To'lov va'dalari"),
           ("brifing", "Ertalabki brifing"), ("ulash", "Mijozni ulash"), ("javon", "Javon tahlili (surat)"),
           ("avto", "Avtomatik eslatmalar"), ("demo", "30 kunlik namuna do'kon"), ("nom", "Do'kon nomi"),
           ("til", "Tilni o'zgartirish"), ("help", "Yordam")],
    "ru": [("today", "Продажи и прибыль за сегодня"), ("week", "Отчёт за неделю"), ("debts", "Должники и напоминания"),
           ("tips", "Советы менеджера"), ("stock", "Остатки на складе"), ("promises", "Обещания оплаты"),
           ("brief", "Утренняя сводка"), ("link", "Подключить клиента"), ("shelf", "Анализ полки (фото)"),
           ("auto", "Автонапоминания"), ("demo", "Пример магазина за 30 дней"), ("name", "Название магазина"),
           ("lang", "Сменить язык"), ("help", "Помощь")],
    "en": [("today", "Today's sales and profit"), ("week", "Weekly report"), ("debts", "Debtors and reminders"),
           ("tips", "Shop manager tips"), ("stock", "Stock levels"), ("promises", "Payment promises"),
           ("brief", "Morning brief"), ("link", "Link a customer"), ("shelf", "Shelf audit (photo)"),
           ("auto", "Automatic reminders"), ("demo", "30-day sample shop"), ("name", "Shop name"),
           ("lang", "Change language"), ("help", "Help")],
}

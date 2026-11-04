"""O'zbekcha vaqt iboralarini sanaga aylantirish: 'ertaga', 'juma kuni', '15-noyabrda', '3 kundan keyin'."""
import calendar
import re
from datetime import date, timedelta

from .nlp import norm, read_number, tokens_of

WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]
MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust",
          "sentabr", "oktabr", "noyabr", "dekabr"]
MONTH_ALIASES = {"sentyabr": 9, "oktyabr": 10}
DATE_WORDS = {"bugun", "ertaga", "indinga", "kuni", "kunga", "kundan", "keyin", "haftadan",
              "oydan", "oxirida", "oxiri", "gacha", "hafta", "oy",
              "завтра", "послезавтра", "сегодня", "tomorrow", "today", "on", "в", "во"}


def _month_num(tok: str) -> int | None:
    for i, m in enumerate(MONTHS, 1):
        if tok.startswith(m):
            return i
    for k, v in MONTH_ALIASES.items():
        if tok.startswith(k):
            return v
    return None


WEEKDAY_PREFIXES = [
    ("dushanba", "понедельник", "monday"), ("seshanba", "вторник", "tuesday"), ("chorshanba", "сред", "wednesday"),
    ("payshanba", "четверг", "thursday"), ("juma", "пятниц", "friday"), ("shanba", "суббот", "saturday"),
    ("yakshanba", "воскресень", "sunday"),
]


def weekday_of(tok: str) -> int | None:
    tok = tok.lstrip("-")
    for i, prefixes in enumerate(WEEKDAY_PREFIXES):
        if any(tok.startswith(p) for p in prefixes):
            return i
    return None


def is_date_token(tok: str) -> bool:
    tok = tok.lstrip("-")
    return tok in DATE_WORDS or weekday_of(tok) is not None or _month_num(tok) is not None


def parse_due_date(text: str, today: date) -> date | None:
    t = norm(text)
    toks = tokens_of(t)

    if "indinga" in toks or "послезавтра" in toks:
        return today + timedelta(days=2)
    if "ertaga" in toks or "завтра" in toks or "tomorrow" in toks:
        return today + timedelta(days=1)

    # "15-noyabrda", "15 noyabr"
    for m in re.finditer(r"(\d{1,2})\s*-?\s*(?:chi\s+)?([a-z']+)", t):
        month = _month_num(m.group(2))
        if not month:
            continue
        day = int(m.group(1))
        try:
            d = date(today.year, month, day)
            return d if d >= today else date(today.year + 1, month, day)
        except ValueError:
            return None

    # "3 kundan keyin", "bir haftadan keyin", "ikki oydan keyin"
    for i, tok in enumerate(toks):
        if tok in ("kundan", "haftadan", "oydan"):
            n, _ = read_number(toks, max(0, i - 1)) if i > 0 else (None, i)
            n = int(n or 1)
            if tok == "kundan":
                return today + timedelta(days=n)
            if tok == "haftadan":
                return today + timedelta(weeks=n)
            return today + timedelta(days=30 * n)

    if "oy" in toks and ("oxirida" in toks or "oxiri" in toks):
        return date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    if "hafta" in toks and ("oxirida" in toks or "oxiri" in toks):
        return today + timedelta(days=(5 - today.weekday()) % 7)

    for tok in toks:
        wd = weekday_of(tok)
        if wd is not None:
            return today + timedelta(days=((wd - today.weekday()) % 7) or 7)

    if "bugun" in toks:
        return today
    return None


WEEKDAYS_I18N = {
    "uz": WEEKDAYS,
    "ru": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
MONTHS_I18N = {
    "uz": MONTHS,
    "ru": ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
           "ноября", "декабря"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}


def label(d: date, lang: str = "uz") -> str:
    from .i18n import norm_lang
    lang = norm_lang(lang)
    wd, mon = WEEKDAYS_I18N[lang][d.weekday()], MONTHS_I18N[lang][d.month - 1]
    if lang == "ru":
        return f"{d.day} {mon}, {wd}"
    if lang == "en":
        return f"{wd}, {mon} {d.day}"
    return f"{d.day}-{mon}, {wd}"


def weekday_short(d: date, lang: str = "uz") -> str:
    from .i18n import norm_lang
    return WEEKDAYS_I18N[norm_lang(lang)][d.weekday()][:2]


def human(d: date | str | None, today: date, lang: str = "uz") -> str:
    from .i18n import tr
    if d is None:
        return "?"
    if isinstance(d, str):
        d = date.fromisoformat(d)
    delta = (d - today).days
    lbl = label(d, lang)
    if delta == 0:
        return tr(lang, "date.today", d=lbl)
    if delta == 1:
        return tr(lang, "date.tomorrow", d=lbl)
    if delta < 0:
        return tr(lang, "date.ago", d=lbl, n=-delta)
    return lbl

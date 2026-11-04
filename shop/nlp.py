"""O'zbekcha matn bilan ishlash uchun umumiy yordamchilar (son, normalizatsiya, tokenlar)."""
import re

NUM_WORDS = {
    "nol": 0, "bir": 1, "ikki": 2, "uch": 3, "to'rt": 4, "besh": 5, "olti": 6, "yetti": 7,
    "sakkiz": 8, "to'qqiz": 9, "o'n": 10, "yigirma": 20, "o'ttiz": 30, "qirq": 40,
    "ellik": 50, "oltmish": 60, "yetmish": 70, "sakson": 80, "to'qson": 90, "yarim": 0.5,
}
TA_WORDS = {"bitta": 1, "ikkita": 2, "uchta": 3, "to'rtta": 4, "beshta": 5, "oltita": 6,
            "yettita": 7, "sakkizta": 8, "to'qqizta": 9, "o'nta": 10}
MULTIPLIERS = {"yuz": 100, "ming": 1000, "million": 1_000_000, "mln": 1_000_000,
               "milliard": 1_000_000_000,
               "тысяч": 1000, "тысячи": 1000, "тысяча": 1000, "тыс": 1000, "миллион": 1_000_000,
               "миллиона": 1_000_000, "млн": 1_000_000, "thousand": 1000, "k": 1000}


def norm(text: str) -> str:
    text = (text or "").lower()
    for ch in "’‘`ʻʼ":
        text = text.replace(ch, "'")
    return text


def tokens_of(text: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?|[a-zа-яё'\-]+|,", text)


def is_number_token(t: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:[.,]\d+)?", t)) or t in NUM_WORDS or t in TA_WORDS


def read_number(tokens, i):
    """tokens[i] dan boshlab son o'qiydi: '1 million 200 ming' -> 1200000. (qiymat, keyingi_i)"""
    total, cur, j, found = 0.0, 0.0, i, False
    while j < len(tokens):
        t = tokens[j]
        if re.fullmatch(r"\d+(?:[.,]\d+)?", t):
            cur += float(t.replace(",", "."))
        elif t in NUM_WORDS:
            cur += NUM_WORDS[t]
        elif t == "yuz" and found:
            cur = (cur or 1) * 100
        elif t in MULTIPLIERS and t != "yuz" and found:
            total += (cur or 1) * MULTIPLIERS[t]
            cur = 0
        else:
            break
        found = True
        j += 1
    if not found:
        return None, i
    value = total + cur
    return (int(value) if value == int(value) else value), j


def parse_amount(text: str):
    """'14 ming', '14000', 'o'n besh ming' -> son yoki None."""
    toks = tokens_of(norm(text))
    for i in range(len(toks)):
        v, _ = read_number(toks, i)
        if v is not None:
            return v
    return None


def amounts_in(text: str, minimum: float = 1000) -> list:
    """Matndagi pul summalari (>= minimum) — sanadagi '15' kabi kichik sonlarni chetlab o'tadi."""
    toks = tokens_of(norm(text))
    out, i = [], 0
    while i < len(toks):
        v, j = read_number(toks, i)
        if v is not None:
            if v >= minimum:
                out.append(v)
            i = j
        else:
            i += 1
    return out


PHONE_RE = re.compile(r"(?:\+?998[\s\-]?)?\(?(\d{2})\)?[\s\-]?(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})")


def normalize_phone(text: str) -> str | None:
    m = PHONE_RE.search(text or "")
    if not m:
        return None
    return "998" + "".join(m.groups())

"""
Vaqtinchalik MOCK AI — Meta API kaliti ishlaguncha bot to'liq ishlashi uchun.

Qoidalarga asoslangan parser. Real AI o'rnini bosmaydi, lekin demo va testlar uchun
oddiy gaplarni tushunadi: nasiya, to'lov, naqd savdo, kirim, va'da, limit, telefon, savol.
"""
import re
from datetime import date

from ..dates import is_date_token, parse_due_date
from ..nlp import (TA_WORDS, amounts_in, is_number_token, norm, normalize_phone,
                   read_number, tokens_of)

UNITS = {
    "kilo": "kg", "kg": "kg", "kilogramm": "kg", "ta": "dona", "dona": "dona",
    "litr": "litr", "l": "litr", "qop": "qop", "pachka": "pachka", "quti": "quti",
    "blok": "blok", "gramm": "g", "shisha": "shisha",
    # ru / en
    "кг": "kg", "кило": "kg", "килограмм": "kg", "шт": "dona", "штук": "dona", "штуки": "dona", "штука": "dona",
    "л": "litr", "литр": "litr", "литра": "litr", "литров": "litr", "мешок": "qop", "мешка": "qop", "мешков": "qop",
    "пачка": "pachka", "пачки": "pachka", "пачек": "pachka",
    "pcs": "dona", "pieces": "dona", "piece": "dona", "liter": "litr", "liters": "litr", "litre": "litr",
    "bag": "qop", "bags": "qop", "pack": "pachka", "packs": "pachka",
}
STOP = {"bilan", "va", "oldi", "oldim", "olib", "ketdi", "nasiyaga", "nasiya", "qarzga",
        "yozib", "yoz", "qo'y", "keldi", "har", "biri", "so'm", "som", "berdi", "to'ladi",
        "naqd", "naqdga", "sotildi", "sotdim", "savdo", "sotuv", "bo'ldi", "dedi", "uchun",
        "limit", "limiti", "telefon", "telefoni", "nomer", "nomeri", "raqami", "kirim", "xarid",
        "взял", "взяла", "взяли", "в", "долг", "и", "по", "за", "наличными", "продал", "продали", "пришло",
        "заплатил", "заплатила", "оплатил", "оплатила", "took", "bought", "on", "credit", "and", "for", "of",
        "paid", "sold", "cash", "arrived", "each", "лимит", "телефон", "phone"}
FILLER = {"bugun", "kecha", "hozir", "endi", "сегодня", "вчера", "today", "yesterday"}
PAY_WORDS = ("to'ladi", "berdi", "qarzidan", "qarzini", "uzdi", "qaytardi",
             "заплатил", "оплатил", "вернул", "погасил", "paid", "repaid")
PROMISE_WORDS = ("beraman", "to'layman", "beradi", "to'laydi", "qaytaraman", "qaytaradi",
                 "va'da", "beramiz", "to'laymiz", "обещал", "заплачу", "отдам", "promised", "will pay")
SALE_WORDS = ("naqd", "naqdga", "sotildi", "sotdim", "savdo", "sotuv", "наличн", "продал", "продали", "cash", "sold")
KIRIM_WORDS = ("keldi", "kirim", "xarid", "пришло", "пришёл", "пришел", "привезли", "arrived", "received", "delivered")
QUESTION_STARTS = ("qancha", "kim", "qaysi", "nechta", "necha", "hamma", "ro'yxat", "nima",
                   "qanaqa", "ko'rsat", "hisobot", "сколько", "кто", "какие", "покажи", "отчёт", "отчет",
                   "how", "who", "what", "show", "which")


def _stem_name(word: str) -> str:
    w = norm(word)
    for suf in ("ning", "ga"):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return word[: -len(suf)]
    return word


def _leading_name(raw: str) -> str | None:
    """Gap boshidagi ism: 'Akmal aka ikki kilo...' -> 'Akmal aka'."""
    words = []
    for w in raw.replace(",", " ").split():
        n = norm(w).strip(".!?")
        if not words and n in FILLER:
            continue
        if (n in STOP or n in FILLER or is_number_token(n) or n in UNITS or is_date_token(n)
                or n.startswith("qarz") or any(n.startswith(p) for p in PROMISE_WORDS)
                or re.match(r"[\d+(]", n)):
            break
        words.append(w.strip(".!?"))
    if not words:
        return None
    words[-1] = _stem_name(words[-1])
    return " ".join(words)


def _items(tokens: list[str]) -> list[dict]:
    items, i = [], 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in TA_WORDS:
            qty, j, unit = TA_WORDS[tok], i + 1, "dona"
        else:
            qty, j = read_number(tokens, i)
            unit = None
        if qty is None:
            i += 1
            continue
        if j < len(tokens) and tokens[j] in UNITS:
            unit = UNITS[tokens[j]]
            j += 1
        name = []
        while j < len(tokens) and tokens[j] not in STOP and tokens[j] != "," \
                and not is_number_token(tokens[j]) and not tokens[j].startswith("qarz"):
            name.append(tokens[j])
            j += 1
        if name:
            items.append({"name": " ".join(name), "qty": qty, "unit": unit, "price": None})
        i = max(j, i + 1)
    return items


def parse_text(text: str, known_customers: list[str] | None = None, today: date | None = None,
               lang: str = "uz", products: list[str] | None = None) -> dict:
    today = today or date.today()
    raw = text.strip()
    t = norm(raw)
    tokens = tokens_of(t)
    res = {"action": "nasiya", "customer": None, "items": [], "amount": None, "question": None,
           "clarify": None, "due_date": None, "phone": None}

    # --- savol ---
    if raw.endswith("?") or (tokens and tokens[0] in QUESTION_STARTS):
        res.update(action="savol", question=raw)
        return res

    # --- telefon: "Akmal aka telefoni 90 123 45 67" ---
    phone = normalize_phone(raw)
    if phone and any(w in tokens for w in ("telefon", "telefoni", "nomer", "nomeri", "raqami", "телефон", "номер", "phone")):
        res.update(action="telefon", customer=_leading_name(raw), phone=phone)
        return res

    # --- limit: "Akmal akaga limit 500 ming" ---
    if any(tok.startswith(("limit", "лимит")) for tok in tokens):
        amounts = amounts_in(raw, minimum=1)
        res.update(action="limit", customer=_leading_name(raw), amount=amounts[0] if amounts else None)
        if res["amount"] is None:
            res["clarify"] = "Limit qancha bo'lsin?"
        return res

    # --- va'da: "Akmal aka juma kuni beraman dedi" ---
    if any(tok.startswith(p) for tok in tokens for p in PROMISE_WORDS) or "will pay" in t:
        due = parse_due_date(raw, today)
        amounts = amounts_in(raw)
        res.update(action="vada", customer=_leading_name(raw),
                   due_date=due.isoformat() if due else None,
                   amount=amounts[0] if amounts else None)
        if not res["customer"]:
            res["clarify"] = "Kim va'da berdi?"
        elif not due:
            res["clarify"] = "Qachon to'lashini aytdi? (masalan: ertaga, juma kuni, 15-noyabr)"
        return res

    if any(w in t for w in PAY_WORDS):
        res["action"] = "tolov"
    elif any(tok.startswith(w) for tok in tokens for w in SALE_WORDS):
        res["action"] = "sotuv"
    elif any(tok.startswith(w) for tok in tokens for w in KIRIM_WORDS):
        res["action"] = "kirim"

    if res["action"] != "tolov":
        res["items"] = _items(tokens)

    # "har biri 280 ming" -> oxirgi mahsulot narxi
    m = re.search(r"(?:har biri|по|each)\s+(\d.+|[a-zа-яё'].+)", t)
    if m and res["items"]:
        price, _ = read_number(tokens_of(m.group(1)), 0)
        if price:
            res["items"][-1]["price"] = price

    # yalpi summa: "Akmal aka 100 ming to'ladi", "Bugun naqd 1 million 200 ming savdo bo'ldi"
    if res["action"] in ("tolov", "sotuv") and not res["items"]:
        amounts = amounts_in(raw, minimum=1)
        res["amount"] = amounts[0] if amounts else None

    if res["action"] in ("nasiya", "tolov"):
        res["customer"] = _leading_name(raw)
        if not res["customer"]:
            res["clarify"] = "Kim oldi? Mijoz ismini ayting." if res["action"] == "nasiya" \
                else "Kim to'ladi?"

    if res["action"] in ("nasiya", "kirim") and not res["items"]:
        res["action"] = "noaniq"
        res["clarify"] = "Tushunmadim: qaysi mahsulot va qancha?"
    if res["action"] in ("tolov", "sotuv") and not res["items"] and not res["amount"]:
        res["action"] = "noaniq"
        res["clarify"] = "Summa qancha?"
    return res


def transcribe(audio: bytes, filename: str = "voice.ogg") -> str:
    # Mock: real transkripsiya yo'q — demo uchun namuna gap qaytaramiz.
    return "Akmal aka ikki kilo shakar bilan bitta non oldi, nasiyaga yozib qo'y"


def parse_image(image: bytes, known_customers: list[str] | None = None, today: date | None = None,
                lang: str = "uz") -> dict:
    return {
        "action": "kirim", "customer": None, "amount": None, "question": None, "clarify": None,
        "due_date": None, "phone": None,
        "items": [
            {"name": "un", "qty": 10, "unit": "qop", "price": 280000},
            {"name": "shakar", "qty": 50, "unit": "kg", "price": 14000},
        ],
    }


def analyze_shelf(image: bytes, product_names: list[str] | None = None, lang: str = "uz") -> dict:
    """Mock: rasmga qaramaydi — demo uchun do'kondagi tovarlardan namunaviy sanoq qaytaradi."""
    import random

    rnd = random.Random(len(image))
    names = [n for n in (product_names or []) if n] or ["coca-cola", "non", "shakar", "un"]
    items = [{"name": n, "count": rnd.randint(0, 24), "confidence": rnd.choice(["high", "medium"])}
             for n in names[:8]]
    return {"items": items, "empty_spots": rnd.randint(0, 3),
            "observations": ["(mock) Bu namunaviy natija — haqiqiy tahlil uchun AI modelni ulang."]}

"""
Muse Spark Open ulanishini tekshirish (Fireworks / Baseten / Modal).

    python check_llm.py                 # 5 ta o'zbekcha gap -> JSON
    python check_llm.py voice.ogg       # + ovoz (Meta MMS) -> matn -> Muse Spark Open
    python check_llm.py voice.ogg --lang=ru
    python check_llm.py javon.jpg       # + javon suratini tahlil qilish
    python check_llm.py chek.jpg --yukxat   # + yuk xati / chek surati

.env faylida: AI_BACKEND=open, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL bo'lishi kerak.
"""
import json
import os
import sys
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()
from django.conf import settings  # noqa: E402

from shop.ai import openai_compat as llm  # noqa: E402
from shop.services import today  # noqa: E402

TESTS = [
    "Akmal aka ikki kilo shakar bilan bitta non oldi, nasiyaga yozib qo'y",
    "Dilnoza opa qarzidan ellik ming so'm berdi",
    "Bugun 10 qop un keldi, har biri 280 ming",
    "Akmal aka juma kuni 200 ming beraman dedi",
    "Bugun naqd bir million ikki yuz ming savdo bo'ldi",
]

print(f"Model: {settings.LLM_MODEL}\nURL:   {settings.LLM_BASE_URL}\nOvoz:  STT_BACKEND={settings.STT_BACKEND or 'off'} {settings.MMS_MODEL if settings.STT_BACKEND == 'mms' else ''}\n")
ok = 0
for t in TESTS:
    start = time.time()
    try:
        out = llm.parse_text(t, ["Akmal aka", "Dilnoza opa"], today())
        ok += 1
        print(f"✅ {time.time() - start:.1f}s  {t}\n   {json.dumps(out, ensure_ascii=False)}\n")
    except Exception as e:  # noqa: BLE001
        print(f"❌ {t}\n   {e}\n")

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
NAMES = ["un", "shakar", "guruch", "coca-cola", "choy", "tuxum", "sut", "non", "kungaboqar yog'i", "sovun"]

for path in [a for a in sys.argv[1:] if not a.startswith("--")]:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        print("❌ fayl ochilmadi:", e)
        continue
    start = time.time()
    try:
        if path.lower().endswith(IMAGE_EXT):
            if "--yukxat" in sys.argv:  # yuk xati / chek: python check_llm.py chek.jpg --yukxat
                out = llm.parse_image(data, ["Akmal aka", "Dilnoza opa"], today())
                print(f"🧾 {time.time() - start:.1f}s  yuk xati: {path}")
            else:  # javon surati: python check_llm.py javon.jpg
                out = llm.analyze_shelf(data, NAMES)
                print(f"📸 {time.time() - start:.1f}s  javon: {path}")
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            from shop.ai import stt
            lang = next((a[7:] for a in sys.argv if a.startswith("--lang=")), "uz")
            text = stt.transcribe(data, lang)
            print(f"🎤 {time.time() - start:.1f}s  {text}")
            print("   →", json.dumps(llm.parse_text(text, ["Akmal aka", "Dilnoza opa"], today(), lang), ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(f"❌ {path}: {e}")

print(f"\nNatija: {ok}/{len(TESTS)}")

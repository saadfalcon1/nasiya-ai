"""
Meta OCHIQ VAZNLI modellar (Muse Spark Open / Muse Glimmer) — OpenAI-mos Chat Completions API orqali.

Bir xil kod bilan ishlaydi:
  • Baseten Model APIs:  LLM_BASE_URL=https://inference.baseten.co/v1   LLM_MODEL=meta-models/muse-spark-open-1026
  • Modal (vLLM endpoint): LLM_BASE_URL=https://<sizning-app>.modal.run/v1
  • Fireworks: LLM_BASE_URL=https://api.fireworks.ai/inference/v1  LLM_MODEL=accounts/fireworks/models/muse-spark-open
    (Muse Spark Open ovozni qabul qilmaydi -> ovoz uchun Meta MMS: shop/ai/stt.py)
  • O'z serveringiz (vLLM / SGLang) — xuddi shunday

Tashkilotchilar tasdiqlagan: ochiq vaznli Meta modellari Stage One va "Use of Meta AI Tooling" uchun hisobga olinadi.
"""
import base64
import json
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import requests
from django.conf import settings

from . import prompts


class LLMError(RuntimeError):
    pass


def _post(messages: list, max_tokens: int = 1200, temperature: float = 0.1) -> dict:
    if not settings.LLM_API_KEY or not settings.LLM_BASE_URL:
        raise LLMError("LLM_BASE_URL yoki LLM_API_KEY o'rnatilmagan")
    url = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    body = {"model": settings.LLM_MODEL, "messages": messages,
            # reasoning model avval "o'ylaydi" — javob kesilib qolmasligi uchun zaxira
            "max_tokens": max(max_tokens, settings.LLM_MIN_TOKENS), "temperature": temperature}
    if settings.LLM_REASONING_EFFORT:  # low = tezroq javob (server qo'llasa)
        body["reasoning_effort"] = settings.LLM_REASONING_EFFORT
    headers = {"Authorization": f"Bearer {settings.LLM_API_KEY}", "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=body, timeout=120)
    if r.status_code == 400 and "reasoning_effort" in body:  # server bu parametrni bilmasa — usiz qayta
        body.pop("reasoning_effort")
        r = requests.post(url, headers=headers, json=body, timeout=120)
    if r.status_code != 200:
        raise LLMError(f"LLM {r.status_code}: {r.text[:300]}")
    return r.json()


def _content(data: dict) -> str:
    """Javob matni. Reasoning modellari fikrlash qismini alohida maydonda yoki <think> ichida qaytarishi mumkin."""
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError):
        raise LLMError(f"Kutilmagan javob: {json.dumps(data)[:300]}")
    text = msg.get("content") or ""
    if isinstance(text, list):  # ba'zi serverlar content'ni bo'laklar ro'yxati sifatida qaytaradi
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _json_of(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise LLMError(f"Model JSON qaytarmadi: {text[:200]}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise LLMError(f"JSON xato: {e}: {m.group(0)[:200]}")


def parse_text(text: str, known_customers: list[str] | None = None, today: date | None = None,
               lang: str = "uz", products: list[str] | None = None) -> dict:
    system = prompts.with_context(prompts.PARSE_TEXT_PROMPT, known_customers or [], today, lang, products)
    data = _post([{"role": "system", "content": system}, {"role": "user", "content": text}])
    return _json_of(_content(data))


def parse_image(image: bytes, known_customers: list[str] | None = None, today: date | None = None,
                lang: str = "uz") -> dict:
    system = prompts.with_context(prompts.PARSE_IMAGE_PROMPT, known_customers or [], today, lang)
    b64 = base64.b64encode(image).decode()
    data = _post([
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": "Rasmni JSON'ga aylantir."},
        ]},
    ], max_tokens=2000)
    return _json_of(_content(data))


TRANSCRIBE_PROMPT = (
    "Bu ovozli xabarda do'konchi o'zbek tilida (ba'zan rus so'zlari aralash) gapiryapti. "
    "Aytilganini so'zma-so'z, lotin yozuvida yozib ber. Sonlarni eshitilganidek so'z bilan yoz. "
    "Hech qanday izoh qo'shma — faqat matnning o'zi."
)


def _to_wav(audio: bytes, filename: str) -> bytes:
    """Telegram ovozi OGG/Opus. Ko'p modellar WAV/MP3 kutadi — ffmpeg bo'lsa WAV'ga o'giramiz."""
    if not shutil.which("ffmpeg"):
        return audio
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / (Path(filename).name or "voice.ogg"), Path(d) / "out.wav"
        src.write_bytes(audio)
        res = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "16000", str(dst)],
                             capture_output=True, timeout=60)
        if res.returncode != 0 or not dst.exists():
            raise LLMError("Ovozni WAV'ga o'girib bo'lmadi: " + res.stderr.decode()[:200])
        return dst.read_bytes()


def transcribe(audio: bytes, filename: str = "voice.ogg") -> str:
    """Faqat model o'zi audio qabul qilsa (input_audio). Muse Spark Open qabul qilmaydi -> shop/ai/stt.py (MMS)."""
    wav = _to_wav(audio, filename)
    fmt = "wav" if wav is not audio else Path(filename).suffix.lstrip(".") or "ogg"
    data = _post([{"role": "user", "content": [
        {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": fmt}},
        {"type": "text", "text": TRANSCRIBE_PROMPT},
    ]}], max_tokens=600, temperature=0)
    text = _content(data).strip().strip('"«»')
    if not text:
        raise LLMError("Bo'sh transkripsiya")
    return text


def analyze_shelf(image: bytes, product_names: list[str] | None = None, lang: str = "uz") -> dict:
    b64 = base64.b64encode(image).decode()
    data = _post([
        {"role": "system", "content": prompts.shelf_prompt(product_names or [], lang)},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": "Javondagi tovarlarni sanab, JSON qaytar."},
        ]},
    ], max_tokens=2500)
    return _json_of(_content(data))

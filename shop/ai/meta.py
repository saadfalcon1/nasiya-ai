"""
Meta Model API mijozi (Responses API).

Tasdiqlangan format (dev.meta.ai'dagi Python namunasi):
  POST https://api.meta.ai/v1/responses
  {"model": "...", "input": [{"role": ..., "content": [{"type": "input_text", "text": ...}]}]}
"""
import base64
import json
import re
from datetime import date

import requests
from django.conf import settings

from . import prompts


class MetaAIError(RuntimeError):
    pass


def _post(input_messages: list) -> dict:
    if not settings.MODEL_API_KEY:
        raise MetaAIError("MODEL_API_KEY o'rnatilmagan")
    r = requests.post(
        settings.MODEL_API_URL,
        headers={"Authorization": f"Bearer {settings.MODEL_API_KEY}",
                 "Content-Type": "application/json"},
        json={"model": settings.MUSE_MODEL, "input": input_messages, "stream": False},
        timeout=90,
    )
    if r.status_code != 200:
        raise MetaAIError(f"Meta API {r.status_code}: {r.text[:300]}")
    return r.json()


def _text_of(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts = []
    for item in data.get("output", []) or []:
        for c in item.get("content", []) or []:
            if isinstance(c, dict) and c.get("text"):
                parts.append(c["text"])
    return "\n".join(parts)


def _json_of(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise MetaAIError(f"Model JSON qaytarmadi: {text[:200]}")
    return json.loads(m.group(0))


def _msg(role: str, *content: dict) -> dict:
    return {"role": role, "content": list(content)}


def parse_text(text: str, known_customers: list[str] | None = None, today: date | None = None,
               lang: str = "uz", products: list[str] | None = None) -> dict:
    system = prompts.with_context(prompts.PARSE_TEXT_PROMPT, known_customers or [], today, lang, products)
    data = _post([
        _msg("system", {"type": "input_text", "text": system}),
        _msg("user", {"type": "input_text", "text": text}),
    ])
    return _json_of(_text_of(data))


def parse_image(image: bytes, known_customers: list[str] | None = None, today: date | None = None,
                lang: str = "uz") -> dict:
    # DIQQAT: rasm formati ("input_image" + data URL) OpenAI Responses uslubida yozilgan.
    # Meta hujjatlarida (Quickstart / API cookbook) tekshirib, kerak bo'lsa moslang.
    b64 = base64.b64encode(image).decode()
    system = prompts.with_context(prompts.PARSE_IMAGE_PROMPT, known_customers or [], today, lang)
    data = _post([
        _msg("system", {"type": "input_text", "text": system}),
        _msg("user",
             {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"},
             {"type": "input_text", "text": "Rasmni JSON'ga aylantir."}),
    ])
    return _json_of(_text_of(data))


def transcribe(audio: bytes, filename: str = "voice.ogg") -> str:
    # TODO: Muse Voice Transcribe endpoint formati hali ma'lum emas.
    # dev.meta.ai -> Audio sahifasidagi kod namunasini olib, shu yerga yozamiz.
    raise MetaAIError("Ovozni matnga o'girish hali ulanmagan (Audio API formati kutilmoqda)")


def analyze_shelf(image: bytes, product_names: list[str] | None = None, lang: str = "uz") -> dict:
    b64 = base64.b64encode(image).decode()
    data = _post([
        _msg("system", {"type": "input_text", "text": prompts.shelf_prompt(product_names or [], lang)}),
        _msg("user",
             {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"},
             {"type": "input_text", "text": "Javondagi tovarlarni sanab, JSON qaytar."}),
    ])
    return _json_of(_text_of(data))

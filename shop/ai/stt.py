"""
Nutq -> matn. Hakaton qoidasi: ishlash vaqtida chaqiriladigan HAR BIR model Meta modeli bo'lishi kerak.

STT_BACKEND:
  mms   — Meta MMS (Massively Multilingual Speech, facebook/mms-1b-all), ochiq vaznli, 1100+ til,
          O'ZBEK tili bor. Serverning o'zida (CPU) ishlaydi; birinchi ishga tushishda ~4 GB yuklab olinadi.
  meta  — Muse Voice Transcribe (Meta Model API, muse-voice-transcribe-1.0). O'zbek tili ro'yxatda yo'q,
          rus/ingliz uchun yaxshi. MODEL_API_KEY kerak.
  mock  — testlar uchun namuna gap.
  ""    — ovoz o'chirilgan (bot "matn bilan yozing" deydi).

Keyin matnni har doim Muse Spark Open tahlil qiladi.
"""
import io
import json
import logging
import os
import shutil
import subprocess
import threading
import wave

import requests
from django.conf import settings

log = logging.getLogger(__name__)

MMS_LANG = {"uz": "uzb-script_latin", "ru": "rus", "en": "eng"}
META_ASR_URL = "https://api.meta.ai/v1/asr/transcribe"


class STTError(RuntimeError):
    pass


class STTDisabled(STTError):
    pass


def pcm16k(audio: bytes) -> bytes:
    """Istalgan audio (Telegram OGG/Opus) -> 16 kHz mono 16-bit PCM."""
    if not shutil.which("ffmpeg"):
        raise STTError("ffmpeg o'rnatilmagan")
    res = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "16000",
                          "pipe:1"], input=audio, capture_output=True, timeout=60)
    if res.returncode != 0 or not res.stdout:
        raise STTError("Ovozni o'qib bo'lmadi: " + res.stderr.decode(errors="ignore")[:200])
    return res.stdout


def wav16k(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return buf.getvalue()


# ---------------- Meta MMS (ochiq vaznli, serverda) ----------------
_lock = threading.Lock()
_mms: dict = {"model": None, "proc": None, "lang": None, "dtype": None}


def _mms_load():
    if _mms["model"] is not None:
        return
    import torch
    from transformers import AutoProcessor, Wav2Vec2ForCTC

    torch.set_num_threads(max(1, os.cpu_count() or 1))
    dtype = getattr(torch, settings.MMS_DTYPE, None) or torch.float32
    log.info("MMS yuklanmoqda: %s (%s)", settings.MMS_MODEL, dtype)
    _mms["proc"] = AutoProcessor.from_pretrained(settings.MMS_MODEL)
    _mms["model"] = Wav2Vec2ForCTC.from_pretrained(settings.MMS_MODEL, torch_dtype=dtype,
                                                   low_cpu_mem_usage=True).eval()
    _mms["dtype"] = dtype
    log.info("MMS tayyor")


def _mms_lang(lang: str):
    code = MMS_LANG.get(lang, MMS_LANG["uz"])
    if _mms["lang"] == code:
        return
    _mms["proc"].tokenizer.set_target_lang(code)
    _mms["model"].load_adapter(code)
    _mms["model"].to(_mms["dtype"])  # adapter og'irliklari ham bir xil turda bo'lsin
    _mms["lang"] = code


def _mms_transcribe(audio: bytes, lang: str) -> str:
    import numpy as np
    import torch

    samples = np.frombuffer(pcm16k(audio), dtype=np.int16).astype(np.float32) / 32768.0
    with _lock:
        _mms_load()
        _mms_lang(lang)
        inputs = _mms["proc"](samples, sampling_rate=16000, return_tensors="pt")
        with torch.inference_mode():
            logits = _mms["model"](inputs["input_values"].to(_mms["dtype"])).logits
        ids = torch.argmax(logits, dim=-1)[0]
        return _mms["proc"].decode(ids)


def preload():
    """Bot ishga tushganda modelni orqa fonda yuklab qo'yadi — birinchi ovozli xabar kutib qolmasin."""
    if settings.STT_BACKEND != "mms":
        return

    def run():
        try:
            with _lock:
                _mms_load()
                _mms_lang("uz")
        except Exception:  # noqa: BLE001
            log.exception("MMS oldindan yuklanmadi")

    threading.Thread(target=run, daemon=True, name="mms-preload").start()


# ---------------- Muse Voice Transcribe (Meta Model API) ----------------
def _meta_transcribe(audio: bytes, lang: str) -> str:
    if not settings.MODEL_API_KEY:
        raise STTError("MODEL_API_KEY o'rnatilmagan")
    req = {"mode": "PUSH_TO_TALK", "model": settings.MUSE_VOICE_MODEL, "audioEncoding": "WAV"}
    files = {"request": (None, json.dumps(req), "application/json"),
             "audio": ("voice.wav", wav16k(pcm16k(audio)), "audio/wav")}
    r = requests.post(META_ASR_URL, headers={"Authorization": f"Bearer {settings.MODEL_API_KEY}"},
                      files=files, timeout=120)
    if r.status_code != 200:
        raise STTError(f"Muse Voice {r.status_code}: {r.text[:300]}")
    return r.json().get("transcript") or ""


def transcribe(audio: bytes, lang: str = "uz") -> str:
    backend = settings.STT_BACKEND
    if backend == "mms":
        text = _mms_transcribe(audio, lang)
    elif backend == "meta":
        text = _meta_transcribe(audio, lang)
    elif backend == "mock":
        from .mock import transcribe as mock_transcribe
        text = mock_transcribe(audio)
    else:
        raise STTDisabled("ovoz o'chirilgan")
    text = (text or "").strip().strip('"«»')
    if not text:
        raise STTError("Bo'sh transkripsiya")
    return text

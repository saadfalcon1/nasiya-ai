"""
AI qatlami. .env dagi AI_BACKEND ga qarab tanlanadi:
    AI_BACKEND=mock      -> shop/ai/mock.py           (kalitsiz, qoidaga asoslangan — test va dev)
    AI_BACKEND=open      -> shop/ai/openai_compat.py  (Muse Spark Open / Glimmer: Baseten, Modal, ...)
    AI_BACKEND=meta      -> shop/ai/meta.py           (Meta Model API, MODEL_API_KEY kerak)
"""
from django.conf import settings


def get_ai():
    if settings.AI_BACKEND == "meta":
        from . import meta
        return meta
    if settings.AI_BACKEND in ("open", "baseten", "modal", "openai"):
        from . import openai_compat
        return openai_compat
    from . import mock
    return mock

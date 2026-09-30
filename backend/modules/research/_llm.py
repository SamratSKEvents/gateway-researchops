"""Thin adapter so the research pipeline uses the shared AI runtime."""
from ..ai_runtime import runtime as _rt

MODEL, BASE = _rt.MODEL, _rt.BASE


async def chat_json(system, user, max_tokens=1000, schema=None):
    return await _rt.chat_json("research.plan", system, user, schema, max_tokens)

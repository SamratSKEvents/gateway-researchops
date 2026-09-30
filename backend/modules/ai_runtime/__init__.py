"""AI Runtime — the ONLY place that talks to a model server.

Public interface:
    await chat(task, system, user, max_tokens=..., schema=None) -> str
    await chat_json(task, system, user, schema, max_tokens=...) -> dict | list | None
    await embed(texts) -> list[list[float]] | None
    recent_calls(n) -> list[dict]          (observability)
    info() -> dict

Configure with env vars (OpenAI-compatible endpoint):
    LLM_BASE_URL  default http://localhost:11434/v1   (Ollama)
    LLM_MODEL     default qwen3:4b
    LLM_API_KEY   default ""  (set for Groq etc.)
    EMBED_MODEL   default nomic-embed-text
"""
from .runtime import chat, chat_json, embed, recent_calls, info  # noqa: F401

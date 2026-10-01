from fastapi import APIRouter
from . import recent_calls, info, usage_of

router = APIRouter(prefix="/api/ai", tags=["ai_runtime"])


@router.get("/calls")
def calls(n: int = 50):
    return {"runtime": info(), "calls": recent_calls(n)}


@router.get("/usage")
def usage(run: str | None = None):
    """LLM token use: per run (run=<id>) or since server start. Counts come from the provider's usage field."""
    return {"runtime": info(), "usage": usage_of(run)}

from fastapi import APIRouter
from . import recent_calls, info

router = APIRouter(prefix="/api/ai", tags=["ai_runtime"])


@router.get("/calls")
def calls(n: int = 50):
    return {"runtime": info(), "calls": recent_calls(n)}

from fastapi import APIRouter
from ..research import service

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("")
async def memory_state(question: str = ""):
    """Research memory across all runs; `question` ranks past investigations by relevance and scopes cross-run contradictions."""
    return await service.memory_state(question)

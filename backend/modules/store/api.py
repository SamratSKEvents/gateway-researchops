from fastapi import APIRouter
from . import bucket, db

router = APIRouter(prefix="/api/store", tags=["store"])


@router.get("/stats")
def stats():
    return {"raw": bucket.stats(), **db.stats()}


@router.get("/search")
async def search(q: str, k: int = 10):
    from ..ai_runtime import embed
    v = await embed([f"search_query: {q}"])
    return {"mode": "vector" if v else "fts", "results": db.search(q, k, v[0] if v else None)}


@router.get("/claims")
def claims(q: str = "", kind: str = "", k: int = 50):
    return db.claims(q, kind, k)


@router.get("/raw")
def raw(url: str):
    return bucket.get(url) or {"error": "not in raw bucket"}

import asyncio, json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from . import service

router = APIRouter(prefix="/api/research", tags=["research"])


class ResearchReq(BaseModel):
    query: str


@router.post("")
async def research(req: ResearchReq):
    if not req.query.strip():
        raise HTTPException(400, "empty query")
    return {"id": service.start_research(req.query)}


class ReplyReq(BaseModel):
    answer: str | dict


class GoalReq(BaseModel):
    goal: str


class WhatIfReq(BaseModel):
    values: dict[str, float]


@router.post("/runs/{rid}/reply")
def reply(rid: str, req: ReplyReq):
    if not service.reply(rid, req.answer):
        raise HTTPException(409, "run is not waiting for input")
    return {"ok": True}


@router.post("/runs/{rid}/goal")
def change_goal(rid: str, req: GoalReq):
    if not req.goal.strip() or not service.change_goal(rid, req.goal):
        raise HTTPException(409, "run is not live")
    return {"ok": True, "note": "applied at the next checkpoint: hypotheses rebuilt, existing evidence re-scored"}


@router.post("/runs/{rid}/whatif")
def whatif(rid: str, req: WhatIfReq):
    out = service.whatif(rid, req.values)
    if out is None:
        raise HTTPException(404, "no belief state for this run")
    return out


@router.get("/runs")
def runs():
    return service.list_runs()


@router.get("/runs/{rid}")
def run(rid: str):
    snap = service.run_snapshot(rid)
    if not snap:
        raise HTTPException(404)
    return snap


@router.get("/health")
def search_health():
    """Research-source health from real call outcomes."""
    from .search import overall, health, cache
    return {**overall(), "providers": health.snapshot(), "cache": cache.stats()}


@router.post("/health/probe")
async def probe_health():
    from .search import probe
    results = await probe()
    return {"probe": results, **search_health()}


@router.get("/runs/{rid}/events")
async def events(rid: str):
    run = service.live.get(rid)
    if not run:
        raise HTTPException(404, "run not live; fetch /api/research/runs/{id}")

    async def gen():
        q, sent = asyncio.Queue(), -1
        run.subscribers.add(q)
        try:
            for ev in list(run.events):
                sent = ev["i"]; yield f"data: {json.dumps(ev, default=list)}\n\n"
            while run.status == "running" or not q.empty():
                try:
                    ev = await asyncio.wait_for(q.get(), 15)
                    if ev["i"] > sent:
                        sent = ev["i"]; yield f"data: {json.dumps(ev, default=list)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
            yield "event: end\ndata: {}\n\n"
        finally:
            run.subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream")

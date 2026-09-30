import asyncio, json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from . import service

router = APIRouter(prefix="/api/research", tags=["research"])


class ResearchReq(BaseModel):
    query: str
    scope: str | None = None          # e.g. "e-scooter subscriptions for students"
    geography: str | None = None      # e.g. "Bengaluru"
    time_range: str | None = None     # e.g. "launch within 12 months"
    depth: str | None = None          # quick | standard | deep  (follow-up research rounds: 0 / 1 / 2)


@router.post("")
async def research(req: ResearchReq):
    if not req.query.strip():
        raise HTTPException(400, "empty query")
    scope = {k: getattr(req, k) for k in ("scope", "geography", "time_range", "depth")}
    return {"id": service.start_research(req.query, scope)}


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


# ---------- derived views & analyses (agents, planner, graph, replay, challenges, court, autopsy) ----------
from ..views import agents as V_agents, planner as V_planner, graph as V_graph   # noqa: E402


def _snap(rid):
    snap = service.run_snapshot(rid)
    if not snap:
        raise HTTPException(404, "no such run")
    return snap


@router.get("/runs/{rid}/agents")
def run_agents(rid: str):
    return V_agents.derive(_snap(rid))["agents"]


@router.get("/runs/{rid}/messages")
def run_messages(rid: str):
    return V_agents.derive(_snap(rid))["messages"]


@router.get("/runs/{rid}/planner")
def run_planner(rid: str):
    return V_planner.derive(_snap(rid))


@router.get("/runs/{rid}/graph")
def run_graph(rid: str, per_hypothesis: int = 8):
    return V_graph.graph(_snap(rid), per_hypothesis)


@router.get("/runs/{rid}/replay")
def run_replay(rid: str):
    return V_graph.replay(_snap(rid))


@router.get("/runs/{rid}/challenges")
def run_challenges(rid: str):
    return _snap(rid)["result"].get("challenges", [])


class CourtReq(BaseModel):
    claim: str


@router.get("/runs/{rid}/court")
def run_court(rid: str):
    s = _snap(rid)
    return {"status": (s["result"].get("background") or {}).get("court"), "hearings": s["result"].get("court", {})}


@router.post("/runs/{rid}/court")
async def hold_court(rid: str, req: CourtReq):
    rec = await service.court_for(rid, req.claim)
    if rec is None:
        raise HTTPException(404, "no such run or claim")
    return rec


@router.get("/runs/{rid}/autopsy")
def run_autopsy(rid: str):
    s = _snap(rid)
    return {"status": (s["result"].get("background") or {}).get("autopsy"), "autopsy": s["result"].get("autopsy")}


@router.post("/runs/{rid}/autopsy")
async def redo_autopsy(rid: str):
    rec = await service.autopsy_for(rid)
    if rec is None:
        raise HTTPException(409, "run has no report yet")
    return rec


class ForkReq(BaseModel):
    assumptions: dict[str, float] = {}
    priors: dict[str, float] = {}
    drop_claims: list[str] = []
    extra: list[dict] = []


class AskReq(BaseModel):
    question: str


@router.post("/runs/{rid}/whatif/fork")
def whatif_fork(rid: str, req: ForkReq):
    out = service.whatif_fork(rid, req.model_dump())
    if out is None:
        raise HTTPException(404, "no belief state for this run")
    return out


@router.post("/runs/{rid}/whatif/ask")
async def whatif_ask(rid: str, req: AskReq):
    if not req.question.strip():
        raise HTTPException(400, "empty question")
    out = await service.whatif_ask(rid, req.question)
    if out is None:
        raise HTTPException(404, "no belief state for this run")
    return out

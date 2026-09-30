"""Research service — starts runs and serves their snapshots (live from memory, finished from disk)."""
import asyncio, json
from .director import Director
from .. import belief
from .paths import RUNS

live: dict[str, Director] = {}


def start_research(query: str, scope: dict | None = None) -> str:
    run = Director(query, scope)
    live[run.id] = run
    asyncio.create_task(run.execute())
    return run.id


def run_snapshot(run_id: str) -> dict | None:
    if run_id in live:
        return live[run_id].snapshot()
    f = RUNS / f"{run_id}.json"
    return json.loads(f.read_text(encoding="utf8")) if run_id.isalnum() and f.exists() else None


def list_runs(limit=40):
    out = []
    for f in sorted(RUNS.glob("*.json"), key=lambda f: -f.stat().st_mtime)[:limit]:
        j = json.loads(f.read_text(encoding="utf8"))
        out.append({"id": j["id"], "query": j["query"], "status": j["status"], "created": j["created"],
                    "subject": (j["result"].get("plan") or {}).get("subject"), "documents": len(j.get("docs", {})),
                    "verdict": ((j["result"].get("report") or {}).get("verdict") or {}).get("label"),
                    "model": (j["result"].get("ai") or {}).get("model"),
                    "search_health": (j["result"].get("search_health") or {}).get("label"),
                    "useful_docs": ((j["result"].get("search_health") or {}).get("fetch") or {}).get("useful_docs")})
    return out


def reply(run_id: str, answer) -> bool:
    """Answer the question the live run is waiting on (goal interview, hypothesis confirmation, VOI question)."""
    run = live.get(run_id)
    return bool(run) and run.reply(answer)


def change_goal(run_id: str, goal: str) -> bool:
    run = live.get(run_id)
    if not run or run.status != "running":
        return False
    run.change_goal(goal)
    return True


def whatif(run_id: str, values: dict) -> dict | None:
    """Recompute the verdict with user-set assumption likelihoods (0-1) — pure math over the stored ledger, no new research."""
    snap = run_snapshot(run_id)
    b = (snap or {}).get("result", {}).get("belief")
    if not b:
        return None
    A = [dict(a, p=min(max(float(values[a["id"]]), 0.01), 0.99)) if a["id"] in values else a for a in b["assumptions"]]
    return {"result": belief.compute(b["hypotheses"], A, b["evidence"]), "cruxes": belief.cruxes(b["hypotheses"], A, b["evidence"])}


# ---------- on-demand analyses on any run (live or saved) ----------
def _persist(run_id, key, sub, value):
    """Store an analysis result into the run (live object or JSON on disk)."""
    run = live.get(run_id)
    if run:
        tgt = run.result.setdefault(key, {}) if sub else run.result
        tgt[sub or key] = value
        run.save()
        return
    f = RUNS / f"{run_id}.json"
    j = json.loads(f.read_text(encoding="utf8"))
    tgt = j["result"].setdefault(key, {}) if sub else j["result"]
    tgt[sub or key] = value
    f.write_text(json.dumps(j, default=list), encoding="utf8")


async def court_for(run_id: str, claim_id: str) -> dict | None:
    from .. import court
    snap = run_snapshot(run_id)
    if not snap or claim_id not in snap.get("claims", {}):
        return None
    rec = await court.hold(claim_id, snap)
    _persist(run_id, "court", claim_id, rec)
    return rec


async def autopsy_for(run_id: str) -> dict | None:
    from .. import autopsy
    snap = run_snapshot(run_id)
    if not snap or not snap.get("result", {}).get("report"):
        return None
    rec = await autopsy.run(snap)
    _persist(run_id, "autopsy", None, rec)
    return rec


def whatif_fork(run_id: str, changes: dict) -> dict | None:
    from .. import whatif as W
    b = ((run_snapshot(run_id) or {}).get("result") or {}).get("belief")
    return W.fork(b, changes) if b else None


async def whatif_ask(run_id: str, question: str) -> dict | None:
    from .. import whatif as W
    snap = run_snapshot(run_id)
    b = ((snap or {}).get("result") or {}).get("belief")
    if not b:
        return None
    rec = await W.ask(b, question, snap["claims"])
    run = live.get(run_id)
    hist = (run.result if run else snap["result"]).setdefault("whatif_questions", [])
    hist.append({k: rec[k] for k in ("question", "mapping_reason", "applied", "diff", "verdict_delta", "flips")} | {"verdict": rec["result"]["verdict"]})
    if run:
        run.save()
    else:
        _persist(run_id, "whatif_questions", None, hist)
    return rec


async def memory_state(question: str = "", backfill: int = 3) -> dict:
    """Cross-run memory. Runs saved before entity extraction existed get their entities extracted (a few per call) and cached."""
    from .. import memory
    ids = [r["id"] for r in list_runs(200)] + [rid for rid in live if rid not in {r["id"] for r in list_runs(200)}]
    snaps = [s for s in (run_snapshot(i) for i in ids) if s]
    for s in [s for s in snaps if s.get("status") == "done" and "entities" not in s.get("result", {})][:backfill]:
        try:
            s["result"]["entities"] = await memory.entities_for(s)
            _persist(s["id"], "entities", None, s["result"]["entities"])
        except Exception:
            pass
    return await memory.state(snaps, question)

"""Research service — starts runs and serves their snapshots (live from memory, finished from disk)."""
import asyncio, json
from .director import Director
from .. import belief
from .paths import RUNS

live: dict[str, Director] = {}


def start_research(query: str) -> str:
    run = Director(query)
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

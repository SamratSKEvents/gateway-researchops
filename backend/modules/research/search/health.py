"""Provider health registry. States are derived ONLY from real call outcomes (or real probes); persisted across restarts."""
import json, os, time
from .cache import DIR

FILE = DIR / "provider_health.json"
DISABLED = {p.strip() for p in os.getenv("RESEARCH_DISABLE_PROVIDERS", "").split(",") if p.strip()}  # for degraded-mode tests
_state: dict[str, dict] = {}
try:
    _state = json.loads(FILE.read_text(encoding="utf8"))
except Exception:
    _state = {}


def _save():
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(_state, indent=1), encoding="utf8")


def get(name):
    s = _state.setdefault(name, {"status": "unknown", "reason": "not used yet", "fails": 0, "cooldown_until": 0, "last_ok": None,
                                 "last_error": None, "last_checked": None, "calls": 0})
    if name in DISABLED:
        return {**s, "status": "disabled", "reason": "disabled by RESEARCH_DISABLE_PROVIDERS"}
    return s


def available(name):
    s = get(name)
    return s["status"] != "disabled" and s["cooldown_until"] <= time.time()


def ok(name, note=""):
    s = get(name)
    s.update(status="healthy", reason=note or "last call succeeded", fails=0, cooldown_until=0, last_ok=time.time(), last_checked=time.time())
    s["calls"] += 1
    _save()


def degraded(name, reason):
    s = get(name)
    s.update(status="degraded", reason=reason, last_checked=time.time())
    s["calls"] += 1
    _save()


def fail(name, reason, cooldown_s=None):
    s = get(name)
    s["fails"] += 1
    s["calls"] += 1
    cd = cooldown_s if cooldown_s is not None else min(60 * 2 ** (s["fails"] - 1), 3600)  # exponential backoff, max 1 h
    s.update(status="failed", reason=reason, last_error=reason, last_checked=time.time(), cooldown_until=time.time() + cd)
    _save()


def snapshot():
    now = time.time()
    return {n: {**get(n), "cooling_down_s": max(0, int(get(n)["cooldown_until"] - now))} for n in list(_state) + [d for d in DISABLED if d not in _state]}

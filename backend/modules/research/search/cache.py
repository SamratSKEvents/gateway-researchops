"""Disk cache of REAL provider responses and fetched pages. Every entry keeps the time it was originally retrieved,
so cached evidence is always identifiable as cached (never fabricated)."""
import hashlib, json, time
from ..paths import RUNS

DIR = RUNS.parent / "cache"
SEARCH_TTL = 14 * 86400
PAGE_TTL = 30 * 86400


def _path(kind, key):
    h = hashlib.sha1(key.encode("utf8")).hexdigest()
    d = DIR / kind / h[:2]
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.json"


def get(kind: str, key: str, ttl: float):
    p = _path(kind, key)
    if not p.exists():
        return None
    try:
        j = json.loads(p.read_text(encoding="utf8"))
    except Exception:
        return None
    return j if time.time() - j["retrieved_at"] <= ttl else None


def put(kind: str, key: str, payload: dict):
    j = {"key": key, "retrieved_at": time.time(), **payload}
    _path(kind, key).write_text(json.dumps(j), encoding="utf8")
    return j


def stats():
    out = {}
    for kind in ("search", "pages"):
        d = DIR / kind
        out[kind] = sum(1 for _ in d.rglob("*.json")) if d.exists() else 0
    return out

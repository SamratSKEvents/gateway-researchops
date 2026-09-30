"""Raw bucket: data/raw/<sha1[:2]>/<sha1(url)>.html + .json (url, via, retrieved_at). The page exactly as downloaded."""
import hashlib, json, time
from .paths import DATA

DIR = DATA / "raw"


def key(url: str) -> str:
    return hashlib.sha1(url.encode("utf8")).hexdigest()


def _base(k):
    d = DIR / k[:2]
    d.mkdir(parents=True, exist_ok=True)
    return d / k


def put(url: str, html: str, via: str = "direct") -> str:
    k = key(url)
    b = _base(k)
    b.with_suffix(".html").write_text(html, encoding="utf8")
    b.with_suffix(".json").write_text(json.dumps({"url": url, "via": via, "retrieved_at": time.time(), "bytes": len(html)}), encoding="utf8")
    return k


def get(url: str) -> dict | None:
    b = _base(key(url))
    if not b.with_suffix(".html").exists():
        return None
    return {**json.loads(b.with_suffix(".json").read_text(encoding="utf8")), "html": b.with_suffix(".html").read_text(encoding="utf8")}


def stats():
    return {"pages": sum(1 for _ in DIR.rglob("*.html")) if DIR.exists() else 0}

import asyncio, json, os, re, time
from collections import deque
import httpx

BASE = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
MODEL = os.getenv("LLM_MODEL", "qwen3:4b")
KEY = os.getenv("LLM_API_KEY", "")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
_LOCAL = "11434" in BASE or "localhost" in BASE or "127.0.0.1" in BASE
_calls: deque = deque(maxlen=200)
_sem = asyncio.Semaphore(int(os.getenv("LLM_CONCURRENCY", "2")))


def info():
    return {"base_url": BASE, "model": MODEL, "embed_model": EMBED_MODEL, "local": _LOCAL}


def recent_calls(n=50):
    return list(_calls)[-n:][::-1]


def _log(task, t0, ok, prompt, out, err=None):
    _calls.append({"task": task, "model": MODEL, "at": time.time(), "latency_ms": int((time.time() - t0) * 1000), "ok": ok,
                   "prompt_chars": len(prompt), "output_preview": (out or "")[:300], "error": err})


async def chat(task, system, user, max_tokens=800, schema=None):
    body = {"model": MODEL, "temperature": 0.2, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if "gpt-oss" in MODEL:
        body["reasoning_effort"] = "low"
    elif _LOCAL:
        body["reasoning_effort"] = "none"   # qwen3 etc.: skip hidden thinking
    if schema:  # constrained decoding: output must match the schema
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}
    t0 = time.time()
    try:
        async with _sem, httpx.AsyncClient(timeout=120) as c:
            for attempt in range(4):
                r = await c.post(f"{BASE}/chat/completions", json=body, headers={"Authorization": f"Bearer {KEY}"} if KEY else {})
                if r.status_code != 429:
                    break
                await asyncio.sleep(min(float(r.headers.get("retry-after", 5)), 30) + attempt * 2)
            r.raise_for_status()
            out = re.sub(r"<think>.*?</think>", "", r.json()["choices"][0]["message"]["content"] or "", flags=re.S).strip()
        _log(task, t0, True, system + user, out)
        return out
    except Exception as e:
        _log(task, t0, False, system + user, None, f"{type(e).__name__}: {e}")
        raise


async def chat_json(task, system, user, schema, max_tokens=1000):
    txt = await chat(task, system + "\nReply with JSON only.", user, max_tokens, schema)
    i = min((txt.find(c) for c in "{[" if c in txt), default=-1)
    return json.JSONDecoder().raw_decode(txt[i:])[0] if i >= 0 else None


async def embed(texts):
    """Embeddings from the same OpenAI-compatible server. Returns None if unavailable (callers fall back to lexical)."""
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            out = []
            for i in range(0, len(texts), 64):
                r = await c.post(f"{BASE}/embeddings", json={"model": EMBED_MODEL, "input": texts[i:i + 64]},
                                 headers={"Authorization": f"Bearer {KEY}"} if KEY else {})
                r.raise_for_status()
                out += [d["embedding"] for d in r.json()["data"]]
        _log("embed", t0, True, f"{len(texts)} texts", f"{len(out)} vectors")
        return out
    except Exception as e:
        _log("embed", t0, False, f"{len(texts)} texts", None, f"{type(e).__name__}: {e}")
        return None

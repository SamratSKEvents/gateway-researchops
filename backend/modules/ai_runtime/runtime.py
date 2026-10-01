import asyncio, contextvars, json, os, re, time
from collections import defaultdict, deque
import httpx

BASE = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
MODEL = os.getenv("LLM_MODEL", "qwen3:4b")
KEY = os.getenv("LLM_API_KEY", "")
# Optional key pool (e.g. several Groq keys): LLM_API_KEYS=k1,k2,k3. Each agent (task prefix) prefers its own key and fails
# over to the others on 429 / 401 / 5xx, so one agent's rate limit does not stall the rest.
KEYS = [k.strip() for k in os.getenv("LLM_API_KEYS", "").split(",") if k.strip()] or ([KEY] if KEY else [])
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
_LOCAL = "11434" in BASE or "localhost" in BASE or "127.0.0.1" in BASE
_calls: deque = deque(maxlen=200)
_sem = asyncio.Semaphore(int(os.getenv("LLM_CONCURRENCY", "2")))
# Token accounting + optional rate budget. LLM_TPM = tokens per minute allowed PER KEY (e.g. a Groq free-tier limit);
# calls wait (never fail) until the rolling 60 s window has room. 0 = unlimited (local model).
TPM = int(os.getenv("LLM_TPM", "0"))
RUN = contextvars.ContextVar("llm_run", default=None)        # set by the research run; inherited by its tasks
usage = defaultdict(lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "by_task": defaultdict(int)})
_window: deque = deque()      # (time, tokens) of recent calls
_wlock = asyncio.Lock()


async def _budget(est: int):
    if not TPM:
        return
    cap = TPM * max(1, len(KEYS))
    while True:
        async with _wlock:
            now = time.time()
            while _window and now - _window[0][0] > 60:
                _window.popleft()
            used = sum(t for _, t in _window)
            if used + est <= cap or not _window:
                _window.append((now, est))
                return
            wait = 60 - (now - _window[0][0]) + 0.1
        await asyncio.sleep(wait)


def _account(task, pt, ct):
    for k in (RUN.get(), "_all"):
        if k:
            u = usage[k]
            u["calls"] += 1; u["prompt_tokens"] += pt; u["completion_tokens"] += ct; u["by_task"][task.split(".")[0]] += pt + ct


def usage_of(run=None):
    u = usage.get(run or "_all")
    if not u:
        return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "by_task": {}}
    return {**{k: u[k] for k in ("calls", "prompt_tokens", "completion_tokens")}, "total_tokens": u["prompt_tokens"] + u["completion_tokens"],
            "by_task": dict(sorted(u["by_task"].items(), key=lambda x: -x[1]))}


def info():
    return {"base_url": BASE, "model": MODEL, "embed_model": EMBED_MODEL, "local": _LOCAL, "keys": len(KEYS), "tpm_per_key": TPM or None}


def keys_for(task: str) -> list[str]:
    """Preferred key for this agent first (stable by task prefix), then the rest of the pool as backups."""
    if not KEYS:
        return [""]
    agent = task.split(".")[0]
    i = sum(map(ord, agent)) % len(KEYS)
    return KEYS[i:] + KEYS[:i]


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
    await _budget(len(system + user) // 4 + max_tokens)      # rough estimate up front; the real count is recorded after
    try:
        async with _sem, httpx.AsyncClient(timeout=120) as c:
            pool = keys_for(task)
            for attempt in range(max(4, len(pool))):
                key = pool[attempt % len(pool)]
                r = await c.post(f"{BASE}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"} if key else {})
                if r.status_code not in (401, 429, 500, 502, 503):
                    break
                if attempt + 1 < len(pool):
                    continue                      # fail over to the next key immediately
                await asyncio.sleep(min(float(r.headers.get("retry-after", 5)), 30) + attempt * 2)
            r.raise_for_status()
            j = r.json()
            out = re.sub(r"<think>.*?</think>", "", j["choices"][0]["message"]["content"] or "", flags=re.S).strip()
            u = j.get("usage") or {}
            _account(task, u.get("prompt_tokens") or len(system + user) // 4, u.get("completion_tokens") or len(out) // 4)
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

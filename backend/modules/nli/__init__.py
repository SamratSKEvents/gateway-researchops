"""Entailment (NLI) model: an independent judge that is not the LLM grading itself.
GPU only: if CUDA or the model is unavailable, available() is False and callers keep their LLM path.

    available() -> bool
    await judge([(premise, hypothesis), ...]) -> [{"entail", "neutral", "contradict"}]  (probabilities)
"""
import asyncio, os, threading

MODEL = os.getenv("NLI_MODEL", "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli")
BATCH = int(os.getenv("NLI_BATCH", "64"))
_lock = threading.Lock()
_state: dict = {}          # {"tok", "model", "labels"} once loaded, {"error"} if it cannot be


def _load():
    with _lock:
        if _state:
            return _state
        try:
            if os.getenv("NLI_DISABLE"):
                raise RuntimeError("disabled by NLI_DISABLE")
            import torch
            if not torch.cuda.is_available():
                raise RuntimeError("no CUDA GPU (NLI runs on GPU only)")
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            tok = AutoTokenizer.from_pretrained(MODEL)
            model = AutoModelForSequenceClassification.from_pretrained(MODEL, dtype=torch.float16).to("cuda").eval()
            labels = {i: l.lower() for i, l in model.config.id2label.items()}
            _state.update(tok=tok, model=model, labels=labels)
        except Exception as e:   # noqa: BLE001 — any failure means "use the LLM path"
            _state["error"] = f"{type(e).__name__}: {e}"
        return _state


def available() -> bool:
    return "model" in _load()


def status() -> dict:
    s = _load()
    return {"model": MODEL, "ready": "model" in s, "error": s.get("error"), "device": "cuda"}


def _judge_sync(pairs):
    import torch
    s = _load()
    tok, model, labels = s["tok"], s["model"], s["labels"]
    order = sorted(range(len(pairs)), key=lambda i: len(pairs[i][0]) + len(pairs[i][1]))   # similar lengths per batch: less padding
    res = [None] * len(pairs)
    for i in range(0, len(order), BATCH):
        idx = order[i:i + BATCH]
        chunk = [pairs[j] for j in idx]
        enc = tok([p for p, _ in chunk], [h for _, h in chunk], truncation="only_first", max_length=512,
                  padding=True, return_tensors="pt").to("cuda")
        with torch.inference_mode():
            probs = model(**enc).logits.float().softmax(-1).cpu().tolist()
        for j, row in zip(idx, probs):
            d = {labels[k]: p for k, p in enumerate(row)}
            res[j] = {"entail": d.get("entailment", 0.0), "neutral": d.get("neutral", 0.0), "contradict": d.get("contradiction", 0.0)}
    return res


async def judge(pairs: list[tuple[str, str]]) -> list[dict]:
    if not pairs:
        return []
    return await asyncio.to_thread(_judge_sync, pairs)

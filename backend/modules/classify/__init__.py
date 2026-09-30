"""Zero-shot text classifier — the one place that turns text into labels (no regexes for meaning).

    await labels(texts, {"key": "hypothesis sentence", ...}) -> [{"key": probability, ...}, ...]   (softmax over keys)
    await best(texts, choices) -> [(key, probability), ...]

GPU entailment model (see nli) scores "text entails <hypothesis sentence>" for every choice; the entailment probabilities
are normalised across choices. If the GPU model is unavailable, one batched LLM call per chunk labels the texts instead.
"""
from .. import nli
from ..ai_runtime import chat_json

LLM_BATCH = 20


async def labels(texts: list[str], choices: dict[str, str], llm=chat_json) -> list[dict[str, float]]:
    if not texts:
        return []
    keys = list(choices)
    if nli.available():
        pairs = [(t[:1500], choices[k]) for t in texts for k in keys]
        scores = await nli.judge(pairs)
        out = []
        for i in range(len(texts)):
            row = [scores[i * len(keys) + j]["entail"] for j in range(len(keys))]
            z = sum(row) or 1.0
            out.append({k: round(v / z, 4) for k, v in zip(keys, row)})
        return out
    return await _llm_labels(texts, choices, keys, llm)


async def _llm_labels(texts, choices, keys, llm):
    schema = {"type": "object", "required": ["labels"], "properties": {"labels": {"type": "array", "items": {"type": "object",
              "required": ["i", "label"], "properties": {"i": {"type": "integer"}, "label": {"enum": keys}}}}}}
    menu = "\n".join(f"- {k}: {choices[k]}" for k in keys)
    out = [{k: 1 / len(keys) for k in keys} for _ in texts]    # uniform = "unknown" when the model fails
    for s in range(0, len(texts), LLM_BATCH):
        chunk = texts[s:s + LLM_BATCH]
        listing = "\n".join(f"[{i}] {t[:600]}" for i, t in enumerate(chunk))
        try:
            j = await llm("classify", f"Label each text with exactly one label.\nLabels:\n{menu}\nReturn every index.", listing, schema, 60 + 25 * len(chunk))
            for x in (j or {}).get("labels", []):
                i = x.get("i")
                if isinstance(i, int) and 0 <= i < len(chunk) and x.get("label") in keys:
                    out[s + i] = {k: (1.0 if k == x["label"] else 0.0) for k in keys}
        except Exception:
            pass
    return out


async def best(texts: list[str], choices: dict[str, str], **kw) -> list[tuple[str, float]]:
    return [max(d.items(), key=lambda kv: kv[1]) for d in await labels(texts, choices, **kw)]


# ---- shared label sets ----
CLAIM_TYPE = {   # what kind of statement a claim is
    "FACT": "This text states a verifiable fact, number or event.",
    "INFERENCE": "This text draws a conclusion or interpretation from facts.",
    "HYPOTHESIS": "This text is a prediction, projection or speculation about the future.",
    "OPINION": "This text expresses a personal opinion or experience.",
}
AGENT_DOMAIN = {   # which specialist a research task belongs to
    "market": "This question is about market size, growth, demand or trends.",
    "competitor": "This question is about competitors, their products or their pricing.",
    "customer": "This question is about customers, users, their needs, behaviour or willingness to pay.",
    "regulation": "This question is about laws, regulation, policy, compliance or operational risk.",
}


# ---- topical relevance (embedding model) ----
RELATED_MIN = 0.62   # cosine; calibration knob: on-topic sentences scored >=0.67, off-topic <=0.54 on the check set
# The entailment model scores UNRELATED sentences as contradictions ("Apple Music" vs a scooter claim), so every
# contradiction/support judgement must first pass this gate.


def _cos(a, b):
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(x * x for x in b) ** 0.5 or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


async def relatedness(anchor: str, texts: list[str], embed=None) -> list[float] | None:
    """Cosine similarity of each text to the anchor; None if no embedding model (callers then skip the gate)."""
    from ..ai_runtime import embed as _embed
    if not texts:
        return []
    v = await (embed or _embed)([f"search_query: {anchor}"] + [f"search_document: {t}" for t in texts])
    if not v:
        return None
    return [round(_cos(v[0], x), 4) for x in v[1:]]

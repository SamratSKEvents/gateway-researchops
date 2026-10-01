"""Research memory across runs (real, computed from saved runs + the global store).

    await entities_for(snap, llm) -> [{"name", "category"}]            (LLM, cached into the run as result.entities)
    await state(runs, question="", embed=..., judge=nli.judge) -> memory payload

projects      every saved run, with relevance to the current question (embedding cosine; entailment model as fallback)
entities      canonical named entities aggregated over runs (competitors, regulators, products, places)
claims        claims seen in more than one run (same sentence or near-duplicate), with the runs they appear in
sources       domains reused across runs and how many claims each fed
contradictions claims from related runs that the entailment model says contradict each other
open_questions report gaps + autopsy follow-ups that no later run resolved
health        counts, freshness buckets, stale share
"""
import math
from collections import Counter, defaultdict
from .. import nli
from ..ai_runtime import chat_json, embed as _embed
from ..ledger import cluster

ENT_SCHEMA = {"type": "object", "required": ["entities"], "properties": {"entities": {"type": "array", "maxItems": 25, "items": {"type": "object",
    "required": ["name", "category"], "properties": {"name": {"type": "string", "maxLength": 60},
                                                    "category": {"enum": ["company", "product", "regulator", "law", "place", "organisation", "person", "other"]}}}}}}
ENT_SYSTEM = ("List the named entities that matter for this business research: companies, products, regulators, laws, places, "
              "organisations. Use the most common canonical name (e.g. 'Yulu', not 'Yulu Bikes Pvt Ltd'). Only entities named in the text.")
TOP_CLAIMS = 30


def _top_claims(snap, n=TOP_CLAIMS):
    ev = sorted(((snap.get("result") or {}).get("belief") or {}).get("evidence", []), key=lambda e: -e["strength"] * e["reliability"])
    out, seen = [], set()
    for e in ev:
        if e["claim"] in snap["claims"] and e["claim"] not in seen:
            seen.add(e["claim"]); out.append(snap["claims"][e["claim"]])
        if len(out) >= n:
            break
    return out or list(snap["claims"].values())[:n]


async def entities_for(snap, llm=chat_json):
    text = f"QUESTION: {snap['query']}\n" + "\n".join(c["text"] for c in _top_claims(snap, 40))
    j = await llm("memory.entities", ENT_SYSTEM, text, ENT_SCHEMA, 700) or {}
    seen, out = set(), []
    for e in j.get("entities", []):
        k = e["name"].strip().lower()
        if k and k not in seen:
            seen.add(k); out.append({"name": e["name"].strip(), "category": e["category"]})
    return out


def _cos(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)) or 1, math.sqrt(sum(x * x for x in b)) or 1
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


async def _relevance(question, runs, embed, judge):
    if not question:
        return {r["id"]: None for r in runs}
    texts = [question] + [r["query"] for r in runs]
    vecs = await embed([f"search_query: {t}" for t in texts]) if embed else None
    if vecs:
        return {r["id"]: round(max(0.0, _cos(vecs[0], v)), 3) for r, v in zip(runs, vecs[1:])}
    if judge is not nli.judge or nli.available():
        sc = await judge([(r["query"], question) for r in runs] + [(question, r["query"]) for r in runs])
        n = len(runs)
        return {r["id"]: round((sc[i]["entail"] + sc[n + i]["entail"]) / 2, 3) for i, r in enumerate(runs)}
    return {r["id"]: None for r in runs}


async def state(runs: list[dict], question: str = "", embed=_embed, judge=nli.judge, related_threshold=0.6) -> dict:
    """runs: full run snapshots (finished or live)."""
    runs = [r for r in runs if r.get("claims")]
    rel = await _relevance(question, runs, embed, judge)
    projects = []
    for r in runs:
        R = r.get("result", {})
        v = (R.get("report") or {}).get("verdict") or {}
        projects.append({"id": r["id"], "question": r["query"], "subject": (R.get("plan") or {}).get("subject"), "created": r.get("created"),
                         "status": r.get("status"), "scope": R.get("scope") or {}, "verdict": v.get("label"), "p": v.get("p"),
                         "claims": len(r["claims"]), "sources": len(r.get("sources", {})),
                         "survival": (R.get("autopsy") or {}).get("survival"), "entities": [e["name"] for e in R.get("entities", [])],
                         "relevance": rel.get(r["id"])})
    projects.sort(key=lambda p: (-(p["relevance"] or 0), -(p["created"] or 0)))

    ents = defaultdict(lambda: {"runs": set(), "category": Counter(), "claims": 0})
    for r in runs:
        for e in r.get("result", {}).get("entities", []):
            k = e["name"].lower()
            ents[k]["name"] = ents[k].get("name") or e["name"]
            ents[k]["runs"].add(r["id"]); ents[k]["category"][e["category"]] += 1
            ents[k]["claims"] += sum(k in c["text"].lower() for c in r["claims"].values())   # name lookup, not classification
    entities = sorted(({"name": v["name"], "category": v["category"].most_common(1)[0][0], "runs": sorted(v["runs"]),
                        "claims": v["claims"]} for v in ents.values()), key=lambda e: (-len(e["runs"]), -e["claims"]))

    items, owner = [], {}
    for r in runs:
        for c in _top_claims(r, 200):
            key = f"{r['id']}:{c['id']}"
            items.append((key, c["text"])); owner[key] = (r, c)
    groups = defaultdict(list)
    for key, g in cluster(items).items():
        groups[g].append(key)
    recurring = []
    for keys in groups.values():
        rs = {owner[k][0]["id"] for k in keys}
        if len(rs) > 1:
            r0, c0 = owner[keys[0]]
            recurring.append({"text": c0["text"], "runs": sorted(rs), "appearances": len(keys),
                              "freshness": min(owner[k][1].get("freshness", 1) for k in keys),
                              "status": next((owner[k][1].get("status") for k in keys if owner[k][1].get("status")), None)})
    recurring.sort(key=lambda x: -x["appearances"])

    dom = defaultdict(lambda: {"runs": set(), "claims": 0, "type": None})
    for r in runs:
        for c in r["claims"].values():
            s = r.get("sources", {}).get(c["source"], {})
            if s.get("domain"):
                d = dom[s["domain"]]; d["runs"].add(r["id"]); d["claims"] += 1; d["type"] = s.get("type")
    total_claims = sum(d["claims"] for d in dom.values()) or 1
    sources = sorted(({"domain": k, "type": v["type"], "runs": sorted(v["runs"]), "claims": v["claims"],
                       "dependency": round(v["claims"] / total_claims, 3)} for k, v in dom.items() if len(v["runs"]) > 1),
                     key=lambda s: -s["claims"])

    contradictions = []
    related = [r for r in runs if (rel.get(r["id"]) or 0) >= related_threshold] if question else runs
    if len(related) > 1 and (judge is not nli.judge or nli.available()):
        pairs, meta = [], []
        related = sorted(related, key=lambda r: -(rel.get(r["id"]) or 0))[:5]
        tops = {r["id"]: _top_claims(r, 8) for r in related}
        for i, a in enumerate(related):
            for b in related[i + 1:]:
                for ca in tops[a["id"]]:
                    for cb in tops[b["id"]]:
                        pairs.append((ca["text"], cb["text"])); meta.append((a, ca, b, cb))
        pairs, meta = pairs[:400], meta[:400]      # ponytail: capped for responsiveness; raise if memory grows useful
        vecs = await embed([t for p in pairs for t in p]) if (embed and pairs) else None
        from ..classify import _cos, RELATED_MIN
        for k, ((a, ca, b, cb), sc) in enumerate(zip(meta, await judge(pairs) if pairs else [])):
            if vecs and _cos(vecs[2 * k], vecs[2 * k + 1]) < RELATED_MIN:
                continue       # unrelated claims: the entailment model's "contradiction" means nothing here
            if sc["contradict"] >= 0.85:
                contradictions.append({"a": {"run": a["id"], "claim": ca["id"], "text": ca["text"]},
                                       "b": {"run": b["id"], "claim": cb["id"], "text": cb["text"]}, "score": round(sc["contradict"], 3)})
        contradictions.sort(key=lambda x: -x["score"])

    open_q = []
    for r in runs:
        R = r.get("result", {})
        for g in (R.get("report") or {}).get("gaps", []):
            open_q.append({"run": r["id"], "question": g["text"], "origin": "report gap", "severity": "MEDIUM"})
        for f in (R.get("autopsy") or {}).get("followups", []):
            open_q.append({"run": r["id"], "question": f["question"], "origin": f"autopsy {f['finding']}", "severity": ["CRITICAL", "HIGH", "MEDIUM", "LOW"][min(f["priority"], 4) - 1]})

    fresh = Counter()
    for r in runs:
        for c in _top_claims(r, 200):
            f = c.get("freshness", 1)
            fresh["fresh" if f >= 0.8 else "aging" if f >= 0.5 else "stale"] += 1
    return {"question": question, "projects": projects, "entities": entities, "recurring_claims": recurring[:60],
            "reused_sources": sources[:60], "contradictions": contradictions[:40], "open_questions": open_q[:80],
            "health": {"investigations": len(runs), "stored_claims": sum(len(r["claims"]) for r in runs), "recurring_claims": len(recurring),
                       "entities": len(entities), "reused_sources": len(sources), "contradictions": len(contradictions),
                       "open_questions": len(open_q), **fresh, "relevance_method": "embeddings" if any(v is not None for v in rel.values()) else None}}

"""Unit economics from the run's own evidence, plus a Monte Carlo over the uncertainty.

    await extract(snap, llm) -> {"applicable", "currency", "params": {name: {value, low, high, basis, cites, note}}}
    simulate(params, overrides={}, trials=2000, seed=7) -> deterministic metrics + distribution percentiles

The LLM only reads numbers out of cited ledger claims (or marks a value as an explicit ASSUMPTION when no claim states it);
every metric and probability is computed here. Model: a recurring-revenue business per customer per month.
"""
import random
from ..ai_runtime import chat_json
from ..ledger import cite_id

PARAMS = {
    "price": "revenue per active customer per month",
    "variable_cost": "cost to serve one active customer per month (servicing, delivery, support, payment, insurance)",
    "cac": "cost to acquire one paying customer",
    "churn": "share of customers who cancel each month (0-1)",
    "fixed_cost": "fixed operating cost per month (team, rent, software)",
}
SCHEMA = {"type": "object", "required": ["applicable", "currency", "params"], "properties": {
    "applicable": {"type": "boolean"}, "currency": {"type": "string", "maxLength": 8},
    "params": {"type": "array", "items": {"type": "object", "required": ["name", "value", "low", "high", "basis", "cites", "note"], "properties": {
        "name": {"enum": list(PARAMS)}, "value": {"type": "number"}, "low": {"type": "number"}, "high": {"type": "number"},
        "basis": {"enum": ["evidence", "assumption"]}, "cites": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
        "note": {"type": "string", "maxLength": 200}}}}}}
SYSTEM = ("You set up a per-customer monthly unit-economics model for a business decision. For each parameter give a likely "
          "value and a low-high range. basis=evidence ONLY if a listed claim states the number (cite its id; convert to per "
          "month and to one currency); otherwise basis=assumption with a conservative range and a note saying why. churn is a "
          "monthly fraction (0.05 = 5%). applicable=false if the decision is not about a business selling to customers.\n"
          "Parameters:\n" + "\n".join(f"- {k}: {v}" for k, v in PARAMS.items()))


def _numeric_claims(snap, n=60):
    """Claims most likely to hold numbers: ones with parsed prices first, then facts the verdict leans on."""
    cl = snap["claims"]
    ev = [e["claim"] for e in sorted(((snap.get("result") or {}).get("belief") or {}).get("evidence", []), key=lambda e: -e["strength"])]
    priced = [c for c in cl.values() if c.get("prices")]
    out, seen = [], set()
    for c in priced + [cl[i] for i in ev if i in cl]:
        if c["id"] not in seen:
            seen.add(c["id"]); out.append(c)
        if len(out) >= n:
            break
    return out


async def extract(snap: dict, llm=chat_json) -> dict:
    claims = _numeric_claims(snap)
    ctx = (f"DECISION: {snap['query']}\nSCOPE: {(snap.get('result') or {}).get('scope') or {}}\n\nCLAIMS:\n"
           + "\n".join(f"[{c['id']}] {c['text']}" for c in claims))
    j = await llm("economics.extract", SYSTEM, ctx, SCHEMA, 1200) or {}
    valid = set(snap["claims"])
    params = {}
    for p in j.get("params", []):
        if p.get("name") not in PARAMS:
            continue
        cites = [c for c in (cite_id(x) for x in p.get("cites", [])) if c in valid]
        lo, v, hi = sorted([float(p["low"]), float(p["value"]), float(p["high"])])
        params[p["name"]] = {"value": v, "low": lo, "high": hi, "cites": cites, "note": p.get("note", ""),
                             "basis": "evidence" if (p.get("basis") == "evidence" and cites) else "assumption",
                             "meaning": PARAMS[p["name"]]}
    return {"applicable": bool(j.get("applicable", True)), "currency": j.get("currency", ""), "params": params}


def _metrics(price, var, cac, churn, fixed):
    margin = price - var
    churn = max(churn, 1e-3)
    ltv = margin / churn
    return {"margin": margin, "ltv": ltv, "ltv_cac": ltv / cac if cac > 0 else None,
            "payback_months": cac / margin if margin > 0 else None,
            "breakeven_customers": fixed / margin if margin > 0 and fixed else None, "lifetime_months": 1 / churn}


def simulate(params: dict, overrides: dict | None = None, trials: int = 2000, seed: int = 7) -> dict:
    P = {k: dict(v) for k, v in params.items()}
    for k, v in (overrides or {}).items():       # a what-if slider pins a parameter
        if k in P:
            P[k].update(value=float(v), low=float(v), high=float(v), basis="override")
    missing = [k for k in ("price", "variable_cost", "cac", "churn") if k not in P]
    if missing:
        return {"error": f"missing parameters: {', '.join(missing)}"}
    g = lambda k: P[k]["value"] if k in P else 0.0      # noqa: E731
    base = _metrics(g("price"), g("variable_cost"), g("cac"), g("churn"), g("fixed_cost"))
    rng = random.Random(seed)
    tri = lambda k: rng.triangular(P[k]["low"], P[k]["high"], P[k]["value"]) if k in P and P[k]["high"] > P[k]["low"] else g(k)   # noqa: E731
    sims = [_metrics(tri("price"), tri("variable_cost"), tri("cac"), tri("churn"), tri("fixed_cost")) for _ in range(trials)]

    def pct(key, qs=(0.1, 0.5, 0.9)):
        xs = sorted(x[key] for x in sims if x[key] is not None)
        return {f"p{int(q * 100)}": round(xs[int(q * (len(xs) - 1))], 3) for q in qs} if xs else None

    return {"base": {k: (round(v, 3) if v is not None else None) for k, v in base.items()},
            "distribution": {"ltv_cac": pct("ltv_cac"), "payback_months": pct("payback_months"), "margin": pct("margin")},
            "probabilities": {"margin_positive": round(sum(x["margin"] > 0 for x in sims) / trials, 3),
                              "ltv_cac_above_3": round(sum((x["ltv_cac"] or 0) > 3 for x in sims) / trials, 3),
                              "payback_under_12m": round(sum((x["payback_months"] or 1e9) < 12 for x in sims) / trials, 3)},
            "evidence_share": round(sum(v["basis"] == "evidence" for v in P.values()) / len(P), 3),
            "assumed": [k for k, v in P.items() if v["basis"] == "assumption"], "trials": trials}

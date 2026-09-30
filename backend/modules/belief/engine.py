"""Inputs (plain dicts, all JSON-serialisable):
  hypotheses  [{id, text, prior, weight, favours}]   favours=+1: true is good for the decision, -1: true is bad
  assumptions [{id, text, hypothesis, p, p0, strength}]  p = current belief (what-if slider), p0 = inferred default
  evidence    [{claim, cluster, hypothesis, stance(+1/-1), strength(0-1), reliability(0-1), freshness(0-1), domains}]
Each evidence cluster counts ONCE per hypothesis (its strongest member); more independent domains add a capped bonus.
Update: logit(P) = logit(prior) + sum_assumptions strength*(logit(p)-logit(p0)) + sum_clusters stance*strength*reliability*freshness*corroboration,
where same-direction clusters saturate: the i-th strongest counts DECAY**i (business sources are rarely fully independent, so
forty generic "the market is growing" lines must not add up to certainty). Max shift per direction = best cluster / (1 - DECAY)."""
import math

K = 1.0            # log-odds moved by one maximal, fully reliable, fresh, single-source cluster
DECAY = 0.7        # i-th strongest cluster in the same direction counts DECAY**i
SD0 = 1.4          # prior uncertainty in log-odds; shrinks as independent evidence accumulates


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def _cluster_weights(evidence, hid):
    """-> {cluster: (signed log-odds shift, |quality|, representative claim)} for one hypothesis."""
    best = {}
    for e in evidence:
        if e["hypothesis"] != hid:
            continue
        q = e["strength"] * e["reliability"] * e["freshness"]
        corroboration = 1 + 0.25 * math.log2(max(1, e.get("domains", 1)))   # 1 domain x1, 4 domains x1.5, capped by log
        w = e["stance"] * q * K * corroboration
        if e["cluster"] not in best or abs(w) > abs(best[e["cluster"]][0]):
            best[e["cluster"]] = (w, q, e["claim"])
    return best


def compute(hypotheses, assumptions, evidence, skip_cluster=None):
    hyps = []
    for h in hypotheses:
        shift_a = sum(a["strength"] * (logit(a["p"]) - logit(a["p0"])) for a in assumptions if a["hypothesis"] == h["id"])
        cw = {c: v for c, v in _cluster_weights(evidence, h["id"]).items() if c != skip_cluster}
        shift_e = sum(w * DECAY ** i for sign in (1, -1)
                      for i, w in enumerate(sorted((w for w, _, _ in cw.values() if w * sign > 0), key=abs, reverse=True)))
        L = logit(h["prior"]) + shift_a + shift_e
        n_eff = sum(q for _, q, _ in cw.values())
        sd = SD0 / math.sqrt(1 + n_eff)
        hyps.append({"id": h["id"], "p": round(sigmoid(L), 4), "low": round(sigmoid(L - sd), 4), "high": round(sigmoid(L + sd), 4),
                     "prior": h["prior"], "evidence_shift": round(shift_e, 3), "assumption_shift": round(shift_a, 3),
                     "clusters": len(cw), "for": sum(w > 0 for w, _, _ in cw.values()), "against": sum(w < 0 for w, _, _ in cw.values()),
                     "n_eff": round(n_eff, 3)})
    tw = sum(h["weight"] for h in hypotheses) or 1
    fav = lambda h, x: x if h["favours"] > 0 else 1 - x   # noqa: E731
    by = {x["id"]: x for x in hyps}
    v = sum(h["weight"] * fav(h, by[h["id"]]["p"]) for h in hypotheses) / tw
    lo = sum(h["weight"] * min(fav(h, by[h["id"]]["low"]), fav(h, by[h["id"]]["high"])) for h in hypotheses) / tw
    hi = sum(h["weight"] * max(fav(h, by[h["id"]]["low"]), fav(h, by[h["id"]]["high"])) for h in hypotheses) / tw
    return {"verdict": round(v, 4), "low": round(lo, 4), "high": round(hi, 4), "hypotheses": hyps}


def cruxes(hypotheses, assumptions, evidence, n=3):
    """Facts/assumptions whose removal (cluster) or reversal (assumption) moves the verdict most; flips = crosses 50%."""
    base = compute(hypotheses, assumptions, evidence)["verdict"]
    out = []
    for c in {e["cluster"] for e in evidence}:
        v = compute(hypotheses, assumptions, evidence, skip_cluster=c)["verdict"]
        rep = max((e for e in evidence if e["cluster"] == c), key=lambda e: e["strength"] * e["reliability"])
        out.append({"kind": "evidence", "id": c, "claim": rep["claim"], "hypothesis": rep["hypothesis"],
                    "verdict_without": round(v, 4), "delta": round(base - v, 4), "flips": (base >= 0.5) != (v >= 0.5)})
    for a in assumptions:
        rev = [dict(x, p=1 - x["p"]) if x["id"] == a["id"] else x for x in assumptions]
        v = compute(hypotheses, rev, evidence)["verdict"]
        out.append({"kind": "assumption", "id": a["id"], "text": a["text"], "hypothesis": a["hypothesis"],
                    "verdict_without": round(v, 4), "delta": round(base - v, 4), "flips": (base >= 0.5) != (v >= 0.5)})
    out.sort(key=lambda x: (-x["flips"], -abs(x["delta"])))
    return out[:n]

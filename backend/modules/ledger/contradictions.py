"""Numeric contradictions: two independent claims about the same subject + measure whose numbers disagree.
Kept side by side, never averaged."""
import re
from collections import Counter

NUM = re.compile(r"(?<![\w.])(?P<cur>₹|rs\.?\s?|inr\s?|\$|usd\s?)?(?P<n>\d[\d,]*(?:\.\d+)?)\s?(?P<mult>k|lakh|crore|cr|mn|million|bn|billion)?\s?(?P<pct>%|percent)?", re.I)
MULT = {"k": 1e3, "lakh": 1e5, "crore": 1e7, "cr": 1e7, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}
MEASURES = {  # measure -> words that must appear in the sentence
    "price": r"price|cost|rent|fee|charge|per month|/month|plan|subscription|priced",
    "market size": r"market (?:size|value|worth)|valued at|market .{0,20}(?:reach|expected|projected)",
    "growth rate": r"cagr|growth rate|grow(?:ing|th)? at",
    "funding": r"raised|funding|investment round|series [a-e]",
    "fleet/users": r"fleet|users|customers|subscribers|vehicles|riders",
}
STOP = {"The", "This", "That", "In", "It", "A", "An", "According", "However", "Its", "Our", "We", "They", "As", "For", "With", "By", "On", "At",
        "Lakh", "Lakhs", "Crore", "Crores", "Rs", "INR", "USD", "Rupees", "Price", "Starting", "Top", "Best", "New"}


def values(text):
    """-> [(kind, value)] kind in {"money", "pct", "count"}; years are ignored."""
    out = []
    for m in NUM.finditer(text):
        n = float(m["n"].replace(",", ""))
        if not m["cur"] and not m["pct"] and not m["mult"] and 1900 <= n <= 2100:
            continue
        if not m["cur"] and not m["pct"]:
            continue                      # bare counts (model numbers, units) are too ambiguous to call a contradiction
        v = n * MULT.get((m["mult"] or "").lower(), 1)
        out.append(("pct" if m["pct"] else "money", v))
    return out


def entities(text):
    """Names: Capitalised words and camel-case product names (iQube, eKart)."""
    return {w for w in re.findall(r"\b(?:[A-Z][a-zA-Z0-9]{2,}|[a-z]+[A-Z][a-zA-Z0-9]*)\b", text) if w not in STOP}


def find_conflicts(claims: list[dict], ratio=1.3, max_ratio=5, limit=30) -> list[dict]:
    """claims: [{id, text, cluster, source}] -> [{measure, subject, a, b, values}] for pairs from different clusters/sources,
    same measure + shared specific named subject, numbers differing by more than `ratio`x but less than `max_ratio`x
    (ponytail: an order of magnitude apart is almost always two different things, not a disagreement)."""
    df = Counter(e for c in claims for e in entities(c["text"]))
    generic = {e for e, n in df.items() if n > max(3, 0.03 * len(claims))}     # "Electric", "Bengaluru": everywhere, not a subject
    facts = []
    for c in claims:
        vals = values(c["text"])
        if not vals:
            continue
        for measure, pat in MEASURES.items():
            if re.search(pat, c["text"], re.I):
                facts.append((measure, entities(c["text"]) - generic, vals, c))
    out, seen, used = [], set(), set()
    for i, (m1, e1, v1, c1) in enumerate(facts):
        for m2, e2, v2, c2 in facts[i + 1:]:
            if m1 != m2 or c1["cluster"] == c2["cluster"] or c1["source"] == c2["source"]:
                continue
            shared = e1 & e2
            if not shared or len(shared) / len(e1 | e2) < 0.5 or c1["id"] in used or c2["id"] in used:
                continue          # "TVS iQube" vs "TVS Jupiter" share a brand, not a subject
            pairs = [(a, b) for ka, a in v1 for kb, b in v2 if ka == kb and a > 0 and b > 0]
            if pairs and all(ratio < max(a, b) / min(a, b) < max_ratio for a, b in pairs):
                key = (m1, min(c1["id"], c2["id"]), max(c1["id"], c2["id"]))
                if key not in seen:
                    seen.add(key)
                    used |= {c1["id"], c2["id"]}
                    out.append({"measure": m1, "subject": sorted(shared)[0], "a": c1["id"], "b": c2["id"],
                                "values": [v1[0][1], v2[0][1]]})
                    if len(out) >= limit:
                        return out
    return out

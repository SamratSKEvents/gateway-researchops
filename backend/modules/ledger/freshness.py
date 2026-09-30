"""Each kind of fact has a half-life: prices go stale in months, market facts in years."""
import re, time

HALF_LIFE_DAYS = {"price": 120, "risk": 365, "opportunity": 540, "fact": 730, "opinion": 365}
YEAR = re.compile(r"\b(20[0-3]\d|19[89]\d)\b")


def claim_year(text: str, doc_year: int | None = None) -> int | None:
    """Latest year mentioned in the sentence (a statement about 2024 is 2024 evidence), else the document's year."""
    now = time.gmtime().tm_year
    ys = [int(y) for y in YEAR.findall(text) if int(y) <= now]
    return max(ys) if ys else doc_year


def doc_year(text: str) -> int | None:
    """Most recent plausible year in the first part of a page (publication/update line usually sits near the top)."""
    return claim_year(text[:1500])


def freshness(kind: str, year: int | None, has_price=False, now: float | None = None) -> float:
    """Weight in (0, 1]. Undated evidence gets a flat 0.6: not trusted as current, not thrown away."""
    if year is None:
        return 0.6
    now_years = 1970 + (now or time.time()) / (365.25 * 86400)
    age_days = max(0.0, (now_years - (year + 0.5)) * 365.25)   # measured from mid-year of `year`
    hl = HALF_LIFE_DAYS["price"] if has_price else HALF_LIFE_DAYS.get(kind, 730)
    return round(max(0.05, 0.5 ** (age_days / hl)), 3)

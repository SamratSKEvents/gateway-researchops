"""Evidence-ledger rules (pure, no I/O): freshness decay, source independence clustering, numeric contradictions."""
from .freshness import claim_year, doc_year, freshness, HALF_LIFE_DAYS  # noqa: F401
from .independence import cluster  # noqa: F401
from .contradictions import find_conflicts, entities  # noqa: F401


def cite_id(x) -> str:
    """Model citation -> ledger id: '[c12]', 'c12', '12', 'exhibit 12' all mean c12."""
    s = str(x).strip().strip("[]() ").lower().replace("exhibit", "").strip()
    return f"c{s}" if s.isdigit() else s

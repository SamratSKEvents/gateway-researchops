"""Report Writer: the LLM drafts cited prose (summary, must-do, must-not-do); code assembles everything numeric or factual
(verdict, hypotheses, cruxes, conflicts, gaps, sources) so nothing in those sections is model-invented."""
from .writer import draft  # noqa: F401
from .assemble import assemble, verdict_label  # noqa: F401

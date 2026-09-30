"""Goal Interviewer + Hypothesis Builder. Open questions in the user's own words, no fixed fields (budget, risk appetite...).
Every function takes `llm` (async (task, system, user, schema, max_tokens) -> dict) so tests can inject a fake."""
from .interviewer import next_step, MAX_QUESTIONS  # noqa: F401
from .hypotheses import build  # noqa: F401

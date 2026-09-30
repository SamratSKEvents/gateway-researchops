"""Research agent — "What does the evidence say about this question?"

Public interface:
    start_research(query) -> run_id
    list_runs(), run_snapshot(run_id)
Internals (pipeline, extract, search) are private to this module.
"""
from .service import start_research, list_runs, run_snapshot  # noqa: F401

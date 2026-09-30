"""Belief Engine: transparent log-odds updates. The LLM only labels evidence stance; this code computes every number."""
from .engine import compute, cruxes, logit, sigmoid  # noqa: F401
from . import stance  # noqa: F401

"""The trial: an adversarial panel that may only argue with ledger evidence, and a separate clerk (verifier) that strikes
any statement its cited quotes do not support."""
from .debate import hold, ROLES  # noqa: F401
from .verifier import verify  # noqa: F401

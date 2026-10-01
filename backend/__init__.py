"""ResearchOps backend. Loads ./.env (KEY=VALUE lines) into the environment before any module reads its config."""
import os
from pathlib import Path

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf8").splitlines():
        _k, _sep, _v = _line.partition("=")
        if _sep and not _line.lstrip().startswith("#"):
            os.environ.setdefault(_k.strip(), _v.strip())     # real environment variables win over the file

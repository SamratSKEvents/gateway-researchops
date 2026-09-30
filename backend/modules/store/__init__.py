"""Global datastore shared by every run.
  bucket — raw bucket: every fetched web page as-is (HTML), keyed by URL. Never parsed, never edited.
  db     — structured store (SQLite): documents, chunks (+ FTS5 + embeddings) and claims, for retrieval across runs."""
from . import bucket, db  # noqa: F401

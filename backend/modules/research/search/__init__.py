"""Research search layer (private to the research module).

    SearchSession().web(query) / .community(provider, name) / .links(site, title) / .fetch(url)
    overall(stats=None) -> {"label": HEALTHY|DEGRADED|OFFLINE|UNKNOWN, "why"}
    probe() -> real minimal check of every provider
    health.snapshot(), cache.stats()
Providers: SearXNG yandex (web search), Reddit via PullPush, Wikipedia articles / external links.
Disable some for testing: RESEARCH_DISABLE_PROVIDERS=a,b
"""
from .engine import SearchSession, overall, probe, QUERY_SPECIFIC  # noqa: F401
from . import health, cache  # noqa: F401

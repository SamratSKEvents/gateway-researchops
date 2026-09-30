import time
from backend.modules.research.search import engine, health, cache


def test_generic_provider_detection():
    s = engine.SearchSession()
    a = {f"https://x/{i}" for i in range(10)}
    assert not s._check_generic("test_p", a)
    assert s._check_generic("test_p", set(a))            # same pages for a different query → generic
    health._state.pop("test_p", None); health._save()
    s2 = engine.SearchSession()
    assert not s2._check_generic("test_q", {"https://a"}) and not s2._check_generic("test_q", {"https://b"})


def test_cache_round_trip_keeps_original_timestamp():
    k = f"test|{time.time()}"
    cache.put("search", k, {"results": [{"url": "u"}]})
    hit = cache.get("search", k, 60)
    assert hit["results"][0]["url"] == "u" and hit["retrieved_at"] <= time.time()


def test_failure_puts_provider_in_cooldown():
    name = f"test_provider_{time.time()}"
    health.fail(name, "boom", cooldown_s=60)
    assert not health.available(name) and health.get(name)["status"] == "failed"
    health.ok(name)
    assert health.available(name)
    health._state.pop(name, None); health._save()

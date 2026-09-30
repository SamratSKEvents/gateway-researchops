import asyncio
from backend.modules.research.director import Director, _to_prob


def test_run_blocks_until_user_replies():
    async def go():
        d = Director("q")
        t = asyncio.create_task(d.ask("interview", {"question": "Who is it for?"}))
        await asyncio.sleep(0.05)
        assert not t.done() and d.pending["kind"] == "interview"
        assert d.reply("commuters") and await t == "commuters"
        assert d.pending is None and not d.reply("late")        # nothing waiting any more
    asyncio.run(go())


def test_optional_questions_time_out_to_stated_assumption():
    async def go():
        return await Director("q").ask("assumption", {"question": "?"}, timeout=0.05)
    assert asyncio.run(go()) is None


def test_answers_become_probabilities():
    assert _to_prob("80") == 0.8 and _to_prob("0.3") == 0.3 and _to_prob("100%") == 0.95
    assert _to_prob("yes") == 0.85 and _to_prob("unsure") is None and _to_prob(None) is None

import asyncio
from backend.modules.report import draft, assemble, verdict_label

H = [{"id": "h1", "text": "demand exists", "prior": 0.5, "weight": 1, "favours": 1}]
BELIEF = {"verdict": 0.62, "low": 0.45, "high": 0.75, "hypotheses": [{"id": "h1", "p": 0.62, "low": 0.45, "high": 0.75, "clusters": 1, "for": 1, "against": 0}]}
CLAIMS = {"c1": {"id": "c1", "source": "s1", "text": "Demand doubled."}, "c2": {"id": "c2", "source": "s2", "text": "x"}}
SOURCES = {"s1": {"id": "s1", "url": "u1", "title": "t", "domain": "a.com", "type_label": "News"},
           "s2": {"id": "s2", "url": "u2", "title": "t", "domain": "b.com", "type_label": "Blog"}}


def test_verdict_label_uses_the_range():
    assert verdict_label(0.7, 0.55, 0.8) == "favourable"
    assert verdict_label(0.3, 0.2, 0.45) == "unfavourable"
    assert verdict_label(0.55, 0.4, 0.7).startswith("leaning favourable")


def test_draft_splits_valid_and_invalid_cites():
    async def llm(*a):
        return {"summary": [{"text": "Demand doubled.", "cites": ["[c1]", "c9"]}], "must_do": [], "must_not": [{"text": "", "cites": []}]}
    d = asyncio.run(draft("ctx", {"c1"}, llm))
    assert d["summary"][0] == {"id": "r1", "text": "Demand doubled.", "cites": ["c1"], "invalid_cites": ["c9"]}
    assert d["must_not"] == []


def test_assemble_strikes_unsupported_and_lists_only_cited_sources():
    prose = {"summary": [{"id": "r1", "text": "Demand doubled.", "cites": ["c1"]}, {"id": "r2", "text": "Made up.", "cites": ["c2"]}],
             "must_do": [], "must_not": []}
    rulings = {"r1": {"ruling": "supported", "reason": "ok"}, "r2": {"ruling": "unsupported", "reason": "not in quote"}}
    r = assemble("Launch?", H, [], BELIEF, [], [], [], prose, rulings, CLAIMS, SOURCES)
    assert [x["id"] for x in r["summary"]] == ["r1"] and r["struck"][0]["id"] == "r2"
    assert [s["id"] for s in r["sources"]] == ["s1"]
    assert r["verification"] == {"statements": 2, "supported": 1, "partial": 0, "struck": 1, "unchecked": 0}
    assert r["gaps"][0]["hypothesis"] == "h1"          # only one evidence cluster


def test_draft_strips_inline_ids_and_drops_actions_copied_from_summary():
    async def llm(task, system, user, schema, max_tokens):
        if task == "report.summary":
            return {"summary": [{"text": "Riders reportedly pay ₹678 a month (c76).", "cites": ["c76"]}]}
        return {"must_do": [{"text": "Riders reportedly pay ₹678 a month (c76).", "cites": ["c76"]},
                            {"text": "Start with delivery riders [c1, c2] first.", "cites": ["c1"]}], "must_not": []}
    d = asyncio.run(draft("ctx", {"c76", "c1"}, llm))
    assert [x["text"] for x in d["summary"]] == ["Riders reportedly pay ₹678 a month."]
    assert [x["text"] for x in d["must_do"]] == ["Start with delivery riders first."]


def test_draft_keeps_summary_when_action_call_fails():
    async def llm(task, *a):
        if task == "report.actions":
            raise RuntimeError("down")
        return {"summary": [{"text": "Demand doubled.", "cites": ["c1"]}]}
    d = asyncio.run(draft("ctx", {"c1"}, llm))
    assert len(d["summary"]) == 1 and d["must_do"] == [] and d["must_not"] == []


def test_research_steps_are_not_accepted_as_business_actions():
    async def llm(task, *a):
        if task == "report.summary":
            return {"summary": []}
        return {"must_do": [{"text": "Identify the key risks in the evidence.", "cites": ["c1"]},
                            {"text": "Start with delivery riders.", "cites": ["c1"]}],
                "must_not": [{"text": "Analyse pricing further.", "cites": ["c1"]}]}
    d = asyncio.run(draft("ctx", {"c1"}, llm))
    assert [x["text"] for x in d["must_do"]] == ["Start with delivery riders."] and d["must_not"] == []

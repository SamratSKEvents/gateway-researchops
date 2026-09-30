from backend.modules.views import agents, planner, graph

SNAP = {"query": "q", "status": "done", "sources": {"s1": {"id": "s1", "domain": "a.com", "type": "news", "tasks": ["t1"]}},
        "claims": {"c1": {"id": "c1", "text": "x", "source": "s1", "tasks": ["t1"]}},
        "result": {"plan": {"tasks": [{"id": "t1", "question": "prices?", "q": "prices", "agent": "competitor"},
                                      {"id": "f2", "question": "h1", "q": "more", "agent": "market", "round": 1, "hypothesis": "h1"}]},
                   "hypotheses": {"hypotheses": [{"id": "h1", "text": "demand"}]}, "voi": [{"hypothesis": "h1", "round": 1, "voi": 0.2, "why": "undecided"}],
                   "belief": {"result": {"verdict": 0.6, "low": 0.4, "high": 0.8, "hypotheses": [{"id": "h1", "p": 0.6, "low": 0.4, "high": 0.8, "clusters": 1}]},
                              "assumptions": [], "evidence": [{"claim": "c1", "hypothesis": "h1", "stance": 1, "strength": 0.8}]}},
        "events": [{"i": 0, "t": 1, "stage": "plan", "status": "done", "title": "plan", "summary": "2 tasks",
                    "data": {"tasks": [{"id": "t1", "question": "prices?", "agent": "competitor"}]}},
                   {"i": 1, "t": 2, "stage": "fetch", "status": "progress", "title": "Read a.com", "summary": "", "data": {"source": "s1"}},
                   {"i": 2, "t": 3, "stage": "belief", "status": "done", "title": "b", "summary": "",
                    "data": {"result": {"hypotheses": [{"id": "h1", "p": 0.6}]}}}]}


def test_agents_messages_route_to_specialist():
    o = agents.derive(SNAP)
    types = [(m["sender"], m["recipient"], m["type"]) for m in o["messages"]]
    assert ("director", "competitor", "TASK_ASSIGNED") in types and ("competitor", "judge", "SOURCE_FOUND") in types
    assert next(a for a in o["agents"] if a["id"] == "competitor")["sources"] == 1


def test_planner_statuses_and_priority():
    p = planner.derive(SNAP)
    st = {t["id"]: (t["status"], t["priority"]) for t in p["tasks"]}
    assert st == {"t1": ("COMPLETED", "MEDIUM"), "f2": ("BLOCKED", "HIGH")}
    assert p["coverage"] == 0.5 and p["uncertainties"][0]["status"] == "OPEN"


def test_graph_links_source_claim_hypothesis():
    g = graph.graph(SNAP)
    e = {(x["source"], x["target"], x["type"]) for x in g["edges"]}
    assert ("s1", "c1", "STATES") in e and ("c1", "h1", "SUPPORTS") in e

import asyncio
from backend.modules import matrix


def test_cells_need_real_citations_and_empty_rows_are_dropped():
    snap = {"query": "q", "claims": {"c1": {"id": "c1", "text": "Yulu costs Rs 1,499 a month.", "prices": ["Rs 1,499"]},
                                     "c2": {"id": "c2", "text": "Bounce operates in 3 cities."}}, "result": {}}

    async def llm(*a):
        return {"rows": ["Yulu", "Bounce", "Ghost"], "columns": ["Monthly price", "Cities", "Funding"], "cells": [
            {"row": "Yulu", "column": "Monthly price", "value": "Rs 1,499", "cites": ["[c1]"]},
            {"row": "Bounce", "column": "Cities", "value": "3", "cites": ["c2"]},
            {"row": "Bounce", "column": "Funding", "value": "$100M", "cites": ["c999"]},      # fake cite -> dropped
            {"row": "Ghost", "column": "Cities", "value": "9", "cites": []}]}                 # no cite -> dropped
    m = asyncio.run(matrix.build(snap, llm=llm))
    assert m["rows"] == ["Yulu", "Bounce"] and m["cells"]["Yulu"]["Monthly price"]["cites"] == ["c1"]
    assert "Funding" not in m["cells"]["Bounce"] and m["coverage"] == round(2 / 6, 3)

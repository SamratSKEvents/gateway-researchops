"""Executive slide deck (.pptx) built ONLY from a run's own records — nothing typed in by hand.

    build(snap) -> BytesIO

Slides: question & goal · how the research ran · hypotheses & odds · strongest evidence · challenges & contradictions ·
evidence court · red-team autopsy · unit economics · verdict & actions · sources.
"""
from io import BytesIO
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

BG, INK, MUTED, ACCENT, GOOD, BAD, MID = (RGBColor(0x0F, 0x13, 0x11), RGBColor(0xE8, 0xEC, 0xE6), RGBColor(0x9A, 0xA5, 0x9E),
                                          RGBColor(0xD9, 0xF3, 0x6B), RGBColor(0x6F, 0xD3, 0x9A), RGBColor(0xFF, 0x8A, 0x7A), RGBColor(0xF2, 0xB8, 0x6B))


def _pct(p):
    return f"{p * 100:.0f}%" if isinstance(p, (int, float)) else "—"


def _cut(s, n):
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1] + "…"


class _Deck:
    def __init__(self):
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(13.333), Inches(7.5)
        self.n = 0

    def slide(self, kicker, title):
        self.n += 1
        s = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        s.background.fill.solid(); s.background.fill.fore_color.rgb = BG
        self.text(s, kicker.upper(), 0.7, 0.4, 10, 0.4, 11, ACCENT, bold=True)
        self.text(s, title, 0.7, 0.75, 11.8, 0.9, 26, INK, bold=True)
        self.text(s, str(self.n), 12.3, 0.4, 0.6, 0.4, 11, MUTED)
        return s

    def text(self, s, txt, x, y, w, h, size=14, color=INK, bold=False):
        tf = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)).text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text, p.font.size, p.font.bold, p.font.color.rgb = txt, Pt(size), bold, color
        return tf

    def bullets(self, s, items, x=0.7, y=1.8, w=11.9, h=5.2, size=15):
        tf = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)).text_frame
        tf.word_wrap = True
        for i, it in enumerate(items or ["(nothing recorded)"]):
            txt, color = it if isinstance(it, tuple) else (it, INK)
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text, p.font.size, p.font.color.rgb, p.space_after = f"•  {txt}", Pt(size), color, Pt(8)
        return tf


def build(snap: dict) -> BytesIO:
    R, claims, sources = snap.get("result", {}), snap.get("claims", {}), snap.get("sources", {})
    rep, bel = R.get("report") or {}, R.get("belief") or {}
    v = rep.get("verdict") or {}
    D = _Deck()

    s = D.slide("Research question", _cut(snap.get("query"), 110))
    goal = R.get("goal") or {}
    D.bullets(s, [f"Verdict: {v.get('label', '—')} — {_pct(v.get('p'))} favourable (range {_pct(v.get('low'))}–{_pct(v.get('high'))})"]
              + [f"{k.replace('_', ' ').title()}: {val}" for k, val in (R.get("scope") or {}).items()]
              + [f"Q: {_cut(x['q'], 110)}  →  {_cut(x['a'], 80)}" for x in goal.get("qa", [])])

    s = D.slide("How the research ran", "Process, sources and evidence")
    sh = (R.get("search_health") or {}).get("fetch") or {}
    plan = R.get("plan") or {}
    D.bullets(s, [f"{len(plan.get('tasks', []))} research tasks across specialists: "
                  + ", ".join(sorted({t.get('agent', '?') for t in plan.get('tasks', [])})),
                  f"{len(sources)} sources registered, {sh.get('useful_docs', '—')} useful documents from {sh.get('useful_domains', '—')} domains",
                  f"{len(claims)} claims extracted; {(R.get('ledger') or {}).get('clusters', '—')} independent clusters after removing copies",
                  f"{len(bel.get('evidence', []))} evidence labels weighed against {len((R.get('hypotheses') or {}).get('hypotheses', []))} hypotheses",
                  f"{len(R.get('challenges', []))} claims challenged and re-researched; {len(R.get('court') or {})} court hearings",
                  f"LLM tokens used: {(R.get('llm_usage') or {}).get('total_tokens', '—')}"])

    s = D.slide("Hypotheses", "What had to be true — and how likely it is now")
    D.bullets(s, [(f"{h['id']}  {_pct(h.get('p'))}  —  {_cut(h['text'], 120)}  (▲{h.get('for', 0)} / ▼{h.get('against', 0)})",
                   GOOD if (h.get("p") or 0) >= 0.6 else BAD if (h.get("p") or 1) <= 0.4 else MID) for h in rep.get("hypotheses", [])])

    s = D.slide("Strongest evidence", "Verbatim claims the verdict leans on")
    top = sorted(bel.get("evidence", []), key=lambda e: -e["strength"] * e["reliability"])
    seen, items = set(), []
    for e in top:
        if e["claim"] in seen or e["claim"] not in claims:
            continue
        seen.add(e["claim"])
        c = claims[e["claim"]]
        items.append((f"“{_cut(c['text'], 130)}” — {sources.get(c['source'], {}).get('domain', '')} ({'supports' if e['stance'] > 0 else 'opposes'} {e['hypothesis']})",
                      GOOD if e["stance"] > 0 else BAD))
        if len(items) >= 6:
            break
    D.bullets(s, items, size=13)

    s = D.slide("Challenge & verify", "What survived independent re-research")
    D.bullets(s, [(f"{r['status']}: {_cut(r['claim_text'], 100)} — {_cut(r['notes'], 70)}",
                   GOOD if r["status"] == "SUPPORTED" else BAD if r["status"] in ("CONTRADICTED", "OUTDATED") else MID) for r in R.get("challenges", [])]
              + [(f"Conflict: {c['measure']} of {c['subject']}: {c['values']}", MID) for c in (R.get("contradictions") or [])[:3]], size=13)

    s = D.slide("Evidence court", "Per-claim hearings and rulings")
    D.bullets(s, [(f"{h['ruling']}: {_cut(h['claim_text'], 90)} — {_cut(h['rationale'], 90)}",
                   GOOD if h["ruling"] == "AFFIRMED" else BAD if h["ruling"] == "OVERRULED" else MID) for h in (R.get("court") or {}).values()], size=13)

    a = R.get("autopsy") or {}
    s = D.slide("Red-team autopsy", f"Survival: {a.get('survival', 'not run')}")
    D.bullets(s, [(f"{f['severity']} · {f['auditor_name']}: {_cut(f['title'], 110)}",
                   BAD if f["severity"] in ("CRITICAL", "HIGH") else MID) for f in a.get("findings", [])[:7]], size=13)

    ec = R.get("economics") or {}
    sim = ec.get("simulation") or {}
    s = D.slide("Unit economics", "Per customer per month, from cited evidence")
    if sim.get("base"):
        b, pr = sim["base"], sim["probabilities"]
        D.bullets(s, [f"{k.replace('_', ' ')}: {p['value']:g} {ec.get('currency', '')} (range {p['low']:g}–{p['high']:g}) — {p['basis']}"
                      + (f" [{', '.join(p['cites'])}]" if p["cites"] else "") for k, p in ec["params"].items()]
                  + [f"Margin {b['margin']:g} · LTV {b['ltv']:g} · LTV/CAC {b['ltv_cac']} · payback {b['payback_months']} months",
                     f"Monte Carlo ({sim['trials']} trials): P(margin>0) {_pct(pr['margin_positive'])} · P(LTV/CAC>3) {_pct(pr['ltv_cac_above_3'])} · P(payback<12m) {_pct(pr['payback_under_12m'])}"],
                  size=13)
    else:
        D.bullets(s, [sim.get("error", "not computed")])

    s = D.slide("Verdict & actions", f"{v.get('label', '—')} — {_pct(v.get('p'))}")
    D.bullets(s, [(f"Do: {_cut(x['text'], 130)}", GOOD) for x in rep.get("must_do", [])]
              + [(f"Don't: {_cut(x['text'], 130)}", BAD) for x in rep.get("must_not", [])]
              + [(f"Crux: {_cut(c.get('text') or claims.get(c.get('claim'), {}).get('text', ''), 120)} (verdict without it {_pct(c['verdict_without'])})", MID)
                 for c in rep.get("cruxes", [])], size=13)

    s = D.slide("Sources", "Every cited source")
    D.bullets(s, [f"{x['domain']} — {_cut(x.get('title'), 80)} ({x.get('type', '')})" for x in rep.get("sources", [])[:14]], size=11)

    buf = BytesIO()
    D.prs.save(buf)
    buf.seek(0)
    return buf

"""Technical decision report (HTML -> vector PDF via headless Chromium), engineering-drawing style: framed sheets, header strip,
footer title block with page numbers, numbered section bars, metric tiles, key-value tables and status stamps.
Built only from the run's records."""
import html, time

FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Condensed:wght@400;500;600;700"
         "&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap")
CSS = """
@page { size: A4; margin: 20mm 12mm 26mm; }
* { box-sizing: border-box; }
body { margin: 0; font: 9.2pt/1.45 'IBM Plex Sans', sans-serif; color: #111; }
.sheet { border: 1.4pt solid #111; padding: 9mm 8mm; min-height: 251mm; position: relative; page-break-after: always; }
.sheet:last-child { page-break-after: auto; }
.mono { font-family: 'IBM Plex Mono', monospace; } .cond { font-family: 'IBM Plex Sans Condensed', sans-serif; }
.k { font: 500 6.6pt 'IBM Plex Mono', monospace; letter-spacing: .08em; text-transform: uppercase; color: #555; }
h1 { font: 700 25pt/1.1 'IBM Plex Sans Condensed', sans-serif; margin: 2mm 0 1mm; letter-spacing: -.01em; }
.sub { font: 500 9pt 'IBM Plex Sans Condensed', sans-serif; letter-spacing: .06em; text-transform: uppercase; color: #333; }
.tb { display: grid; border: 1pt solid #111; margin: 5mm 0; } .tb > div { border-right: .6pt solid #111; padding: 1.6mm 2.2mm; } .tb > div:last-child { border: 0; }
.tb .v { font: 600 11pt 'IBM Plex Mono', monospace; }
.banner { background: #111; color: #fff; text-align: center; font: 600 7.5pt 'IBM Plex Mono', monospace; letter-spacing: .14em; padding: 1.6mm; margin: 3mm 0; }
.stamp { display: inline-block; border: 1.6pt solid currentColor; padding: 1.2mm 3mm; font: 700 9pt 'IBM Plex Sans Condensed', sans-serif; letter-spacing: .06em; text-transform: uppercase; }
.stamp small { display: block; font: 500 6.4pt 'IBM Plex Mono', monospace; letter-spacing: .08em; }
.g { color: #127a3a; } .b { color: #c0272d; } .m { color: #a15c00; } .n { color: #555; }
.sec { display: flex; align-items: center; margin: 6mm 0 3mm; page-break-after: avoid; }
.sec .no { border: 1.4pt solid #111; width: 10mm; height: 7.5mm; display: grid; place-items: center; font: 500 11pt 'IBM Plex Mono', monospace; }
.sec .t { flex: 1; border-bottom: 1.4pt solid #111; padding: 0 0 1mm 3mm; font: 600 13pt 'IBM Plex Sans Condensed', sans-serif; text-transform: uppercase; letter-spacing: .04em; }
.sec .tag { font: 6.6pt 'IBM Plex Mono', monospace; color: #666; border-bottom: 1.4pt solid #111; padding-bottom: 1.4mm; }
h3 { font: 600 9.5pt 'IBM Plex Sans Condensed', sans-serif; text-transform: uppercase; letter-spacing: .05em; margin: 4mm 0 1.5mm; page-break-after: avoid; }
h3 .n2 { font-family: 'IBM Plex Mono', monospace; color: #555; margin-right: 2mm; }
.tiles { display: grid; grid-template-columns: repeat(6, 1fr); border: 1pt solid #111; margin: 2mm 0 4mm; }
.tiles > div { border-right: .6pt solid #111; padding: 1.8mm 2mm; } .tiles > div:last-child { border: 0; }
.tiles .v { font: 600 15pt 'IBM Plex Mono', monospace; line-height: 1.1; } .tiles .u { font: 6.4pt 'IBM Plex Mono', monospace; color: #555; }
table { width: 100%; border-collapse: collapse; font-size: 8.4pt; margin-bottom: 3mm; page-break-inside: auto; }
th { font: 600 6.8pt 'IBM Plex Mono', monospace; text-transform: uppercase; letter-spacing: .06em; text-align: left; border-top: 1.2pt solid #111; border-bottom: .8pt solid #111; padding: 1.2mm 1.6mm; }
td { border-bottom: .4pt solid #bbb; padding: 1.2mm 1.6mm; vertical-align: top; } tr { page-break-inside: avoid; }
td.id, .cite { font: 7pt 'IBM Plex Mono', monospace; color: #555; }
.st { font: 600 6.8pt 'IBM Plex Mono', monospace; border: .9pt solid currentColor; padding: .3mm 1.4mm; white-space: nowrap; }
ol.f { padding-left: 0; list-style: none; counter-reset: f; } ol.f li { counter-increment: f; display: grid; grid-template-columns: 9mm 1fr; margin-bottom: 1.6mm; }
ol.f li::before { content: counter(f, decimal-leading-zero); font: 500 8pt 'IBM Plex Mono', monospace; }
.note { font-size: 7.4pt; color: #444; border-top: .6pt solid #111; padding-top: 1.6mm; margin-top: 3mm; }
"""


def _e(s):
    return html.escape(str(s if s is not None else ""))


def _p(x):
    return f"{x * 100:.0f}%" if isinstance(x, (int, float)) else "—"


def _cls(st):
    return {"SUPPORTED": "g", "AFFIRMED": "g", "VERIFIED": "g", "CONTRADICTED": "b", "OUTDATED": "b", "OVERRULED": "b", "FAILS": "b",
            "CRITICAL": "b", "HIGH": "b", "WEAKENED": "m", "QUALIFIED": "m", "PARTIALLY_SUPPORTED": "m", "MEDIUM": "m"}.get(str(st).upper(), "n")


def build_html(snap: dict) -> str:
    R, claims, sources = snap.get("result", {}), snap.get("claims", {}), snap.get("sources", {})
    rep, bel = R.get("report") or {}, R.get("belief") or {}
    v = rep.get("verdict") or {}
    doc = f"ROPS-{time.strftime('%Y', time.localtime(snap.get('created', time.time())))}-{snap['id'][:6].upper()}"
    cite = lambda cs: f" <span class='cite'>[{', '.join(_e(c) for c in cs)}]</span>" if cs else ""   # noqa: E731
    ledger, fetch = R.get("ledger") or {}, (R.get("search_health") or {}).get("fetch") or {}
    secs, n = [], [0]

    def sec(title, tag=""):
        n[0] += 1
        return f"<div class='sec'><div class='no'>{n[0]:02d}</div><div class='t'>{_e(title)}</div><div class='tag'>§{n[0]:02d} {_e(tag)}</div></div>"

    # ---- cover ----
    scope = R.get("scope") or {}
    cover = [f"<div class='sheet'><div class='k'>Technical decision report — autonomous business research</div>",
             f"<h1>{_e(snap.get('query'))}</h1><div class='sub'>Goal interview · hypotheses · multi-source evidence · challenge &amp; verify · trial · verdict</div>",
             "<div class='tb' style='grid-template-columns: 1.3fr 2fr 1.3fr'>"
             f"<div><div class='k'>Document ID</div><div class='v'>{doc}</div></div>"
             f"<div><div class='k'>Scope</div><div class='v' style='font-size:9.5pt'>{_e(' · '.join(f'{k}: {x}' for k, x in scope.items()) or 'as stated in the question')}</div></div>"
             f"<div><div class='k'>Run date</div><div class='v'>{time.strftime('%Y-%m-%d %H:%M', time.localtime(snap.get('created', time.time())))}</div></div></div>",
             "<div class='banner'>GENERATED FROM CITED EVIDENCE — EVERY STATEMENT TRACES TO A VERBATIM SOURCE QUOTE</div>",
             f"<div class='stamp {'g' if v.get('low', 0) > .5 else 'b' if v.get('high', 1) < .5 else 'm'}'>VERDICT: {_e(v.get('label', '—'))}"
             f"<small>{_p(v.get('p'))} FAVOURABLE · RANGE {_p(v.get('low'))}–{_p(v.get('high'))}</small></div>",
             "<div class='tiles' style='margin-top:6mm'>" + "".join(f"<div><div class='k'>{a}</div><div class='v'>{b}</div><div class='u'>{c}</div></div>" for a, b, c in [
                 ("Sources", len(sources), f"{fetch.get('useful_docs', '—')} useful"), ("Claims", len(claims), f"{ledger.get('clusters', '—')} independent"),
                 ("Evidence", len(bel.get("evidence", [])), "labels weighed"), ("Challenged", len(R.get("challenges", [])), "re-researched"),
                 ("Hearings", len(R.get("court") or {}), "evidence court"), ("Tokens", (R.get("llm_usage") or {}).get("total_tokens", "—"), "LLM use")]) + "</div>",
             "<h3>Document control</h3><table><tr><th>Item</th><th>Value</th></tr>"
             f"<tr><td>Prepared by</td><td>ResearchOps autonomous agent ({_e((R.get('ai') or {}).get('model', ''))})</td></tr>"
             f"<tr><td>Run ID</td><td class='id'>{_e(snap['id'])}</td></tr>"
             f"<tr><td>Citation verification</td><td>{(rep.get('verification') or {}).get('supported', 0)} supported · {(rep.get('verification') or {}).get('partial', 0)} partial · {(rep.get('verification') or {}).get('struck', 0)} struck</td></tr>"
             f"<tr><td>Red-team survival</td><td>{_e((R.get('autopsy') or {}).get('survival', 'pending'))}</td></tr></table>",
             "<div class='note'>Probabilities are computed by a transparent log-odds belief engine from independent evidence clusters; the language model reads and classifies evidence but never sets a number.</div></div>"]

    # ---- executive summary ----
    body = [sec("Executive technical summary", "verdict")]
    for key, title in (("summary", "Principal findings"), ("must_do", "Recommended actions"), ("must_not", "Actions to avoid")):
        if rep.get(key):
            body.append(f"<h3><span class='n2'>{n[0]:02d}.{('summary', 'must_do', 'must_not').index(key) + 1}</span>{title}</h3><ol class='f'>"
                        + "".join(f"<li><span>{_e(it['text'])}{cite(it.get('cites'))}</span></li>" for it in rep[key]) + "</ol>")
    if rep.get("cruxes"):
        body.append("<h3>What would change the verdict</h3><table><tr><th>Kind</th><th>Fact / assumption</th><th>Verdict without it</th><th>Flips?</th></tr>" + "".join(
            f"<tr><td class='id'>{_e(c['kind'])}</td><td>{_e(c.get('text') or claims.get(c.get('claim'), {}).get('text', ''))}</td>"
            f"<td class='mono'>{_p(c['verdict_without'])}</td><td><span class='st {'b' if c['flips'] else 'n'}'>{'YES' if c['flips'] else 'NO'}</span></td></tr>" for c in rep["cruxes"]) + "</table>")

    body.append(sec("Hypotheses and odds", "belief engine"))
    body.append("<table><tr><th>ID</th><th>Hypothesis</th><th>Odds</th><th>Range</th><th>For / against</th></tr>" + "".join(
        f"<tr><td class='id'>{_e(h['id'])}</td><td>{_e(h['text'])}</td><td class='mono {'g' if h.get('p', 0) >= .6 else 'b' if h.get('p', 1) <= .4 else 'm'}'>{_p(h.get('p'))}</td>"
        f"<td class='mono'>{_p(h.get('low'))}–{_p(h.get('high'))}</td><td class='mono'>{h.get('for', 0)} / {h.get('against', 0)}</td></tr>" for h in rep.get("hypotheses", [])) + "</table>")
    if rep.get("assumptions"):
        body.append("<h3>Stated assumptions</h3><table><tr><th>ID</th><th>Assumption</th><th>Likelihood</th></tr>" + "".join(
            f"<tr><td class='id'>{_e(a['id'])}</td><td>{_e(a['text'])}</td><td class='mono'>{_p(a.get('p'))}</td></tr>" for a in rep["assumptions"]) + "</table>")

    if R.get("challenges") or R.get("contradictions"):
        body.append(sec("Challenge and verification", "claim lifecycle"))
        body.append("<table><tr><th>Status</th><th>Claim</th><th>Challenge</th><th>Verifier</th></tr>" + "".join(
            f"<tr><td><span class='st {_cls(r['status'])}'>{_e(r['status'])}</span></td><td>{_e(r['claim_text'])}<div class='cite'>{_e(r['claim'])} · {_e(r['claim_type'])}</div></td>"
            f"<td>{_e(r['argument'])}<div class='cite'>{_e(r['severity'])}</div></td><td>{_e(r['notes'])}</td></tr>" for r in R.get("challenges", [])) + "</table>")
        if R.get("contradictions"):
            body.append("<h3>Numeric contradictions between sources</h3><table><tr><th>Measure</th><th>Subject</th><th>Values</th><th>Claims</th></tr>" + "".join(
                f"<tr><td>{_e(c['measure'])}</td><td>{_e(c['subject'])}</td><td class='mono'>{_e(c['values'])}</td><td class='id'>{_e(c['a'])}, {_e(c['b'])}</td></tr>"
                for c in R["contradictions"][:10]) + "</table>")

    if R.get("court"):
        body.append(sec("Evidence court", "per-claim hearings"))
        for cid, h in R["court"].items():
            body.append(f"<h3><span class='st {_cls(h['ruling'])}'>{_e(h['ruling'])}</span>&nbsp; {_e(h['claim_text'][:140])}</h3><p>{_e(h['rationale'])}</p>"
                        "<table><tr><th>Role</th><th>Argument</th><th>Cites</th><th>Check</th></tr>" + "".join(
                            f"<tr><td class='id'>{_e(t['role'])}</td><td>{_e(t.get('statement', ''))}</td><td class='id'>{_e(', '.join(t['cites']))}</td>"
                            f"<td class='id'>{_e(t['verification'].get('ruling'))}</td></tr>" for t in h["turns"]) + "</table>")

    a = R.get("autopsy") or {}
    if a:
        body.append(sec("Red-team autopsy", "second-order audit"))
        body.append(f"<div class='stamp {_cls(a.get('survival', ''))}'>SURVIVAL: {_e(a.get('survival'))}<small>{_e(a.get('survival_reasoning', ''))}</small></div>")
        body.append("<table style='margin-top:3mm'><tr><th>Severity</th><th>Auditor</th><th>Finding</th><th>Action</th></tr>" + "".join(
            f"<tr><td><span class='st {_cls(f['severity'])}'>{_e(f['severity'])}</span></td><td class='id'>{_e(f['auditor_name'])}</td>"
            f"<td><b>{_e(f['title'])}</b><div>{_e(f['description'])}</div></td><td>{_e(f['recommended_action'])}</td></tr>" for f in a.get("findings", [])) + "</table>")

    ap = R.get("action_plan") or {}
    if ap.get("phases"):
        body.append(sec("Action plan", "phased roadmap"))
        if ap.get("first_step"):
            body.append(f"<div class='stamp m'>FIRST STEP<small>{_e(ap['first_step'])}</small></div>")
        body.append("<table style='margin-top:3mm'><tr><th>Phase</th><th>Actions</th><th>Go / no-go gate</th><th>Risks retired</th></tr>" + "".join(
            f"<tr><td><b>{_e(p['name'])}</b><div class='cite'>{_e(p['horizon'])}</div></td><td>{'<br>'.join('• ' + _e(a) for a in p['actions'])}{cite(p['cites'])}</td>"
            f"<td>{_e(p['gate'])}</td><td>{'<br>'.join(_e(r) for r in p['risks_addressed'])}</td></tr>" for p in ap["phases"]) + "</table>")

    ec = R.get("economics") or {}
    sim = ec.get("simulation") or {}
    if sim.get("base"):
        b, pr = sim["base"], sim["probabilities"]
        body.append(sec("Unit economics", "per customer per month"))
        body.append("<div class='tiles'>" + "".join(f"<div><div class='k'>{a_}</div><div class='v'>{b_}</div><div class='u'>{c_}</div></div>" for a_, b_, c_ in [
            ("Margin", f"{b['margin']:g}", ec.get("currency", "")), ("LTV", f"{b['ltv']:.0f}", ec.get("currency", "")), ("LTV/CAC", b["ltv_cac"], "ratio"),
            ("Payback", b["payback_months"], "months"), ("P(LTV/CAC>3)", _p(pr["ltv_cac_above_3"]), f"{sim['trials']} trials"),
            ("Evidence share", _p(sim["evidence_share"]), "cited params")]) + "</div>")
        body.append("<table><tr><th>Parameter</th><th>Likely</th><th>Range</th><th>Basis</th><th>Note</th></tr>" + "".join(
            f"<tr><td>{_e(k)}</td><td class='mono'>{p['value']:g}</td><td class='mono'>{p['low']:g}–{p['high']:g}</td>"
            f"<td><span class='st {'g' if p['basis'] == 'evidence' else 'm'}'>{_e(p['basis']).upper()}</span>{cite(p['cites'])}</td><td>{_e(p['note'])}</td></tr>"
            for k, p in ec["params"].items()) + "</table>")

    used = rep.get("sources") or []
    if used:
        body.append(sec("Source register", "cited sources"))
        body.append("<table><tr><th>#</th><th>Source</th><th>Type</th><th>Claims</th></tr>" + "".join(
            f"<tr><td class='id'>{i + 1:02d}</td><td>{_e(s.get('title') or s['domain'])}<div class='cite'>{_e(s['url'])}</div></td><td>{_e(s.get('type'))}</td>"
            f"<td class='id'>{_e(', '.join(s.get('claims', [])[:6]))}</td></tr>" for i, s in enumerate(used)) + "</table>")

    return (f"<html><head><meta charset='utf-8'><link rel='stylesheet' href='{FONTS}'><style>{CSS}</style></head><body>"
            + "".join(cover) + "<div class='sheet'>" + "".join(body) + "</div></body></html>")


def _band(doc, rid, where):
    style = "font:500 6.5pt 'IBM Plex Mono',monospace;letter-spacing:.06em;color:#333;width:100%;padding:0 12mm;display:flex;justify-content:space-between;"
    if where == "head":
        return f"<div style=\"{style}\"><span>TECHNICAL DECISION REPORT — RESEARCHOPS</span><span>{doc} · REV A</span></div>"
    return (f"<div style=\"{style}border-top:1pt solid #111;padding-top:2mm;margin:0 12mm;width:calc(100% - 24mm)\">"
            f"<span>RESEARCHOPS · AUTONOMOUS RESEARCH AGENT</span><span>DOC {doc} · RUN {rid}</span>"
            "<span>SHEET <span class='pageNumber'></span> OF <span class='totalPages'></span></span></div>")


async def build_pdf(snap: dict) -> bytes:
    from playwright.async_api import async_playwright
    doc = f"ROPS-{snap['id'][:6].upper()}"
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page()
        await pg.set_content(build_html(snap), wait_until="networkidle")
        pdf = await pg.pdf(format="A4", print_background=True, display_header_footer=True,
                           header_template=_band(doc, snap["id"], "head"), footer_template=_band(doc, snap["id"], "foot"),
                           margin={"top": "16mm", "bottom": "20mm", "left": "12mm", "right": "12mm"})
        await b.close()
    return pdf

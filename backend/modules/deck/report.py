"""Printable decision report (HTML -> PDF via headless Chromium), built only from the run's records."""
import html

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font: 10.5pt/1.5 'Outfit', 'Segoe UI', system-ui, sans-serif; color: #12151a; }
h1 { font-size: 20pt; margin: 0 0 4pt; letter-spacing: -.02em; } h2 { font-size: 13pt; margin: 18pt 0 6pt; border-bottom: 1px solid #e4e7eb; padding-bottom: 3pt; }
.k { color: #8b93a1; font-size: 8.5pt; letter-spacing: .1em; text-transform: uppercase; }
.v { display: inline-block; padding: 4pt 10pt; border-radius: 6pt; background: #eef3ff; color: #2f6bff; font-weight: 600; margin: 6pt 0; }
table { width: 100%; border-collapse: collapse; font-size: 9.5pt; } td, th { text-align: left; padding: 4pt 6pt; border-bottom: 1px solid #eef0f3; vertical-align: top; }
.g { color: #16a34a; } .b { color: #e5484d; } .m { color: #d97706; } .c { color: #8b93a1; font-size: 8.5pt; }
li { margin-bottom: 3pt; }
"""


def _e(s):
    return html.escape(str(s if s is not None else ""))


def _p(x):
    return f"{x * 100:.0f}%" if isinstance(x, (int, float)) else "—"


def build_html(snap: dict) -> str:
    R, claims, sources = snap.get("result", {}), snap.get("claims", {}), snap.get("sources", {})
    rep = R.get("report") or {}
    v = rep.get("verdict") or {}
    cite = lambda cs: f' <span class="c">[{", ".join(_e(c) for c in cs)}]</span>' if cs else ""   # noqa: E731
    out = [f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>",
           f"<div class='k'>ResearchOps decision report</div><h1>{_e(snap.get('query'))}</h1>",
           f"<div class='v'>{_e(v.get('label', '—'))} · {_p(v.get('p'))} favourable ({_p(v.get('low'))}–{_p(v.get('high'))})</div>"]
    if R.get("scope"):
        out.append("<p class='c'>" + " · ".join(f"{_e(k)}: {_e(x)}" for k, x in R["scope"].items()) + "</p>")
    for sec, title in (("summary", "Summary"), ("must_do", "Must do"), ("must_not", "Must not do")):
        if rep.get(sec):
            out.append(f"<h2>{title}</h2><ul>" + "".join(f"<li>{_e(it['text'])}{cite(it.get('cites'))}</li>" for it in rep[sec]) + "</ul>")
    if rep.get("hypotheses"):
        out.append("<h2>Hypotheses</h2><table><tr><th>ID</th><th>Hypothesis</th><th>Odds</th><th>For / against</th></tr>" + "".join(
            f"<tr><td>{_e(h['id'])}</td><td>{_e(h['text'])}</td><td class='{'g' if h.get('p', 0) >= .6 else 'b' if h.get('p', 1) <= .4 else 'm'}'>{_p(h.get('p'))}</td>"
            f"<td>{h.get('for', 0)} / {h.get('against', 0)}</td></tr>" for h in rep["hypotheses"]) + "</table>")
    if rep.get("cruxes"):
        out.append("<h2>What would change the verdict</h2><ul>" + "".join(
            f"<li>{_e(c.get('text') or claims.get(c.get('claim'), {}).get('text', ''))} <span class='c'>(verdict without it: {_p(c['verdict_without'])})</span></li>"
            for c in rep["cruxes"]) + "</ul>")
    if R.get("challenges"):
        out.append("<h2>Challenged claims</h2><table>" + "".join(
            f"<tr><td class='{'g' if r['status'] == 'SUPPORTED' else 'b' if r['status'] in ('CONTRADICTED', 'OUTDATED') else 'm'}'>{_e(r['status'])}</td>"
            f"<td>{_e(r['claim_text'])}<div class='c'>{_e(r['notes'])}</div></td></tr>" for r in R["challenges"]) + "</table>")
    if R.get("court"):
        out.append("<h2>Evidence court</h2><ul>" + "".join(f"<li><b>{_e(h['ruling'])}</b> — {_e(h['claim_text'])}<div class='c'>{_e(h['rationale'])}</div></li>"
                                                          for h in R["court"].values()) + "</ul>")
    a = R.get("autopsy") or {}
    if a:
        out.append(f"<h2>Red-team autopsy: {_e(a.get('survival'))}</h2><ul>" + "".join(
            f"<li><b>{_e(f['severity'])}</b> · {_e(f['auditor_name'])}: {_e(f['title'])}</li>" for f in a.get("findings", [])[:10]) + "</ul>")
    ec = R.get("economics") or {}
    if (ec.get("simulation") or {}).get("base"):
        b, pr = ec["simulation"]["base"], ec["simulation"]["probabilities"]
        out.append("<h2>Unit economics</h2><table>" + "".join(
            f"<tr><td>{_e(k)}</td><td>{p['value']:g} ({p['low']:g}–{p['high']:g}) {_e(ec.get('currency', ''))}</td><td>{_e(p['basis'])}{cite(p['cites'])}</td></tr>"
            for k, p in ec["params"].items()) + f"</table><p>LTV/CAC {b['ltv_cac']} · payback {b['payback_months']} months · "
            f"P(LTV/CAC&gt;3) {_p(pr['ltv_cac_above_3'])} · P(margin&gt;0) {_p(pr['margin_positive'])}</p>")
    used = rep.get("sources") or []
    if used:
        out.append("<h2>Sources</h2><ol>" + "".join(f"<li>{_e(s.get('title') or s['domain'])} — <span class='c'>{_e(s['url'])}</span></li>" for s in used) + "</ol>")
    out.append("</body></html>")
    return "".join(out)


async def build_pdf(snap: dict) -> bytes:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page()
        await pg.set_content(build_html(snap), wait_until="load")
        pdf = await pg.pdf(format="A4", print_background=True)
        await b.close()
    return pdf

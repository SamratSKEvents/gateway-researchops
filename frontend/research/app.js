const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let D = null;          // full run snapshot
let RUN = null;        // run id
let steps = {};        // stage -> {el, events}
const EPI = { verified: "Verified fact", reference: "Reference fact", reported: "Reported (unverified)", opinion: "Opinion" };

// ---------------- landing ----------------
["Should we launch an electric scooter subscription service in Bengaluru?", "Competitors and pricing of cloud kitchens in Mumbai", "Is there demand for a B2B SaaS for dental clinics in India?"].forEach((x) => {
  const b = document.createElement("button"); b.textContent = x; b.type = "button"; b.onclick = () => start(x); $("#examples").append(b);
});
$("#heroSearch").onsubmit = (e) => { e.preventDefault(); start(e.target.q.value); };
$("#topSearch").onsubmit = (e) => { e.preventDefault(); start(e.target.q.value); e.target.q.value = ""; };
$("#inspClose").onclick = () => ($("#inspector").hidden = true);
document.addEventListener("keydown", (e) => e.key === "Escape" && ($("#inspector").hidden = true));

async function loadRecent() {
  const runs = await (await fetch("/api/research/runs")).json();
  $("#recentList").innerHTML = runs.map((r) => `<li><a href="#run=${r.id}">${esc(r.query)} <small>${r.status} · ${new Date(r.created * 1000).toLocaleString()}</small></a></li>`).join("") || `<li class="muted" style="padding:8px">None yet</li>`;
}
loadRecent();
Graph.mount($("#panel-graph"));

async function start(q) {
  q = (q || "").trim(); if (!q) return;
  const v = (id) => ($(id)?.value || "").trim() || null;    // optional constraints; the interview skips what is given here
  const body = { query: q, geography: v("#cGeo"), scope: v("#cScope"), time_range: v("#cTime"), depth: v("#cDepth") };
  const r = await fetch("/api/research", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const { id } = await r.json();
  location.hash = `run=${id}`;
}

window.addEventListener("hashchange", route);
route();
document.addEventListener("click", (e) => { const d = $(".recent"); if (d?.open && !d.contains(e.target)) d.open = false; });
function route() {
  const d = $(".recent"); if (d) d.open = false;
  const m = location.hash.match(/run=(\w+)/);
  if (!m) { document.body.classList.remove("is-running"); $("#landing").hidden = false; $("#runView").hidden = true; $("#topSearch").hidden = true; return; }
  const tab = (location.hash.match(/tab=(\w+)/) || [])[1];
  if (m[1] !== RUN) openRun(m[1]).then(() => tab && showTab(tab)); else if (tab) showTab(tab);
}

// ---------------- run view ----------------
async function openRun(id) {
  RUN = id; D = null; steps = {};
  $("#landing").hidden = true; $("#runView").hidden = false; $("#topSearch").hidden = false;
  $("#timeline").innerHTML = ""; $("#brief").innerHTML = ""; $("#briefWaiting").hidden = false;
  $("#verdict").innerHTML = ""; $("#trial").innerHTML = ""; $("#verdictWaiting").hidden = false; $("#hearing").hidden = true; $("#meter").hidden = true;
  ["claims", "sources"].forEach((x) => ($("#" + x).innerHTML = ""));
  const snap = await (await fetch(`/api/research/runs/${id}`)).json();
  Graph.reset(snap.query); showTab("graph");
  $("#runQuery").textContent = `Query: ${snap.query}`;
  $("#runTitle").textContent = "Researching…";
  $("#goalForm").hidden = snap.status !== "running";
  document.body.classList.toggle("is-running", snap.status === "running");
  if (snap.status === "running") {
    if (snap.pending) setTimeout(() => showPending(snap.pending), 0);
    const es = new EventSource(`/api/research/runs/${id}/events`);
    es.onmessage = (m) => { if (RUN === id) onEvent(JSON.parse(m.data)); };
    es.addEventListener("end", async () => { es.close(); if (RUN === id) finish(await (await fetch(`/api/research/runs/${id}`)).json()); });
    es.onerror = () => es.close();
  } else {
    snap.events.forEach(onEvent);
    finish(snap);
  }
}

function onEvent(ev) {
  Graph.ev(ev);
  typeof Views !== "undefined" && Views.step(ev);
  if (ev.stage === "await") {   // replayed history may contain answered questions: ask the server what is pending now
    if (ev.status === "waiting" && D === null) fetch(`/api/research/runs/${RUN}`).then((r) => r.json()).then((x) => x.pending ? showPending(x.pending) : ($("#hearing").hidden = true));
    else $("#hearing").hidden = true;
    return addStep({ ...ev, stage: "await" + ev.i });
  }
  if (ev.stage === "belief" && ev.status === "done" && ev.data?.result) meter(ev.data.result);
  if (ev.stage === "complete") {
    document.body.classList.remove("is-running");
    $("#goalForm").hidden = true; $("#hearing").hidden = true;
    loadHealth();
    $("#runTitle").textContent = ev.status === "done" ? "Research completed" : "Research stopped";
    addStep(ev);
    return;
  }
  if (ev.status === "progress") {
    const s = steps[ev.stage]; if (!s) return;
    s.subs.push(ev);
    const li = document.createElement("li");
    li.textContent = `${ev.title} — ${ev.summary}`;
    if (/fail/i.test(ev.title) || ev.data?.ok === false) li.className = "bad";
    li.onclick = (e) => { e.stopPropagation(); inspectEvent(ev); };
    s.el.querySelector(".subs").append(li);
    bumpCounters(ev);
    return;
  }
  addStep(ev);
  bumpCounters(ev);
}

function addStep(ev) {
  let s = steps[ev.stage];
  if (!s || (ev.status === "running" && s.ev.status !== "running")) {   // a stage re-runs in every research round: new log entry
    const el = document.createElement("li");
    el.className = "step";
    el.innerHTML = `<h4><span></span><time></time></h4><p></p><ul class="subs"></ul>`;
    const step = s = steps[ev.stage] = { el, subs: [], ev };
    el.onclick = () => inspectStage(step);
    $("#timeline").append(el);
  }
  s.ev = ev;
  s.el.className = `step ${ev.status}`;
  s.el.querySelector("span").textContent = ev.title;
  s.el.querySelector("time").textContent = `${ev.t}s`;
  s.el.querySelector("p").textContent = ev.status === "running" ? "working…" : ev.summary;
  s.el.scrollIntoView({ block: "nearest" });
}

const C = { searches: 0, results: 0, read: 0, failed: 0 };
function bumpCounters(ev) {
  if (ev.stage === "search" && ev.status === "progress") { C.searches++; C.results += ev.data?.results?.length || 0; }
  if (ev.stage === "fetch" && ev.status === "progress") ev.title.startsWith("Read") ? C.read++ : C.failed++;
  if (ev.i === 0) Object.keys(C).forEach((k) => (C[k] = 0));
  $("#counters").innerHTML = [["searches", C.searches], ["results", C.results], ["pages read", C.read], ["unreadable", C.failed]]
    .map(([k, v]) => `<div><b>${v}</b><span>${k}</span></div>`).join("");
}

function finish(snap) {
  D = snap;
  typeof Views !== "undefined" && Views.done(snap);
  Graph.enrich(snap);
  loadRecent();
  if (!D.result?.plan) { $("#brief").innerHTML = `<div class="waiting">Research did not complete. Inspect the failed step in the log.</div>`; $("#briefWaiting").hidden = true; return; }
  $("#runTitle").textContent = D.result.plan.subject;
  $("#briefWaiting").hidden = true;
  renderVerdict(); renderTrial(); renderBrief(); renderClaims(); renderSources();
}

// ---------------- tabs ----------------
$("#tabs").onclick = (e) => e.target.dataset.tab && showTab(e.target.dataset.tab);
function showTab(t) {
  document.querySelectorAll(".tabs button[data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  const more = $("#moreTabs"); if (more) { more.value = [...more.options].some((o) => o.value === t) ? t : ""; more.classList.toggle("on", !!more.value); }
  document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== "panel-" + t));
  if (t === "graph") requestAnimationFrame(() => Graph.refresh());   // cards must be measured while visible
  if (typeof Views !== "undefined" && Views[t]) Views[t]();      // lazy views fetch their data when opened
}

// ---------------- helpers ----------------
const S = (id) => D.sources[id];
function claimHTML(cid, opts = {}) {
  const c = D.claims[cid]; if (!c) return "";
  const s = S(c.source);
  const kind = c.kind === "risk" ? `<span class="badge b-warning">risk</span>` : c.kind === "opportunity" ? `<span class="badge b-reported">opportunity</span>` : "";
  return `<div class="claim" data-claim="${cid}"><p class="q">${opts.quote === false ? "" : "“"}${esc(c.text)}${opts.quote === false ? "" : "”"}</p>
    <div class="badges"><span class="badge b-${c.epistemic}">${EPI[c.epistemic]}</span>${kind}
    ${c.freshness != null && c.freshness < 0.5 ? `<span class="badge b-warning" title="freshness weight ${c.freshness}">stale</span>` : ""}
    ${c.cluster_domains > 1 ? `<span class="badge b-reference" title="same statement found on ${c.cluster_domains} domains">${c.cluster_domains} domains</span>` : ""}
    <span class="src">${esc(s.type_label)} · ${esc(s.domain)}${c.year ? " · " + c.year : " · undated"}${c.snippet ? " · search snippet" : ""}</span></div></div>`;
}
document.addEventListener("click", (e) => {
  const c = e.target.closest("[data-claim]"); if (c) { e.stopPropagation(); return inspectClaim(c.dataset.claim); }
  const s = e.target.closest("[data-source]"); if (s) { e.stopPropagation(); return inspectSource(s.dataset.source); }
});
function openInspector(html) { $("#inspBody").innerHTML = html; $("#inspector").hidden = false; $("#inspector").scrollTop = 0; }
function table(rows, cols, rowAttr) {
  if (!rows?.length) return `<p class="muted">Nothing.</p>`;
  cols = cols || Object.keys(rows[0]).filter((k) => typeof rows[0][k] !== "object" || rows[0][k] === null || Array.isArray(rows[0][k]));
  return `<div style="overflow-x:auto"><table><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) =>
    `<tr ${rowAttr ? rowAttr(r) : ""}>${cols.map((c) => `<td>${fmt(r[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function fmt(v) {
  if (v == null) return `<span class="muted">—</span>`;
  if (Array.isArray(v)) return esc(v.map((x) => (typeof x === "object" ? JSON.stringify(x) : x)).join(", "));
  if (typeof v === "object") return `<span class="mono">${esc(JSON.stringify(v).slice(0, 200))}</span>`;
  const s = String(v);
  if (/^https?:\/\//.test(s)) return `<a href="${esc(s)}" target="_blank" rel="noopener">${esc(s.replace(/^https?:\/\/(www\.)?/, "").slice(0, 60))}</a>`;
  return esc(s);
}

// ---------------- stage inspection ----------------
function inspectStage(s) {
  const ev = s.ev, stage = ev.stage, d = ev.data || {};
  let body = "";
  if (ev.status === "failed") body += `<h4>Error</h4><pre class="text">${esc(d.traceback || ev.summary)}</pre>`;
  else if (stage === "search") body += `<h4>Queries (click to see results)</h4>` + s.subs.map((x, i) =>
    `<div class="edge" data-sub="${i}"><b>${esc(x.data.query)}</b><div class="why">${esc(x.data.question)} — ${esc(x.summary)}</div></div>`).join("");
  else if (stage === "fetch") body += table(d.sources, ["id", "url", "type", "status", "chars", "error"], (r) => `class="click" data-source="${r.id}"`);
  else body += renderData(d);
  openInspector(`<p class="eyebrow">Research step · ${esc(ev.status)} · t=${ev.t}s</p><h2>${esc(ev.title)}</h2><p>${esc(ev.summary)}</p>${body}`);
  document.querySelectorAll("[data-sub]").forEach((el) => (el.onclick = () => inspectEvent(s.subs[+el.dataset.sub])));
}
function renderData(d) {
  let h = "";
  for (const [k, v] of Object.entries(d || {})) {
    h += `<h4>${esc(k.replace(/_/g, " "))}${Array.isArray(v) ? ` (${v.length})` : ""}</h4>`;
    if (Array.isArray(v) && v.length && typeof v[0] === "object") h += table(v.slice(0, 300));
    else if (Array.isArray(v)) h += `<p>${esc(v.join(" · "))}</p>`;
    else if (typeof v === "object" && v) h += `<pre class="json">${esc(JSON.stringify(v, null, 2).slice(0, 15000))}</pre>`;
    else h += `<pre class="text">${esc(String(v).slice(0, 15000))}</pre>`;
  }
  return h || `<p class="muted">No data payload.</p>`;
}
function inspectEvent(ev) {
  const d = ev.data || {};
  let body = "";
  if (ev.stage === "search") {
    const trail = (d.attempts || []).map((a) => `<div class="prov"><span>${esc(a.provider)}</span><span class="st ${a.status}">${esc(a.status)}${a.generic ? " · generic" : ""}</span><span class="muted">${a.n} results ${a.ms ? `· ${a.ms} ms` : ""} ${esc(a.note || "")}</span></div>`).join("");
    body = (trail ? `<h4>Provider attempts (in order)</h4>${trail}` : "") + (d.provider ? `<p class="muted">Used: <b>${esc(d.provider)}</b>${d.cached ? " · served from cache (real earlier result)" : ""}${d.specific === false ? " · results not query-specific" : ""}</p>` : "") +
      (d.ok === false && !(d.results || []).length ? `<p class="note">No results for this query${d.error ? ": " + esc(d.error) : ""}.</p>` : "") +
      `<h4>Results (${(d.results || []).length})</h4>` +
      (d.results || []).map((r) => `<div class="edge"><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a><div class="why">${esc(r.snippet)}</div><div class="src">${esc(r.url)}${r.engines ? " · " + esc(r.engines.join(", ")) : ""}${r.text ? ` · full text ${r.text.length.toLocaleString()} chars` : ""}</div></div>`).join("");
    const down = Object.entries(d.engines_down || {});
    body = `<p class="muted">Research question: ${esc(d.question)}</p>` +
      (down.length ? `<p class="note">Search engines unavailable for this query (reported by SearXNG): ${esc(down.map(([e, why]) => `${e} (${why})`).join(", "))}</p>` : "") + body;
  } else if (ev.stage === "fetch") {
    body = `<p><a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.url)}</a></p>` + (d.preview ? `<h4>Extracted text (first 1,500 chars)</h4><pre class="text">${esc(d.preview)}</pre>` : "") +
      (D ? `<p><button class="chip" data-source="${d.source}">See claims extracted from this source</button></p>` : "");
  } else body = renderData(d);
  openInspector(`<p class="eyebrow">${esc(ev.stage)} · t=${ev.t}s</p><h2>${esc(ev.title)}</h2><p>${esc(ev.summary)}</p>${body}`);
}

// ---------------- entity inspectors ----------------
function inspectClaim(cid) {
  if (!D) return openInspector(`<p class="eyebrow">Claim ${esc(cid)}</p><p>Full claim details are available when the run completes.</p>`);
  const c = D.claims[cid], s = S(c.source);
  const task = (id) => D.result.plan.tasks.find((t) => t.id === id)?.question || id;
  openInspector(`<p class="eyebrow">Claim ${cid}</p><h2 style="font-size:20px">“${esc(c.text)}”</h2>
   <div class="badges"><span class="badge b-${c.epistemic}">${EPI[c.epistemic]}</span><span class="badge b-reported">${esc(c.kind)}</span></div>
   <h4>Why this classification</h4><p class="note">${epiWhy(c, s)}</p>
   <h4>Source</h4><div class="edge" data-source="${s.id}"><b>${esc(s.title || s.domain)}</b><div class="why">${esc(s.type_label)} · authority weight ${s.authority}</div><div class="src">${esc(s.url)}</div></div>
   <h4>Research tasks</h4>${c.tasks.map((t) => `<p class="note">${esc(t)} · ${esc(task(t))}</p>`).join("") || `<p class="muted">Not linked to a task (mentions the subject).</p>`}
   <h4>Ledger</h4><dl class="kv">${[["date", c.year || "undated"], ["freshness weight", c.freshness], ["independence cluster", c.cluster],
      ["domains saying the same", c.cluster_domains]].map(([k, v]) => `<dt>${k}</dt><dd>${fmt(v)}</dd>`).join("")}</dl>
   ${stanceHTML(cid)}
   <h4>Signals detected</h4><dl class="kv">${[["prices", c.prices], ["sentiment", c.sentiment], ["from search snippet only", !!c.snippet]]
      .map(([k, v]) => `<dt>${k}</dt><dd>${fmt(Array.isArray(v) && !v.length ? null : v)}</dd>`).join("")}</dl>`);
}
function epiWhy(c, s) {
  if (c.epistemic === "verified") return `Factual statement from ${esc(s.type_label.toLowerCase())} (${esc(s.domain)}).`;
  if (c.epistemic === "reference") return `Factual statement from an encyclopedia/reference source.`;
  if (c.epistemic === "reported") return `Statement from a ${esc(s.type_label.toLowerCase())} — not independently verified.`;
  return `Evaluative or first-person language from a ${esc(s.type_label.toLowerCase())}. It reflects one writer's view, not a fact.`;
}
function inspectSource(sid) {
  const s = S(sid);
  const cl = Object.values(D.claims).filter((c) => c.source === sid);
  openInspector(`<p class="eyebrow">Source ${sid} · ${esc(s.type_label)}</p><h2>${esc(s.title || s.domain)}</h2>
   <p><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a></p>
   <dl class="kv"><dt>type</dt><dd>${esc(s.type_label)} (authority ${s.authority})</dd><dt>status</dt><dd>${esc(s.status)}${s.error ? " — " + esc(s.error) : ""}</dd>
   <dt>found by</dt><dd>${esc((s.queries || []).join(" · "))}</dd><dt>text</dt><dd>${s.chars ? s.chars.toLocaleString() + " chars" : "—"}</dd></dl>
   ${s.snippets?.length ? `<h4>Search snippets</h4>${s.snippets.map((x) => `<p class="note">${esc(x)}</p>`).join("")}` : ""}
   <h4>${cl.length} claims extracted</h4>${cl.slice(0, 80).map((c) => claimHTML(c.id)).join("")}
   ${D.docs?.[sid] ? `<h4>Extracted text</h4><pre class="text">${esc(D.docs[sid].slice(0, 12000))}</pre>` : ""}`);
}

// ---------------- brief ----------------
function section(title, how, inner) { return inner ? `<section class="b"><h3>${title}</h3><p class="how">${how}</p>${inner}</section>` : ""; }
function best(pred, n) {  // highest-authority claims first
  return Object.values(D.claims).filter(pred).sort((a, b) => S(b.source).authority - S(a.source).authority || a.text.length - b.text.length).slice(0, n).map((c) => c.id);
}
function renderBrief() {
  const R = D.result, plan = R.plan;
  const synthHTML = `<p class="note">Findings per research task, straight from the evidence ledger (no model prose). The decision itself is on the Verdict tab.</p>`;
  const nDocs = Object.keys(D.docs || {}).length;
  let h = `<div class="b-hero"><div><p class="eyebrow">Research question</p><h1>${esc(D.query)}</h1>
    <div class="where">subject: ${esc(plan.subject)} · ${esc(plan.how)}</div>${synthHTML}</div>
    <div><dl class="facts"><dt>tasks</dt><dd>${plan.tasks.length}</dd><dt>documents read</dt><dd>${nDocs}</dd>
    <dt>statements</dt><dd>${Object.keys(D.claims).length}</dd><dt>domains</dt><dd>${new Set(Object.values(D.sources).filter((s) => s.n_claims).map((s) => s.domain)).size}</dd>
    ${plan.keywords.length ? `<dt>keywords</dt><dd>${esc(plan.keywords.join(", "))}</dd>` : ""}</dl></div></div>`;
  h += plan.tasks.map((t) => section(`${esc(t.id)} · ${esc(t.question)}`, `Search: “${esc(t.q)}”. Highest-authority statements linked to this task.`,
    best((c) => c.tasks.includes(t.id), 8).map((c) => claimHTML(c)).join(""))).join("");
  h += `<div class="cols">` +
    section("Opportunities", "Statements with growth / demand / gap language, ranked by source authority.", best((c) => c.kind === "opportunity", 10).map((c) => claimHTML(c)).join("")) +
    section("Risks", "Statements with risk / failure / regulation language, ranked by source authority.", best((c) => c.kind === "risk", 10).map((c) => claimHTML(c)).join("")) + `</div>`;
  const priced = best((c) => c.prices?.length, 20);
  h += section("Prices mentioned", "Every statement containing a currency amount. Check the source before relying on a number.",
    priced.length ? table(priced.map((c) => ({ price: D.claims[c].prices.join(", "), statement: D.claims[c].text.slice(0, 140), source: S(D.claims[c].source).domain, id: c })), ["price", "statement", "source"], (r) => `class="click" data-claim="${r.id}"`) : "");
  $("#brief").innerHTML = h;
}

function renderClaims() {
  const all = Object.values(D.claims);
  $("#claims").innerHTML = `<div class="tablewrap"><div class="tools"><input placeholder="Search statements…" id="claimsF">
    <select id="claimsE"><option value="">All epistemic types</option>${Object.entries(EPI).filter(([k]) => k !== "inference").map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
    <select id="claimsK"><option value="">All kinds</option><option>fact</option><option>risk</option><option>opportunity</option><option>opinion</option></select>
    <span class="muted" id="claimsN"></span></div><div id="claimsList"></div></div>`;
  const draw = () => {
    const f = $("#claimsF").value.toLowerCase(), e = $("#claimsE").value, k = $("#claimsK").value;
    const rows = all.filter((c) => (!e || c.epistemic === e) && (!k || c.kind === k) && (!f || c.text.toLowerCase().includes(f)));
    $("#claimsN").textContent = `${rows.length} of ${all.length} statements (showing first 200)`;
    $("#claimsList").innerHTML = rows.slice(0, 200).map((c) => claimHTML(c.id)).join("");
  };
  ["claimsF", "claimsE", "claimsK"].forEach((id) => ($("#" + id).oninput = draw)); draw();
}
function renderSources() {
  const rows = Object.values(D.sources).filter((s) => s.n_claims > 0 || s.status !== "registered").sort((a, b) => b.n_claims - a.n_claims)
    .map((s) => ({ id: s.id, source: s.title?.slice(0, 70) || s.domain, domain: s.domain, type: s.type_label, authority: s.authority, status: s.status, claims: s.n_claims }));
  $("#sources").innerHTML = `<div class="tablewrap"><p class="muted">${rows.length} sources. "snippet" = only the search-result snippet was used (page not read). Authority weights are fixed per source type and shown so you can judge them.</p>
    ${table(rows, ["source", "domain", "type", "authority", "status", "claims"], (r) => `class="click" data-source="${r.id}"`)}</div>`;
}

// ---------------- research-source health badge ----------------
async function loadHealth() {
  try {
    const h = await (await fetch("/api/research/health")).json();
    const b = $("#healthBadge");
    const cls = h.label.split(" ")[0];
    b.className = `health ${cls}`;
    b.textContent = `SEARCH: ${h.label}`;
    b.onclick = () => showHealth(h);
  } catch (e) { $("#healthBadge").textContent = "SEARCH: backend unreachable"; }
}
function showHealth(h) {
  const rows = Object.entries(h.providers).sort().map(([n, p]) => `<div class="prov"><span>${esc(n)}</span><span class="st ${p.status}">${esc(p.status)}</span>
    <span class="muted">${esc(p.reason || "")}${p.cooling_down_s ? ` · cooling down ${p.cooling_down_s}s` : ""}${p.last_ok ? ` · last ok ${new Date(p.last_ok * 1000).toLocaleTimeString()}` : ""}</span></div>`).join("");
  openInspector(`<p class="eyebrow">Research sources</p><h2>SEARCH: ${esc(h.label)}</h2><p>${esc(h.why)}</p>
    <p class="muted" style="font-size:12px">States come only from real calls or real probes. Cache: ${h.cache.search} search responses, ${h.cache.pages} pages (all real earlier retrievals).</p>
    <button class="chip" id="probe">Probe all providers now (real requests)</button>
    <h4>Providers</h4>${rows || '<p class="muted">No provider used yet — run a probe.</p>'}
    `);
  $("#probe").onclick = async (e) => {
    e.target.textContent = "Probing… (a few seconds)"; e.target.disabled = true;
    const r = await (await fetch("/api/research/health/probe", { method: "POST" })).json();
    showHealth(r); loadHealth();
  };
}
loadHealth();
setInterval(loadHealth, 60000);

// ---------------- hearing: the run waits for the user ----------------
function showPending(p) {
  const H = $("#hearing"); H.hidden = false;
  const send = async (answer) => {
    H.innerHTML = `<p class="muted">Sent — continuing…</p>`;
    await fetch(`/api/research/runs/${RUN}/reply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer }) });
    setTimeout(() => (H.hidden = true), 800);
  };
  if (p.kind === "hypotheses") {
    H.innerHTML = `<p class="eyebrow">Your input is needed · ${esc(p.title)}</p><h3>${esc(p.decision)}</h3>
      <p class="muted">Starting hypotheses and how likely each seems before research. Edit, untick to drop, then confirm.</p>
      ${p.hypotheses.map((h) => `<div class="hyp-edit" data-id="${h.id}"><input type="checkbox" checked aria-label="keep ${h.id}">
        <input class="t" value="${esc(h.text)}" aria-label="hypothesis text"><span class="fav ${h.favours > 0 ? "good" : "bad"}">${h.favours > 0 ? "good if true" : "bad if true"}</span>
        <input type="range" min="5" max="95" value="${Math.round(h.prior * 100)}" aria-label="prior"><b>${Math.round(h.prior * 100)}%</b></div>`).join("")}
      ${p.assumptions.length ? `<p class="muted" style="margin-top:12px">Assumptions inferred from your goal (adjustable later as what-if sliders): ${p.assumptions.map((a) => esc(a.text)).join(" · ")}</p>` : ""}
      <button class="primary" id="hConfirm">Confirm and start research</button>`;
    H.querySelectorAll(".hyp-edit input[type=range]").forEach((r) => (r.oninput = () => (r.nextElementSibling.textContent = r.value + "%")));
    $("#hConfirm").onclick = () => send({ hypotheses: [...H.querySelectorAll(".hyp-edit")].filter((d) => d.querySelector("[type=checkbox]").checked)
      .map((d) => ({ id: d.dataset.id, text: d.querySelector(".t").value, prior: +d.querySelector("[type=range]").value / 100 })) });
    return;
  }
  H.innerHTML = `<p class="eyebrow">Your input is needed · ${esc(p.title)}</p><h3>${esc(p.question)}</h3>
    ${p.hint ? `<p class="muted">${esc(p.hint)}</p>` : ""}
    <form id="hForm"><textarea name="a" rows="2" placeholder="Your answer…" required></textarea>
    <div class="row"><button class="primary">Answer</button>${p.kind === "interview" ? `<button type="button" id="hSkip">Skip — use stated assumptions</button>` : `<button type="button" id="hSkip">Unsure</button>`}</div></form>`;
  $("#hForm").onsubmit = (e) => { e.preventDefault(); send(e.target.a.value); };
  $("#hSkip").onclick = () => send(p.kind === "interview" ? "skip" : "unsure");
  H.querySelector("textarea").focus();
}
$("#goalForm").onsubmit = async (e) => {
  e.preventDefault(); const g = e.target.g.value.trim(); if (!g) return;
  const r = await fetch(`/api/research/runs/${RUN}/goal`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal: g }) });
  e.target.g.value = ""; e.target.g.placeholder = r.ok ? "Goal updated — hypotheses will be rebuilt at the next checkpoint" : "Run is not live";
};

// ---------------- verdict ----------------
const pct = (x) => `${Math.round(x * 100)}%`;
function meter(r) {
  const m = $("#meter"); m.hidden = false;
  m.innerHTML = `<div class="gauge"><i style="left:${r.low * 100}%;width:${(r.high - r.low) * 100}%"></i><b style="left:${r.verdict * 100}%"></b></div>
    <span>verdict so far <b>${pct(r.verdict)}</b> favourable (${pct(r.low)}–${pct(r.high)})</span>`;
}
const RULING = { supported: "b-reference", partial: "b-opinion", unsupported: "b-warning", unchecked: "b-reported", "no citation": "b-reported" };
const ruling = (r) => r ? `<span class="badge ${RULING[r.ruling] || "b-reported"}" title="${esc(r.reason || "")}">${esc(r.ruling)}</span>` : "";
const cites = (ids) => (ids || []).map((c) => D.claims[c] ? `<span class="cite" data-claim="${c}">[${c}]</span>` : "").join(" ");
function stanceHTML(cid) {
  const E = D.result.belief?.evidence?.filter((e) => e.claim === cid) || [];
  const H = Object.fromEntries((D.result.belief?.hypotheses || []).map((h) => [h.id, h.text]));
  return E.length ? `<h4>Weighed as evidence</h4>${E.map((e) => `<p class="note">${e.stance > 0 ? "supports" : "opposes"} ${esc(e.hypothesis)} “${esc(H[e.hypothesis])}” · strength ${e.strength} · reliability ${e.reliability} · freshness ${e.freshness}</p>`).join("")}` : "";
}
function hypRows(res) {
  const byId = Object.fromEntries(res.hypotheses.map((h) => [h.id, h]));
  return D.result.report.hypotheses.map((h) => {
    const b = byId[h.id];
    return `<div class="hyp"><div class="hyp-t"><b>${esc(h.id)}</b> ${esc(h.text)} <span class="fav ${h.favours > 0 ? "good" : "bad"}">${h.favours > 0 ? "good if true" : "bad if true"}</span></div>
      <div class="gauge small"><i style="left:${b.low * 100}%;width:${(b.high - b.low) * 100}%"></i><b style="left:${b.p * 100}%"></b><u style="left:${h.prior * 100}%" title="prior ${pct(h.prior)}"></u></div>
      <div class="hyp-n"><b>${pct(b.p)}</b> <span class="muted">${pct(b.low)}–${pct(b.high)} · prior ${pct(h.prior)} · ${b.clusters} independent clusters (${b.for} for / ${b.against} against)</span></div></div>`;
  }).join("");
}
function cruxHTML(list) {
  return list.map((c) => `<div class="edge" ${c.kind === "evidence" ? `data-claim="${c.id}"` : ""}><b>${c.flips ? "Would FLIP the verdict" : "Moves the verdict"} ${pct(Math.abs(c.delta))}</b>
    <div class="why">${c.kind === "evidence" ? `if this evidence is wrong: “${esc(D.claims[c.claim]?.text || c.claim)}”` : `if this assumption is reversed: “${esc(c.text)}”`} → ${pct(c.verdict_without)}</div></div>`).join("");
}
function renderVerdict() {
  const R = D.result.report;
  $("#verdictWaiting").hidden = true;
  if (!R) { $("#verdict").innerHTML = `<div class="waiting">No verdict for this run (it stopped early or was made by an older version). See the Findings tab and the log.</div>`; return; }
  const v = R.verdict, ver = R.verification, A = R.assumptions || [];
  const item = (it) => `<li>${esc(it.text)} ${cites(it.cites)} ${ruling({ ruling: it.ruling, reason: it.ruling_reason })}</li>`;
  let h = `<div class="v-hero"><div><p class="eyebrow">Decision</p><h1>${esc(R.decision)}</h1>
      <p class="muted">Question: ${esc(D.query)}</p>
      ${D.result.goal ? `<details><summary class="muted">Your goal (from the interview)</summary><pre class="text">${esc(D.result.goal.goal)}</pre></details>` : ""}</div>
    <div class="v-num" id="vNum"><p class="eyebrow">Verdict</p><div class="big">${pct(v.p)}</div><div class="lbl">${esc(v.label)}</div>
      <div class="muted">range ${pct(v.low)}–${pct(v.high)}</div>
      <div class="ver"><b>${ver.supported}</b> supported · <b>${ver.partial}</b> partial · <b>${ver.struck}</b> struck${ver.unchecked ? ` · ${ver.unchecked} unchecked` : ""}<br><span class="muted">citation verifier, ${ver.statements} statements</span></div></div></div>`;
  h += section("Summary", "Written by the model only from ledger evidence; every sentence was checked by the independent verifier. Click a citation to see its verbatim quote.",
    R.summary.length ? `<ul class="prose">${R.summary.map(item).join("")}</ul>` : `<p class="muted">No verified summary sentences.</p>`);
  h += `<div class="cols">` + section("Must do", "Actions the evidence justifies.", R.must_do.length ? `<ul class="prose">${R.must_do.map(item).join("")}</ul>` : `<p class="muted">None survived verification.</p>`)
    + section("Must not do", "Actions the evidence argues against.", R.must_not.length ? `<ul class="prose">${R.must_not.map(item).join("")}</ul>` : `<p class="muted">None survived verification.</p>`) + `</div>`;
  h += section("Hypotheses", "Probabilities are computed by transparent code (log-odds): each independent evidence cluster shifts a hypothesis by its stance × strength × source reliability × freshness; repeated copies count once and same-direction evidence saturates. Bar = range; tick = prior.",
    `<div id="hypRows">${hypRows({ hypotheses: R.hypotheses })}</div>`);
  if (A.length) h += section("What if?", "The assumptions inferred from your goal. Move a slider: the verdict is recomputed instantly from the same evidence, no new research.",
    A.map((a) => `<div class="whatif"><label>${esc(a.text)} <span class="muted">(affects ${esc(a.hypothesis)}${a.answered ? `; you answered “${esc(a.answered)}”` : ""})</span></label>
      <input type="range" min="1" max="99" value="${Math.round(a.p * 100)}" data-a="${a.id}"><b>${pct(a.p)}</b></div>`).join(""));
  h += section("Cruxes", "The facts and assumptions that move the verdict most. Check these first.", `<div id="cruxes">${cruxHTML(R.cruxes)}</div>`);
  h += section("Where sources disagree", "Numeric contradictions between independent sources. Kept side by side, never averaged.",
    R.contradictions.length ? R.contradictions.map((c) => `<div class="conflict"><p class="eyebrow">${esc(c.measure)} · ${esc(c.subject)}</p><div class="cols">${claimHTML(c.a)}${claimHTML(c.b)}</div></div>`).join("") : `<p class="muted">No numeric contradictions detected.</p>`);
  h += section("What we could not verify", "Gaps are reported, not guessed. They widen the verdict's range.",
    R.gaps.length ? `<ul class="prose">${R.gaps.map((g) => `<li>${esc(g.text)}</li>`).join("")}</ul>` : `<p class="muted">No major gaps.</p>`);
  if (R.struck.length) h += section("Struck by the verifier", "Statements the model wrote that their cited quotes did not support. Shown for transparency, excluded from the report.",
    `<ul class="prose struck">${R.struck.map((x) => `<li>${esc(x.text)} ${cites(x.cites)} <span class="muted">— ${esc(x.reason)}</span></li>`).join("")}</ul>`);
  h += section("Sources", "Every source cited above, with the claims taken from it.",
    table(R.sources.map((s) => ({ ...s, n: s.claims.length })), ["title", "domain", "type", "n", "url"], (r) => `class="click" data-source="${r.id}"`));
  $("#verdict").innerHTML = h;
  let t;
  document.querySelectorAll(".whatif input").forEach((r) => (r.oninput = () => {
    r.nextElementSibling.textContent = r.value + "%";
    clearTimeout(t); t = setTimeout(whatIf, 150);
  }));
}
async function whatIf() {
  const values = Object.fromEntries([...document.querySelectorAll(".whatif input")].map((r) => [r.dataset.a, +r.value / 100]));
  const r = await (await fetch(`/api/research/runs/${RUN}/whatif`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values }) })).json();
  const v = r.result, R = D.result.report;
  $("#vNum .big").textContent = pct(v.verdict);
  $("#vNum .lbl").textContent = v.low > 0.5 ? "favourable" : v.high < 0.5 ? "unfavourable" : v.verdict >= 0.5 ? "leaning favourable (uncertain)" : "leaning unfavourable (uncertain)";
  $("#vNum .muted").textContent = `range ${pct(v.low)}–${pct(v.high)} · what-if (was ${pct(R.verdict.p)})`;
  $("#hypRows").innerHTML = hypRows(v);
  $("#cruxes").innerHTML = cruxHTML(r.cruxes);
}

// ---------------- trial ----------------
function renderTrial() {
  const T = D.result.trial;
  if (!T) { $("#trial").innerHTML = `<div class="waiting">No trial for this run.</div>`; return; }
  $("#trial").innerHTML = `<div class="tablewrap"><p class="muted">Each speaker may only argue with evidence exhibits from the ledger. The citation verifier (clerk) then rules on every point.</p>
    <div class="court">${T.panel.map((r) => `<section class="speaker ${r.role}"><h3>${esc(r.title)}</h3>
      ${r.error ? `<p class="note">Did not testify: ${esc(r.error)}</p>` : ""}
      <ol>${r.points.map((p) => `<li>${esc(p.point)} ${cites(p.cites)} ${ruling(p.ruling)}${p.invalid_cites?.length ? ` <span class="muted" title="cited ids not in the ledger were removed">(${p.invalid_cites.length} invalid citation removed)</span>` : ""}</li>`).join("")}</ol></section>`).join("")}</div></div>`;
}

// Lazy views over the run API + progress stepper, theme and log toggles. Each view fetches its data when its tab opens.
const Views = (() => {
  const API = (p) => /report\.pdf|deck\.pptx/.test(p) ? `demo/${RUN}/${p.split('?')[0].slice(1)}` : `/api/research/runs/${RUN}${p}`;
  const get = async (p) => (await fetch(API(p))).json();
  const post = async (p, body) => (await fetch(API(p), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })).json();
  const P = (id) => $("#panel-" + id);
  const pct = (x) => (typeof x === "number" ? `${Math.round(x * 100)}%` : "—");
  const chip = (t, cls = "") => `<span class="v-chip ${cls ? "v-" + cls : ""}">${esc(t)}</span>`;
  const sev = (s) => ({ CRITICAL: "bad", HIGH: "bad", MEDIUM: "mid", LOW: "", SUPPORTED: "good", AFFIRMED: "good", CONTRADICTED: "bad", OUTDATED: "bad",
    OVERRULED: "bad", QUALIFIED: "mid", PARTIALLY_SUPPORTED: "mid", supported: "good", partial: "mid", unsupported: "bad" }[s] || "");
  const cites = (cs) => (cs || []).map((c) => /^c\d+$/.test(c) ? `<button class="linkish" data-claim="${esc(c)}">${esc(c)}</button>` : `<span class="v-cite">${esc(c)}</span>`).join(" ");
  const empty = (msg) => `<div class="waiting">${esc(msg)}</div>`;

  // ---------- theme + log toggle + More menu ----------
  const setTheme = (t) => { document.documentElement.dataset.theme = t; try { localStorage.theme = t; } catch (e) {} };
  try { if (localStorage.theme) setTheme(localStorage.theme); } catch (e) {}
  $("#themeToggle").onclick = () => setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
  $("#logHide").onclick = () => $("#runView").classList.add("nolog");
  $("#logShow").onclick = () => $("#runView").classList.remove("nolog");
  $("#moreTabs").onchange = (e) => e.target.value && showTab(e.target.value);

  // ---------- progress stepper ----------
  const STEPS = [["Goal", ["interview"]], ["Hypotheses", ["hypotheses"]], ["Plan", ["plan"]], ["Research", ["search", "select", "fetch", "claims", "ledger"]],
    ["Evidence", ["belief", "voi"]], ["Challenge", ["challenge", "index"]], ["Trial", ["trial"]], ["Report", ["report"]],
    ["Audit", ["entities", "court", "autopsy", "economics"]]];
  let S = { state: {}, cur: null, waiting: null, t: 0, failed: false };
  function step(ev) {
    if (ev.i === 0) S = { state: {}, cur: null, waiting: null, t: 0, failed: false };
    S.t = ev.t;
    const st = ev.stage.startsWith("await") ? "await" : ev.stage;
    if (st === "await") S.waiting = ev.status === "waiting" ? (ev.data?.question || ev.title) : null;
    const idx = STEPS.findIndex(([, ks]) => ks.includes(st));
    if (idx >= 0) {
      if (ev.status === "running") { S.cur = Math.max(S.cur ?? 0, idx); S.waiting = null; for (let i = 0; i < idx; i++) S.state[i] = "done"; if (S.state[idx] !== "done") S.state[idx] = "now"; }
      if (ev.status === "done" || ev.status === "failed") { for (let i = 0; i < idx; i++) S.state[i] = "done"; if (idx < 8 || S.state[8] !== "done") S.state[idx] = idx === S.cur && idx === 8 ? "now" : "done"; }
      if (ev.status === "failed" && ["interview", "hypotheses", "plan"].includes(st)) S.failed = true;
    }
    if (st === "complete") { for (let i = 0; i < 8; i++) S.state[i] = "done"; S.cur = 8; S.state[8] = S.state[8] || "now"; }
    drawSteps();
  }
  function drawSteps() {
    const done = Object.values(S.state).filter((x) => x === "done").length;
    const cur = S.cur != null ? STEPS[S.cur][0] : "Starting";
    const label = S.waiting ? `Waiting for your answer` : S.state[8] === "done" ? "All done" : S.cur === 8 ? "Results ready — audit running in the background" : `${cur}…`;
    $("#stepper").innerHTML = `<div class="st-head"><b class="${S.waiting ? "wait" : ""}">${esc(label)}</b><span>${done}/${STEPS.length} steps · ${Math.round(S.t)}s</span></div>
      <div class="st-bar"><i style="width:${(done / STEPS.length) * 100}%"></i></div>
      <ol class="st-steps">${STEPS.map(([n], i) => `<li class="${S.state[i] || ""}${i === S.cur && S.waiting ? " wait" : ""}">${n}</li>`).join("")}</ol>`;
  }
  // background stages finish after "complete": poll the run until they are done
  let poll;
  function done(snap) {
    clearInterval(poll);
    const bg = snap.result?.background || {};
    const fin = (v) => v === "done" || v === "interrupted";
    if (Object.values(bg).some((v) => !fin(v))) {
      poll = setInterval(async () => {
        const s = await (await fetch(`/api/research/runs/${RUN}`)).json();
        s.events.slice(S.seen || snap.events.length).forEach(step); S.seen = s.events.length;
        if (Object.values(s.result?.background || {}).every(fin)) { clearInterval(poll); S.state[8] = "done"; drawSteps(); D = s; overviewExtras(s); }
      }, 4000);
    } else { S.state[8] = "done"; drawSteps(); }
    overviewExtras(snap);
  }

  // ---------- overview extras: research debt + dissent ----------
  function overviewExtras(snap) {
    const R = snap.result || {}, rep = R.report || {}, v = rep.verification || {};
    const ch = R.challenges || [], weak = ch.filter((r) => ["CONTRADICTED", "OUTDATED"].includes(r.status)).length;
    const unver = ch.filter((r) => r.status === "INSUFFICIENT_EVIDENCE").length, partial = ch.filter((r) => r.status === "PARTIALLY_SUPPORTED").length;
    const crit = (R.autopsy?.findings || []).filter((f) => ["CRITICAL", "HIGH"].includes(f.severity)).length;
    const debt = weak * 3 + unver * 2 + partial + (v.struck || 0) + crit * 2;
    const panel = (R.trial?.panel || []).filter((r) => ["challenger", "premortem"].includes(r.role) && r.points?.length);
    const overruled = Object.values(R.court || {}).filter((h) => h.ruling === "OVERRULED");
    let box = $("#overviewExtras");
    if (!box) { box = document.createElement("div"); box.id = "overviewExtras"; $("#panel-verdict").append(box); }
    const sim = R.economics?.simulation;
    const mcCard = sim?.base ? `<section class="v-card"><h3>Monte Carlo unit economics <span class="v-badge v-${sim.probabilities.ltv_cac_above_3 >= 0.6 ? "good" : sim.probabilities.ltv_cac_above_3 >= 0.3 ? "mid" : "bad"}">${pct(sim.probabilities.ltv_cac_above_3)} chance LTV/CAC &gt; 3</span></h3>
      <div class="v-kv"><div><b>${sim.base.ltv_cac ?? "—"}</b>LTV/CAC (likely)</div><div><b>${sim.base.payback_months ?? "—"}</b>payback months</div>
      <div><b>${pct(sim.probabilities.margin_positive)}</b>P(margin &gt; 0)</div><div><b>${pct(sim.probabilities.payback_under_12m)}</b>P(payback &lt; 12m)</div>
      ${(sim.scenarios || []).filter((x) => /Worst case|Best case/.test(x.name)).map((x) => `<div><b>${x.ltv_cac ?? "—"}</b>${esc(x.name.toLowerCase())} LTV/CAC</div>`).join("")}
      ${sim.risk ? `<div><b>${pct(sim.risk.prob_ltv_below_cac)}</b>P(LTV &lt; CAC)</div>` : ""}</div>
      ${(sim.warnings || []).map((w) => `<p class="v-warn">⚠ ${esc(w)}</p>`).join("")}
      <p class="v-muted">${sim.trials} simulated futures over the parameter ranges; ${sim.assumed.length} of ${Object.keys(R.economics.params).length} parameters are assumptions (no evidence). Open More → Unit economics to test values.</p></section>` : "";
    box.innerHTML = mcCard + `<section class="v-card"><h3>Research debt register <span class="v-badge v-${debt > 10 ? "bad" : debt > 4 ? "mid" : "good"}">${debt}</span></h3>
      <div class="v-kv"><div><b>${weak}</b>contradicted / outdated</div><div><b>${unver}</b>unverified</div><div><b>${partial}</b>partially supported</div>
      <div><b>${v.struck || 0}</b>struck statements</div><div><b>${crit}</b>critical / high audit findings</div></div>
      <p class="v-muted">${debt === 0 ? "No outstanding epistemic debt." : `Before acting on this, resolve the ${weak + unver} weak or unverified claim(s) the verdict leans on; see Claims & debt and the autopsy follow-up queue.`}</p></section>
      ${panel.length || overruled.length ? `<section class="v-card v-dissent"><h3>Minority report <span class="v-badge v-mid">dissent</span></h3>
        ${panel.map((r) => `<p><b>${esc(r.title)}:</b> ${esc(r.points[0].point)} ${cites(r.points[0].cites)}</p>`).join("")}
        ${overruled.map((h) => `<p><b>Court overruled:</b> ${esc(h.claim_text.slice(0, 140))} — ${esc(h.rationale)}</p>`).join("")}</section>` : ""}`;
  }

  // ---------- report: "Generate report" opens the PDF in a new closable in-app tab ----------
  function report() {
    if (!D?.result?.report) return (P("report").innerHTML = empty("The report appears once research completes."));
    const url = API(`/report.pdf?t=${Date.now()}`);
    P("report").innerHTML = `<div class="v-toolbar"><b>Decision report</b><span class="v-muted">technical PDF built only from this run's records</span>
      <button class="v-btn v-small" id="genReport">Open in new tab ↗</button><a class="v-btn v-small v-ghost" href="${url}" target="_blank">Download PDF</a>
      <a class="v-btn v-small v-ghost" href="${API("/deck.pptx")}">Slide deck (.pptx)</a></div>
      <iframe class="v-pdf" src="${url}#view=FitH" title="Decision report"></iframe>`;
    $("#genReport").onclick = () => openDocTab(`Report ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`, API(`/report.pdf?t=${Date.now()}`));
  }
  let docN = 0;
  function openDocTab(title, url) {
    const id = `doc${++docN}`;
    const btn = document.createElement("button");
    btn.dataset.tab = id; btn.className = "v-doctab"; btn.innerHTML = `📄 ${esc(title)} <span class="v-x" title="Close">✕</span>`;
    $("#moreTabs").before(btn);
    const panel = document.createElement("div");
    panel.className = "panel"; panel.id = `panel-${id}`; panel.hidden = true;
    panel.innerHTML = `<div class="v-toolbar"><span class="v-muted">Generating the PDF… (a few seconds)</span><a class="v-btn v-small v-ghost" href="${url}" target="_blank">Open in browser</a></div>
      <iframe class="v-pdf" src="${url}#view=FitH" title="${esc(title)}"></iframe>`;
    $(".stage").append(panel);
    panel.querySelector("iframe").onload = () => (panel.querySelector(".v-muted").textContent = title);
    btn.onclick = (e) => {
      if (e.target.classList.contains("v-x")) { btn.remove(); panel.remove(); showTab("report"); return; }
      showTab(id);
    };
    showTab(id);
  }

  // ---------- ask (follow-up, RAG) ----------
  function ask() {
    const hist = D?.result?.followups || [];
    P("ask").innerHTML = `<div class="v-chat" id="chat">${hist.map(qa).join("") || empty("Ask anything about this research. Answers use only the collected evidence and are citation-checked.")}</div>
      <form class="v-askbox" id="askForm"><input name="q" placeholder="Ask a follow-up… e.g. What do competitors charge per month?" autocomplete="off"><button>Ask</button></form>`;
    $("#askForm").onsubmit = async (e) => {
      e.preventDefault(); const q = e.target.q.value.trim(); if (!q) return;
      e.target.q.value = ""; const c = $("#chat"); if (c.querySelector(".waiting")) c.innerHTML = "";
      c.insertAdjacentHTML("beforeend", `<div class="v-msg v-user">${esc(q)}</div><div class="v-msg v-bot v-pending">Searching the evidence…</div>`); c.scrollTop = 1e9;
      const r = await post("/ask", { question: q });
      c.querySelector(".v-pending").outerHTML = qa(r, true); c.scrollTop = 1e9;
      (D.result.followups = D.result.followups || []).push(r);
    };
  }
  const qa = (r, fresh) => `${fresh ? "" : `<div class="v-msg v-user">${esc(r.question)}</div>`}<div class="v-msg v-bot">
    ${(r.answer || []).map((a) => `<p>${esc(a.text)} ${cites(a.cites)} ${a.ruling && a.ruling !== "no citation" ? chip(a.ruling, sev(a.ruling)) : ""}</p>`).join("") || "<p>No answer.</p>"}
    ${r.needs_more_research ? `<button class="v-btn v-small" onclick="start(${esc(JSON.stringify(r.question))})">Research this deeper →</button>` : ""}</div>`;

  // ---------- agents & conversation ----------
  async function agents() {
    P("agents").innerHTML = empty("Loading agents…");
    const [ag, msgs] = await Promise.all([get("/agents"), get("/messages")]);
    const types = [...new Set(msgs.map((m) => m.type))];
    const name = Object.fromEntries(ag.map((a) => [a.id, a.name]));
    const draw = (f) => msgs.filter((m) => !f || m.type === f).slice(-250).map((m) => `<div class="v-msg v-agent"><span class="v-who">${esc(name[m.sender] || m.sender)} → ${esc(name[m.recipient] || m.recipient)}</span>
      ${chip(m.type.replaceAll("_", " ").toLowerCase())}<span>${esc(m.summary)}</span><span class="v-t">${m.t}s</span></div>`).join("");
    P("agents").innerHTML = `<div class="v-cards">${ag.map((a) => `<div class="v-card v-agentcard ${a.status.toLowerCase()}"><b>${esc(a.name)}</b><span class="v-muted">${esc(a.role)}</span>
      <div class="v-kv v-small"><div><b>${a.sources}</b>sources</div><div><b>${a.claims}</b>claims</div><div><b>${a.messages}</b>msgs</div></div>${chip(a.status, a.status === "WORKING" ? "mid" : a.status === "COMPLETED" ? "good" : "")}</div>`).join("")}</div>
      <div class="v-toolbar"><h3>Conversation</h3><select id="msgFilter"><option value="">All messages (${msgs.length})</option>${types.map((t) => `<option>${t}</option>`).join("")}</select></div>
      <div class="v-chat" id="convo">${draw("")}</div>`;
    $("#msgFilter").onchange = (e) => ($("#convo").innerHTML = draw(e.target.value));
  }

  // ---------- evidence court with voice playback ----------
  const VOICE = { JUDGE: { rate: 0.95, pitch: 0.8 }, CLERK: { rate: 1.05, pitch: 1.0 }, PROSECUTION: { rate: 1.08, pitch: 0.9 }, DEFENSE: { rate: 1.0, pitch: 1.15 } };
  async function court() {
    const c = await get("/court"), hs = Object.values(c.hearings || {});
    P("court").innerHTML = `<div class="v-toolbar"><form id="courtForm"><input name="claim" placeholder="Claim id to put on trial, e.g. c412"><button class="v-btn v-small">Hold hearing</button></form>
      <label class="v-muted">Voice speed <select id="vspeed"><option>0.8</option><option selected>1</option><option>1.25</option><option>1.5</option></select></label>
      ${c.status === "running" || c.status === "queued" ? chip("hearings running…", "mid") : ""}</div>
      ${hs.map((h, i) => `<section class="v-card"><h3>${chip(h.ruling, sev(h.ruling))} ${esc(h.claim_text.slice(0, 160))} <button class="v-btn v-small v-ghost" data-play="${i}">▶ Play hearing</button></h3>
        <p class="v-muted">${esc(h.rationale)}</p>${h.turns.map((t) => `<div class="v-turn ${t.role.toLowerCase()}"><b>${esc(t.role)}</b><p>${esc(t.thesis || t.statement)}</p>
        ${(t.points || []).map((p) => `<p class="v-pt"><b>${esc(p.label)}:</b> ${esc(p.text)} ${cites(p.cites)}</p>`).join("")}
        ${t.verification?.ruling && t.verification.ruling !== "no citation" ? chip(t.verification.ruling, sev(t.verification.ruling)) : ""}</div>`).join("")}</section>`).join("") || empty(c.status === "running" || c.status === "queued" ? "Hearings are running in the background…" : "No hearings yet — enter a claim id above (e.g. from the Verdict or Evidence views) and press Hold hearing.")}`;
    $("#courtForm").onsubmit = async (e) => { e.preventDefault(); const id = e.target.claim.value.trim(); if (!id) return; e.target.querySelector("button").textContent = "Hearing…"; await post("/court", { claim: id }); court(); };
    P("court").querySelectorAll("[data-play]").forEach((b) => (b.onclick = () => speak(hs[+b.dataset.play].turns)));
  }
  function speak(turns) {
    if (!("speechSynthesis" in window)) return alert("Speech is not supported in this browser");
    speechSynthesis.cancel();
    const speed = +$("#vspeed").value, voices = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
    turns.forEach((t, i) => {
      const u = new SpeechSynthesisUtterance(`${t.role.toLowerCase()}. ${t.thesis || ""}. ${(t.points || []).map((p) => `${p.label}: ${p.text}`).join(". ")}`);
      const v = VOICE[t.role] || {}; u.rate = (v.rate || 1) * speed; u.pitch = v.pitch || 1; if (voices.length) u.voice = voices[i % Math.min(voices.length, 3)];
      speechSynthesis.speak(u);
    });
  }

  // ---------- autopsy ----------
  async function autopsy() {
    const { status, autopsy: a } = await get("/autopsy");
    if (!a) {
      const busy = status === "running" || status === "queued";
      P("autopsy").innerHTML = empty(busy ? `Red-team autopsy ${status}… (it runs in the background after the report)` : status === "interrupted" ? "The autopsy was interrupted before it finished." : "No red-team autopsy for this run yet.")
        + (busy ? "" : `<button class="v-btn" id="audGo">Run red-team autopsy now</button>`);
      const btn = $("#audGo"); if (btn) btn.onclick = async () => { btn.textContent = "Auditing (about 10–30 s)…"; btn.disabled = true; await post("/autopsy"); autopsy(); };
      return;
    }
    const draw = (f) => a.findings.filter((x) => !f || x.severity === f).map((x) => `<div class="v-card v-finding"><b>${chip(x.severity, sev(x.severity))} ${esc(x.title)}</b>
      <span class="v-muted">${esc(x.auditor_name)} · ${esc(x.basis)}</span><p>${esc(x.description)}</p><p class="v-muted">${esc(x.why_it_matters)}</p>
      ${x.recommended_action ? `<p><b>Action:</b> ${esc(x.recommended_action)}</p>` : ""}${x.claims?.length ? `<p>${cites(x.claims)}</p>` : ""}</div>`).join("");
    P("autopsy").innerHTML = `<section class="v-card"><h3>Survival: ${chip(a.survival, a.survival === "SURVIVES" ? "good" : a.survival === "FAILS" ? "bad" : "mid")}</h3><p class="v-muted">${esc(a.survival_reasoning)}</p>
      <div class="v-toolbar"><select id="sevF"><option value="">All severities (${a.findings.length})</option>${["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((s) => `<option>${s}</option>`).join("")}</select>
      <button class="v-btn v-small v-ghost" id="reaudit">Re-run audit</button></div></section><div id="findings">${draw("")}</div>
      <section class="v-card"><h3>Follow-up research queue</h3>${a.followups.map((f) => `<p>${chip("P" + f.priority)} ${esc(f.question)} <span class="v-muted">— ${esc(f.reason)}</span></p>`).join("") || "<p class='muted'>Nothing queued.</p>"}</section>`;
    $("#sevF").onchange = (e) => ($("#findings").innerHTML = draw(e.target.value));
    $("#reaudit").onclick = async () => { $("#reaudit").textContent = "Auditing…"; await post("/autopsy"); autopsy(); };
  }

  // ---------- unit economics with sliders ----------
  async function economics() {
    const { status, economics: ec } = await get("/economics");
    if (!ec) {
      P("economics").innerHTML = empty(status ? `Economics ${status}…` : "No unit-economics model for this run yet.") + (status ? "" : `<button class="v-btn" id="ecGo">Compute now</button>`);
      const b = $("#ecGo"); if (b) b.onclick = async () => { b.textContent = "Extracting parameters from the evidence…"; await post("/economics"); economics(); };
      return;
    }
    if (ec.simulation?.error) return (P("economics").innerHTML = empty(ec.simulation.error));
    const params = Object.entries(ec.params);
    P("economics").innerHTML = `<section class="v-card"><h3>Monte Carlo simulation <span class="v-muted">unit economics per customer per month (${esc(ec.currency || "")})</span></h3>
      <div class="v-toolbar"><button class="v-btn v-small v-danger" id="mcWorst">⚠ Show worst case</button><button class="v-btn v-small v-ghost" id="mcBest">Show best case</button>
      <button class="v-btn v-small v-ghost" id="mcReset">Reset to likely</button><span class="v-muted" id="mcMode">Likely values — drag any parameter to test it</span></div>
      ${params.map(([k, p]) => { const lo = Math.min(p.low, p.value) * 0.5, hi = Math.max(p.high, p.value) * 1.5 || 1;
        return `<div class="v-slider"><label>${esc(k)} ${chip(p.basis, p.basis === "evidence" ? "good" : "mid")} ${cites(p.cites)}</label>
        <input type="range" data-k="${k}" min="${lo}" max="${hi}" step="${(hi - lo) / 200}" value="${p.value}"><output>${p.value}</output></div>`; }).join("")}</section>
      <section class="v-card" id="simOut"></section>`;
    const show = (s) => ($("#simOut").innerHTML = s.error ? empty(s.error) : `<div class="v-kv"><div><b>${s.base.margin}</b>margin</div><div><b>${s.base.ltv_cac ?? "—"}</b>LTV/CAC</div>
      <div><b>${s.base.payback_months ?? "—"}</b>payback (months)</div><div><b>${pct(s.probabilities.ltv_cac_above_3)}</b>P(LTV/CAC>3)</div>
      <div><b>${pct(s.probabilities.margin_positive)}</b>P(margin>0)</div><div><b>${pct(s.probabilities.payback_under_12m)}</b>P(payback<12m)</div></div>
      ${(s.warnings || []).map((w) => `<p class="v-warn">⚠ ${esc(w)}</p>`).join("")}
      <h4>Scenarios — worst case to best case</h4>
      <table class="v-mx"><tr><th>Scenario</th><th>Margin / customer / month</th><th>LTV</th><th>LTV / CAC</th><th>Payback (months)</th><th>How</th></tr>
      ${(s.scenarios || []).map((x) => `<tr class="${/Worst|Severe/.test(x.name) ? "v-rowbad" : /Best|Upside/.test(x.name) ? "v-rowgood" : ""}"><th>${esc(x.name)}</th>
        <td>${x.margin ?? "—"}</td><td>${x.ltv != null ? Math.round(x.ltv) : "—"}</td><td><b>${x.ltv_cac ?? "—"}</b></td><td>${x.payback_months ?? "never"}</td><td class="v-muted">${esc(x.how)}</td></tr>`).join("")}</table>
      ${s.risk ? `<h4>Tail risk</h4><div class="v-kv"><div><b>${s.risk.expected_ltv_cac ?? "—"}</b>expected LTV/CAC</div>
        <div><b>${s.risk.value_at_risk_p5_ltv_cac ?? "—"}</b>value at risk (p5 LTV/CAC)</div><div><b>${s.risk.expected_shortfall_ltv_cac ?? "—"}</b>avg of worst 5%</div>
        <div><b>${pct(s.risk.prob_loss_per_customer)}</b>P(loss per customer)</div><div><b>${pct(s.risk.prob_ltv_below_cac)}</b>P(LTV &lt; CAC)</div></div>` : ""}
      ${(s.tornado || []).length ? `<h4>What moves the outcome most (LTV/CAC swing, low → high)</h4>${tornadoChart(s.tornado)}` : ""}
      <div class="v-mc">${histo("LTV / CAC across " + s.trials + " simulated futures", s.histogram?.ltv_cac, 3, "target 3×")}
      ${histo("Payback period (months)", s.histogram?.payback_months, 12, "12 months")}</div>
      <p class="v-muted">Monte Carlo simulation: every parameter is drawn from its low–likely–high range ${s.trials} times. LTV/CAC p10–p90: ${s.distribution.ltv_cac ? `${s.distribution.ltv_cac.p10} – ${s.distribution.ltv_cac.p90}` : "—"}. Assumed (no evidence): ${s.assumed.join(", ") || "none"}.</p>`);
    show(ec.simulation); post("/economics/simulate", { overrides: {} }).then((x) => !x.error && show(x));   // always show the latest model (scenarios, tail risk)
    let tm, pinned = {};
    const UNFAV = { price: "low", variable_cost: "high", cac: "high", churn: "high", fixed_cost: "high" };
    const setAll = async (side, label) => {
      pinned = {};
      P("economics").querySelectorAll("input[type=range]").forEach((r) => {
        const p = ec.params[r.dataset.k], want = side === "likely" ? "value" : side === "worst" ? UNFAV[r.dataset.k] : (UNFAV[r.dataset.k] === "low" ? "high" : "low");
        const v = p[want] ?? p.value; r.value = v; r.nextElementSibling.textContent = (+v).toFixed(r.dataset.k === "churn" ? 3 : 0);
        if (side !== "likely") pinned[r.dataset.k] = v;
      });
      $("#mcMode").innerHTML = label; $("#simOut").classList.toggle("v-worst", side === "worst");
      show(await post("/economics/simulate", { overrides: pinned }));
    };
    $("#mcWorst").onclick = () => setAll("worst", "<b class='v-bad'>Worst case</b>: price at its low, every cost, churn and acquisition cost at its high");
    $("#mcBest").onclick = () => setAll("best", "<b class='v-good'>Best case</b>: every parameter at its favourable bound");
    $("#mcReset").onclick = () => setAll("likely", "Likely values — drag any parameter to test it");
    P("economics").querySelectorAll("input[type=range]").forEach((r) => (r.oninput = () => {
      r.nextElementSibling.textContent = (+r.value).toFixed(r.dataset.k === "churn" ? 3 : 0); pinned[r.dataset.k] = +r.value;
      clearTimeout(tm); tm = setTimeout(async () => show(await post("/economics/simulate", { overrides: pinned })), 250);
    }));
  }

  function tornadoChart(t) {
    const max = Math.max(...t.map((x) => Math.max(Math.abs(x.at_low), Math.abs(x.at_high)))) || 1;
    return `<div class="v-tornado">${t.map((x) => { const lo = Math.min(x.at_low, x.at_high), hi = Math.max(x.at_low, x.at_high);
      return `<div class="v-trow"><span>${esc(x.param)}</span><div class="v-tbar"><i style="left:${(lo / max) * 50 + 50}%;width:${Math.max(1, ((hi - lo) / max) * 50)}%"></i></div>
        <span class="v-muted">${x.at_low} → ${x.at_high}</span></div>`; }).join("")}</div>`;
  }

  function histo(title, h, mark, markLabel) {
    if (!h || !h.counts?.length) return "";
    const W = 420, H = 120, n = h.counts.length, max = Math.max(...h.counts), bw = W / n;
    const xOf = (v) => ((v - h.lo) / ((h.hi - h.lo) || 1)) * W;
    const bars = h.counts.map((c, i) => { const v = h.lo + (i + 0.5) * (h.hi - h.lo) / n; const bh = (c / max) * (H - 18);
      return `<rect x="${i * bw + 1}" y="${H - bh - 14}" width="${bw - 2}" height="${bh}" class="${mark != null && v >= mark ? "v-ok" : ""}"/>`; }).join("");
    const m = mark != null && mark >= h.lo && mark <= h.hi ? `<line x1="${xOf(mark)}" x2="${xOf(mark)}" y1="0" y2="${H - 14}"/><text x="${xOf(mark) + 4}" y="10">${markLabel}</text>` : "";
    return `<figure><figcaption>${esc(title)}</figcaption><svg viewBox="0 0 ${W} ${H}" class="v-hist">${bars}${m}
      <text x="0" y="${H - 2}">${h.lo}</text><text x="${W}" y="${H - 2}" text-anchor="end">${h.hi}</text></svg></figure>`;
  }

  // ---------- what-if lab ----------
  function whatif() {
    const b = D?.result?.belief;
    if (!b) return (P("whatif").innerHTML = empty("Available once evidence has been weighed."));
    P("whatif").innerHTML = `<section class="v-card"><h3>Ask a what-if</h3><form class="v-askbox" id="wiForm"><input name="q" placeholder="e.g. What if a competitor cuts prices by 30%?"><button>Run</button></form><div id="wiOut"></div></section>
      <section class="v-card"><h3>Assumptions</h3>${b.assumptions.map((a) => `<div class="v-slider"><label>${esc(a.text)}</label><input type="range" data-a="${a.id}" min="0.01" max="0.99" step="0.01" value="${a.p}"><output>${pct(a.p)}</output></div>`).join("") || "<p class='muted'>No assumptions.</p>"}<div id="forkOut"></div></section>`;
    const diff = (r) => `<p><b>Verdict ${pct(r.baseline.verdict)} → ${pct(r.result.verdict)}</b> ${r.flips ? chip("flips the decision", "bad") : ""}</p>
      ${r.diff.map((d) => `<p>${esc(d.id)}: ${pct(d.before)} → ${pct(d.after)} <span class="${d.delta > 0 ? "v-good" : d.delta < 0 ? "v-bad" : "v-muted"}">${d.delta > 0 ? "+" : ""}${Math.round(d.delta * 100)} pts</span></p>`).join("")}`;
    $("#wiForm").onsubmit = async (e) => { e.preventDefault(); $("#wiOut").innerHTML = "<p class='muted'>Mapping the question onto the model…</p>";
      const r = await post("/whatif/ask", { question: e.target.q.value }); $("#wiOut").innerHTML = `<p class="v-muted">${esc(r.mapping_reason || "")}</p>${diff(r)}`; };
    let tm, vals = {};
    P("whatif").querySelectorAll("input[data-a]").forEach((r) => (r.oninput = () => { r.nextElementSibling.textContent = pct(+r.value); vals[r.dataset.a] = +r.value;
      clearTimeout(tm); tm = setTimeout(async () => ($("#forkOut").innerHTML = diff(await post("/whatif/fork", { assumptions: vals }))), 200); }));
  }

  // ---------- comparison matrix ----------
  async function matrix() {
    const { status, matrix: m } = await get("/matrix");
    if (!m || !m.rows?.length) {
      P("matrix").innerHTML = empty(status && status !== "done" ? `Matrix ${status}…` : "No comparison matrix yet.") + (status && status !== "done" ? "" : `<button class="v-btn" id="mxGo">Build matrix from the evidence</button>`);
      const b = $("#mxGo"); if (b) b.onclick = async () => { b.textContent = "Reading the evidence…"; await post("/matrix"); matrix(); };
      return;
    }
    P("matrix").innerHTML = `<div class="v-toolbar"><span class="v-muted">${m.rows.length} options × ${m.columns.length} attributes · ${pct(m.coverage)} of cells backed by a cited claim; blanks were not stated in the evidence.</span>
      <button class="v-btn v-small v-ghost" id="mxRe">Rebuild</button></div>
      <div class="v-mxwrap"><div class="v-grid" style="grid-template-columns: 140px repeat(${m.columns.length}, minmax(118px, 1fr)) 64px">
        <div class="v-gcorner">Option \ Attribute</div>${m.columns.map((c) => `<div class="v-gcol">${esc(c)}</div>`).join("")}<div class="v-gcol v-gsum">evidence</div>
        ${m.rows.map((r) => { const n = m.columns.filter((c) => m.cells[r][c]).length;
          return `<div class="v-grow">${esc(r)}</div>${m.columns.map((c) => { const x = m.cells[r][c];
            return x ? `<div class="v-gcell v-gfill"><span>${esc(x.value)}</span><div class="v-gcites">${cites(x.cites)}</div></div>` : `<div class="v-gcell v-gempty" title="Not stated in the evidence">not stated</div>`; }).join("")}
            <div class="v-gsum"><b>${n}</b>/${m.columns.length}</div>`; }).join("")}
        <div class="v-gcorner v-gsum">coverage</div>${m.columns.map((c) => { const n = m.rows.filter((r) => m.cells[r][c]).length;
          return `<div class="v-gsum"><b>${n}</b>/${m.rows.length}</div>`; }).join("")}<div class="v-gsum"><b>${pct(m.coverage)}</b></div>
      </div></div>`;
    $("#mxRe").onclick = async () => { $("#mxRe").textContent = "Rebuilding…"; await post("/matrix"); matrix(); };
  }

  // ---------- action plan (plan generator) ----------
  async function actionplan() {
    const { status, plan } = await get("/action-plan");
    if (!plan) {
      P("actionplan").innerHTML = empty(status ? `Action plan ${status}…` : "No action plan yet.") + (status ? "" : `<button class="v-btn" id="apGo">Generate plan</button>`);
      const b = $("#apGo"); if (b) b.onclick = async () => { b.textContent = "Planning…"; await post("/action-plan"); actionplan(); };
      return;
    }
    P("actionplan").innerHTML = (plan.first_step ? `<section class="v-card v-dissent"><h3>First step</h3><p>${esc(plan.first_step)}</p></section>` : "")
      + plan.phases.map((p, i) => `<section class="v-card"><h3>${chip(`Phase ${i + 1}`)} ${esc(p.name)} <span class="v-muted">${esc(p.horizon)}</span></h3>
        ${p.actions.map((a) => `<p>• ${esc(a)}</p>`).join("")}<p><b>Go / no-go gate:</b> ${esc(p.gate)}</p>
        ${p.risks_addressed.length ? `<p class="v-muted">Retires: ${p.risks_addressed.map(esc).join(" · ")}</p>` : ""}<p>${cites(p.cites)}</p></section>`).join("");
  }

  // ---------- planner ----------
  async function planner() {
    const p = await get("/planner");
    const phases = [...new Set(p.tasks.map((t) => t.phase))];
    P("planner").innerHTML = `<div class="v-kv"><div><b>${pct(p.coverage)}</b>coverage</div><div><b>${pct(p.confidence)}</b>confidence</div><div><b>${p.round}</b>rounds</div>
      <div><b>${p.budget.searches}</b>searches</div><div><b>${p.budget.pages_read}</b>pages read</div><div><b>${Math.round(p.budget.elapsed_s)}s</b>elapsed</div></div>
      ${phases.map((ph) => `<section class="v-card"><h3>${esc(ph)}</h3>${p.tasks.filter((t) => t.phase === ph).map((t) => `<div class="v-task">${chip(t.status, t.status === "COMPLETED" ? "good" : t.status === "BLOCKED" ? "bad" : "mid")}
        ${chip(t.agent || "—")} <b>${esc(t.title)}</b> <span class="v-muted">${t.claims} claims · ${esc(t.reason_for_creation)}</span></div>`).join("")}</section>`).join("")}
      <section class="v-card"><h3>Open uncertainties</h3>${p.uncertainties.map((u) => `<p>${chip(u.status, u.status === "RESOLVED" || u.status === "ANSWERED" ? "good" : "mid")} ${esc(u.question)} <span class="v-muted">${pct(u.p)}</span></p>`).join("")}</section>
      <section class="v-card"><h3>Plan versions</h3>${p.versions.map((v) => `<p><b>${esc(v.version)}</b> at ${v.t}s — ${esc(v.summary)}</p>`).join("")}</section>`;
  }

  // ---------- replay ----------
  async function replay() {
    const items = await get("/replay");
    let i = 0, timer = null, cat = "";
    P("replay").innerHTML = `<div class="v-toolbar"><button class="v-btn v-small" id="rpPlay">▶ Play</button><input type="range" id="rpSeek" min="0" max="${items.length - 1}" value="0">
      <select id="rpCat"><option value="">All</option>${["PLAN", "DISCOVERY", "VERIFICATION", "CHALLENGE", "JUDICIAL"].map((c) => `<option>${c}</option>`).join("")}</select></div><div class="v-chat" id="rpList"></div>`;
    const draw = () => { $("#rpSeek").value = i; $("#rpList").innerHTML = items.slice(0, i + 1).filter((x) => !cat || x.category === cat).map((x) =>
      `<div class="v-msg v-agent">${chip(x.category)}<b>${esc(x.title)}</b><span>${esc(x.detail)}</span><span class="v-t">${x.t}s</span></div>`).join(""); $("#rpList").scrollTop = 1e9; };
    $("#rpSeek").oninput = (e) => { i = +e.target.value; draw(); };
    $("#rpCat").onchange = (e) => { cat = e.target.value; draw(); };
    $("#rpPlay").onclick = () => { if (timer) { clearInterval(timer); timer = null; $("#rpPlay").textContent = "▶ Play"; return; }
      $("#rpPlay").textContent = "❚❚ Pause"; timer = setInterval(() => { if (i >= items.length - 1) { clearInterval(timer); timer = null; $("#rpPlay").textContent = "▶ Play"; return; } i++; draw(); }, 600); };
    draw();
  }

  // ---------- memory ----------
  async function memory() {
    P("memory").innerHTML = empty("Comparing this investigation with every past run (first load can take a few seconds; then it is cached)…");
    const m = await (await fetch(`/api/memory?question=${encodeURIComponent(D?.query || "")}`)).json();
    P("memory").innerHTML = `<div class="v-kv">${Object.entries(m.health).filter(([, v]) => typeof v === "number").map(([k, v]) => `<div><b>${v}</b>${esc(k.replaceAll("_", " "))}</div>`).join("")}</div>
      <section class="v-card"><h3>Related investigations</h3>${m.projects.slice(0, 10).map((p) => `<p><a href="#run=${p.id}">${esc(p.question)}</a> ${p.relevance != null ? chip(`${pct(p.relevance)} relevant`) : ""} ${p.verdict ? chip(p.verdict) : ""}</p>`).join("")}</section>
      <section class="v-card"><h3>Entities</h3><p>${m.entities.slice(0, 40).map((e) => chip(`${e.name} · ${e.runs.length}`)).join(" ")}</p></section>
      <section class="v-card"><h3>Claims seen in several runs</h3>${m.recurring_claims.slice(0, 12).map((c) => `<p>${esc(c.text)} <span class="v-muted">${c.runs.length} runs</span></p>`).join("") || "<p class='muted'>None yet.</p>"}</section>
      <section class="v-card"><h3>Cross-run contradictions</h3>${m.contradictions.slice(0, 8).map((c) => `<p>“${esc(c.a.text.slice(0, 120))}” <b>vs</b> “${esc(c.b.text.slice(0, 120))}”</p>`).join("") || "<p class='muted'>None.</p>"}</section>
      <section class="v-card"><h3>Open questions</h3>${m.open_questions.slice(0, 12).map((q) => `<p>${chip(q.severity, sev(q.severity))} ${esc(q.question)}</p>`).join("")}</section>`;
  }

  // ---------- evidence by hypothesis (replaces the old Findings list) ----------
  function brief() {
    if ($("#briefWaiting")) $("#briefWaiting").hidden = true;
    const R = D?.result || {}, ev = R.belief?.evidence || [], hs = R.report?.hypotheses || R.hypotheses?.hypotheses || [];
    if (!ev.length) return ($("#brief").innerHTML = empty("Evidence appears once it has been weighed against the hypotheses."));
    const st = Object.fromEntries((R.challenges || []).map((c) => [c.claim, c.status]));
    $("#brief").innerHTML = hs.map((h) => {
      const rows = ev.filter((e) => e.hypothesis === h.id && D.claims[e.claim]).sort((a, b) => b.strength * b.reliability - a.strength * a.reliability);
      const seen = new Set(), uniq = rows.filter((e) => !seen.has(e.claim) && seen.add(e.claim)).slice(0, 12);
      return `<section class="v-card"><h3>${esc(h.id)} ${h.p != null ? `<span class="v-badge v-${h.p >= .6 ? "good" : h.p <= .4 ? "bad" : "mid"}">${pct(h.p)}</span>` : ""} ${esc(h.text)}</h3>
        <table class="v-mx"><tr><th></th><th>Evidence (verbatim)</th><th>Source</th><th>Strength</th><th>Fresh</th><th>Checked</th></tr>
        ${uniq.map((e) => { const c = D.claims[e.claim], s = D.sources[c.source] || {};
          return `<tr><td class="${e.stance > 0 ? "v-good" : "v-bad"}">${e.stance > 0 ? "▲" : "▼"}</td><td>${esc(c.text)} <button class="linkish" data-claim="${esc(c.id)}">${esc(c.id)}</button></td>
            <td><button class="linkish" data-source="${esc(c.source)}">${esc(s.domain || c.source)}</button><div class="v-muted">${esc(s.type_label || "")}</div></td>
            <td>${pct(e.strength)}</td><td>${pct(e.freshness)}</td><td>${st[c.id] ? chip(st[c.id], sev(st[c.id])) : "—"}</td></tr>`; }).join("") || `<tr><td colspan="6" class="v-muted">No evidence found for this hypothesis.</td></tr>`}</table></section>`;
    }).join("");
  }

  // ---------- sources: what each source contributed ----------
  function sources() {
    if (!D?.sources) return ($("#sources").innerHTML = empty("Sources appear as research runs."));
    const used = new Set((D.result?.belief?.evidence || []).map((e) => D.claims[e.claim]?.source));
    const cited = new Set((D.result?.report?.sources || []).map((s) => s.id));
    const rows = Object.values(D.sources).filter((s) => s.status === "fetched" || s.n_claims)
      .sort((a, b) => (cited.has(b.id) - cited.has(a.id)) || (used.has(b.id) - used.has(a.id)) || (b.n_claims || 0) - (a.n_claims || 0));
    const types = [...new Set(rows.map((s) => s.type_label))];
    const draw = (f) => rows.filter((s) => !f || s.type_label === f).map((s) => `<tr><td><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.domain)}</a><div class="v-muted">${esc((s.fetched_title || s.title || "").slice(0, 90))}</div></td>
      <td>${esc(s.type_label || "")}</td><td>${s.n_claims || 0}</td><td>${cited.has(s.id) ? chip("cited in report", "good") : used.has(s.id) ? chip("weighed as evidence", "mid") : "—"}</td>
      <td>${s.origin === "verification" ? chip("verifier") : esc(s.via || s.origin || "")}</td><td><button class="linkish" data-source="${esc(s.id)}">details</button></td></tr>`).join("");
    $("#sources").innerHTML = `<div class="v-toolbar"><b>${rows.length} sources read</b><span class="v-muted">${cited.size} cited in the report · ${used.size} weighed as evidence</span>
      <select id="srcF"><option value="">All types</option>${types.map((t) => `<option>${esc(t)}</option>`).join("")}</select></div>
      <table class="v-mx"><tr><th>Source</th><th>Type</th><th>Claims taken</th><th>Role in verdict</th><th>Via</th><th></th></tr><tbody id="srcRows">${draw("")}</tbody></table>`;
    $("#srcF").onchange = (e) => ($("#srcRows").innerHTML = draw(e.target.value));
  }

  return { step, done, report, ask, actionplan, matrix, brief, sources, agents, court, autopsy, economics, whatif, planner, replay, memory };
})();

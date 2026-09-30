// Live research graph. One central question card; stage cards (live checklists / progress panels), hypothesis cards,
// sources and claims branch out as events arrive. Real relations are drawn: source -> claim -> hypothesis.
// Rich nodes are HTML inside SVG <foreignObject>; small nodes are SVG marks. No library, works offline.
const Graph = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const HUBS = {   // stage -> hub id
    interview: "goal", await: "goal", hypotheses: "hyp", belief: "hyp", plan: "plan", voi: "plan",
    search: "src", select: "src", fetch: "src", claims: "led", ledger: "led", index: "led", trial: "trial", report: "verdict", complete: "verdict",
  };
  const TITLES = { goal: "Goal interview", hyp: "Hypotheses", plan: "Research plan", src: "Sources", led: "Evidence ledger", trial: "Trial", verdict: "Verdict" };
  const LEN = { hub: 230, hyp: 190, dot: 90, ev: 80, role: 110, q: 140 };
  const MAX_SRC = 80;
  let svg, gLinks, gNodes, nodes, byId, links, view, raf, seenRel;

  function mount(host) {
    host.innerHTML = "";
    svg = document.createElementNS(NS, "svg"); svg.setAttribute("class", "kg");
    svg.innerHTML = `<defs><marker id="kgArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="kg-arrow"/></marker></defs>`;
    view = document.createElementNS(NS, "g"); gLinks = document.createElementNS(NS, "g"); gNodes = document.createElementNS(NS, "g");
    view.append(gLinks, gNodes); svg.append(view); host.append(svg);
    const legend = document.createElement("div"); legend.className = "kg-legend";
    legend.innerHTML = `<span><i class="lg-card"></i>stage: checklist / progress</span><span><i class="lg-hyp"></i>hypothesis · odds · trend · ⓘ assumptions</span>
      <span><i class="lg-dot"></i>source</span><span><i class="lg-up"></i>claim supports</span><span><i class="lg-down"></i>claim opposes</span>
      <span><i class="lg-rel"></i>source → claim → hypothesis</span><span><i class="lg-badge"></i>trial speaker</span>`;
    const fitBtn = document.createElement("button"); fitBtn.className = "kg-fit"; fitBtn.textContent = "Fit"; fitBtn.onclick = () => { userMoved = false; fit(); };
    host.append(legend, fitBtn);
    panZoom(host);
  }

  function reset(query) {
    nodes = []; byId = {}; links = []; seenRel = new Set();
    gLinks.innerHTML = ""; gNodes.innerHTML = ""; T = { x: 0, y: 0, k: 1 }; userMoved = false; applyView();
    add({ id: "root", kind: "root", label: query, info: `<p class="eyebrow">Research question</p><h2>${esc(query)}</h2>` });
  }

  // ---------- helpers ----------
  const el = (tag, attrs = {}) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
  const pcls = (p) => (p >= 0.6 ? "good" : p <= 0.4 ? "bad" : "mid");
  const pct = (p) => `${Math.round(p * 100)}%`;
  const barHTML = (p, cls) => `<div class="kgc-bar"><i class="${cls}" style="width:${Math.max(0, Math.min(1, p)) * 100}%"></i></div>`;
  const check = (state, text, extra = "") => `<li class="${state}"><b>${state === "done" ? "✓" : state === "run" ? "◌" : state === "bad" ? "✕" : "○"}</b><span>${esc(text)}</span>${extra}</li>`;
  function spark(hist) {
    if (!hist || hist.length < 2) return "";
    const w = 60, h = 16, pts = hist.map((p, i) => `${(i / (hist.length - 1)) * w},${h - p * h}`).join(" ");
    return `<svg class="kgc-spark" width="${w}" height="${h}"><line x1="0" x2="${w}" y1="${h / 2}" y2="${h / 2}"/><polyline points="${pts}"/></svg>`;
  }

  // ---------- rich cards (HTML in foreignObject) ----------
  const CARD = {
    root(n) {
      return { w: 280, html: `<div class="kgc-eyebrow">Research question</div><div class="kgc-q">${esc(n.label)}</div>` +
        (n.p != null ? `<div class="kgc-row">${barHTML(n.p, pcls(n.p))}<b>${pct(n.p)}</b></div><div class="kgc-sub">${esc(n.lean || "verdict so far")}</div>` : `<div class="kgc-sub">${esc(n.sub || "starting…")}</div>`) };
    },
    goal(n) {
      const qa = n.qa || [];
      return { w: 240, html: head(n) + `<ul class="kgc-list">${qa.map((x) => check(x.a ? "done" : "run", x.q, x.a ? `<em>${esc(x.a)}</em>` : "")).join("") ||
        check("run", "Understanding your goal…")}</ul>` + (n.done ? `<div class="kgc-sub">✓ goal confirmed — research may start</div>` : "") };
    },
    hyp(n) {
      return { w: 220, html: head(n) + `<ul class="kgc-list">${(n.items || []).map((h) => check(h.p != null ? "done" : "todo", `${h.id} · ${h.p != null ? pct(h.p) : "prior " + pct(h.prior ?? 0.5)}`)).join("") || check("run", "Forming hypotheses from your goal…")}</ul>` +
        (n.round ? `<div class="kgc-sub">weighed in ${n.round} round(s) · ${n.labels || 0} evidence labels</div>` : "") };
    },
    plan(n) {
      const tasks = n.tasks || [], done = tasks.filter((t) => (t.claims || 0) > 0).length;
      return { w: 290, html: head(n, `${done}/${tasks.length}`) + (tasks.length ? `<div class="kgc-row">${barHTML(done / (tasks.length || 1), "acc")}</div>` : "") +
        `<ul class="kgc-list">${tasks.slice(0, 8).map((t) => check((t.claims || 0) > 0 ? "done" : n.searching ? "run" : "todo", (t.follow ? "↳ " : "") + t.question,
          t.claims ? `<small>${t.claims} claims</small>` : "")).join("") || check("run", "Breaking the question into tasks…")}</ul>` +
        (tasks.length > 8 ? `<div class="kgc-sub">+${tasks.length - 8} more tasks</div>` : "") };
    },
    src(n) {
      const r = n.read || 0, f = n.failed || 0, tot = r + f || 1, types = Object.entries(n.types || {}).sort((a, b) => b[1] - a[1]).slice(0, 5);
      return { w: 230, html: head(n) + `<div class="kgc-stats"><div><b>${n.searches || 0}</b>searches</div><div><b>${r}</b>read</div><div><b>${f}</b>unreadable</div></div>` +
        `<div class="kgc-bar split"><i class="good" style="width:${r / tot * 100}%"></i><i class="bad" style="width:${f / tot * 100}%"></i></div>` +
        (types.length ? `<div class="kgc-tags">${types.map(([t, c]) => `<span>${esc(t)} ${c}</span>`).join("")}</div>` : "") };
    },
    led(n) {
      const s = n.steps || {};
      return { w: 250, html: head(n) + `<ul class="kgc-list">${[
        ["extract", `Extract claims${n.claims ? ` · ${n.claims}` : ""}`], ["fresh", `Freshness${n.stale != null ? ` · ${n.stale} stale` : ""}`],
        ["indep", `Independence${n.clusters ? ` · ${n.clusters} clusters` : ""}`], ["contra", `Contradictions${n.conflicts ? ` · ${n.conflicts.length}` : ""}`],
      ].map(([k, t]) => check(s[k] || "todo", t)).join("")}</ul>` +
        (n.conflicts || []).slice(0, 3).map((c) => `<div class="kgc-warn">⚠ ${esc(c.measure)} ${esc((c.values || []).join(" vs "))}</div>`).join("") };
    },
    trial(n) {
      const roles = n.roles || [];
      return { w: 230, html: head(n) + `<ul class="kgc-list">${["Advocate", "Challenger", "Witnesses", "Pre-mortem"].map((r) =>
        check(roles.some((x) => x.toLowerCase().includes(r.toLowerCase().slice(0, 6))) ? "done" : n.status === "running" ? "run" : "todo", r)).join("")}</ul>` };
    },
    verdict(n) {
      const p = n.p, v = n.v || {}, tot = v.statements || 1, a = Math.PI * (1 - (p ?? 0)), r = 34;
      const gauge = `<svg width="90" height="50" viewBox="-45 -40 90 50"><path d="M -${r} 0 A ${r} ${r} 0 0 1 ${r} 0" class="kgc-g-bg"/>` +
        (p != null ? `<path d="M -${r} 0 A ${r} ${r} 0 0 1 ${Math.cos(a) * r} ${-Math.sin(a) * r}" class="kgc-g ${pcls(p)}"/>` : "") +
        `<text x="0" y="-4" text-anchor="middle">${p != null ? pct(p) : "…"}</text></svg>`;
      return { w: 250, html: head(n) + `<div class="kgc-row">${gauge}<div class="kgc-sub">${esc(n.lean || (n.status === "running" ? "verifying & writing…" : "waiting for evidence"))}</div></div>` +
        (v.statements ? `<div class="kgc-sub">Citations verified ${v.supported}/${v.statements}</div><div class="kgc-bar split">${[["supported", "good"], ["partial", "mid"], ["struck", "bad"]]
          .map(([k, c]) => `<i class="${c}" style="width:${(v[k] || 0) / tot * 100}%"></i>`).join("")}</div>` : "") +
        (n.cruxes || []).map((c) => `<div class="kgc-crux">◆ ${esc(c)}</div>`).join("") };
    },
    hypcard(n) {   // one hypothesis: text, odds, trend, ⓘ assumptions (expand in place)
      const p = n.p ?? n.prior ?? 0.5, asm = n.assumptions || [];
      return { w: 230, html: `<div class="kgc-hyph"><span class="kgc-id">${esc(n.hid)}</span>` +
        (asm.length ? `<button class="kgc-info ${n.open ? "on" : ""}" data-act="toggle" title="Assumptions behind this hypothesis">ⓘ ${asm.length}</button>` : "") + `</div>` +
        `<div class="kgc-text">${esc(n.label)}</div><div class="kgc-row">${barHTML(p, n.p == null ? "prior" : pcls(p))}<b>${pct(p)}</b>${spark(n.hist)}</div>` +
        `<div class="kgc-sub">▲ ${n.for || 0} for · ▼ ${n.against || 0} against</div>` +
        (n.open ? `<div class="kgc-asm">${asm.map((a) => `<div><b>~${pct(a.p)}</b> ${esc(a.text)}${a.answered ? ` <em>(you: ${esc(a.answered)})</em>` : ""}</div>`).join("")}</div>` : "") };
    },
    q(n) { const t = n.label.length > 110 ? n.label.slice(0, 108) + "…" : n.label; return { w: 200, html: `<div class="kgc-eyebrow">Asked you</div><div class="kgc-text">${esc(t)}</div>` }; },
  };
  function head(n, right = "") {
    const st = n.status === "running" ? "run" : n.status === "done" ? "done" : "todo";
    return `<div class="kgc-head"><i class="kgc-dot ${st}"></i><span>${esc(TITLES[n.id] || n.label)}</span><small>${esc(right || n.sub || "")}</small></div>`;
  }

  // ---------- rendering ----------
  function render(n) {
    const g = n.el; g.innerHTML = "";
    g.setAttribute("class", `kg-node ${n.kind} ${n.cls || ""} ${n.status || ""}`);
    const t = el("title"); t.textContent = n.label || ""; g.append(t);
    const cardFn = CARD[n.card || n.id] || CARD[n.kind];
    if (cardFn) {
      const { w, html } = cardFn(n);
      const fo = el("foreignObject", { x: -w / 2, y: -500, width: w, height: 1000 });
      const div = document.createElement("div"); div.className = `kgc kgc-${n.card || n.kind} ${n.status || ""}`; div.innerHTML = html;
      div.addEventListener("pointerdown", (e) => { if (e.target.closest("[data-act]")) e.stopPropagation(); });
      div.addEventListener("click", (e) => {
        const b = e.target.closest("[data-act]"); if (!b) return;
        e.stopPropagation(); n.open = !n.open; render(n); kick(0.3);
      });
      fo.append(div); g.append(fo);
      const h = div.offsetHeight || 60;
      fo.setAttribute("y", -h / 2); fo.setAttribute("height", h + 2);
      n.w = w; n.h = h;
      return;
    }
    if (n.kind === "dot") { g.append(el("circle", { r: 5.5, class: "kg-shape" })); n.w = n.h = 11; }
    else if (n.kind === "ev") {
      const s = 4 + (n.strength || 0.5) * 5;
      g.append(el("path", { class: "kg-shape", d: n.cls === "pos" ? `M 0 ${-s} L ${s} ${s * 0.8} L ${-s} ${s * 0.8} Z` : `M 0 ${s} L ${s} ${-s * 0.8} L ${-s} ${-s * 0.8} Z` }));
      n.w = n.h = s * 2;
    } else if (n.kind === "role") {
      const w = n.label.length * 6.6 + 26;
      g.append(el("rect", { x: -w / 2, y: -12, width: w, height: 24, rx: 6, class: "kg-shape" }));
      const tx = el("text", { y: 4, "text-anchor": "middle", class: "kg-chip" }); tx.textContent = n.label; g.append(tx);
      n.w = w; n.h = 24;
    }
  }

  // ---------- model ----------
  function add(n) {
    if (byId[n.id]) { Object.assign(byId[n.id], n); render(byId[n.id]); return byId[n.id]; }
    const p = n.parent && byId[n.parent], a = Math.random() * 6.283;
    Object.assign(n, { x: p ? p.x + Math.cos(a) * 40 : 0, y: p ? p.y + Math.sin(a) * 40 : 0, vx: 0, vy: 0 });
    if (n.kind === "root") n.fixed = true;
    nodes.push(n); byId[n.id] = n;
    if (p) link(p, n, "tree", LEN[n.kind] || 110);
    n.el = el("g");
    n.el.onclick = (e) => { e.stopPropagation(); const h = typeof n.info === "function" ? n.info() : n.info; if (h) openInspector(h); };
    dragNode(n);
    gNodes.append(n.el); render(n); kick();
    return n;
  }
  function link(s, t, type, len) {
    const l = { s, t, type, len, el: el("line", { class: "kg-link " + type }) };
    if (type === "rel") l.el.setAttribute("marker-end", "url(#kgArrow)");
    gLinks.append(l.el); links.push(l); return l;
  }
  function rel(a, b) {   // cross relation (not part of the tree)
    const k = a + ">" + b; if (seenRel.has(k) || !byId[a] || !byId[b]) return; seenRel.add(k);
    link(byId[a], byId[b], "rel", 120); kick(0.5);
  }
  const upd = (id, patch) => { const n = byId[id]; if (n) { Object.assign(n, typeof patch === "function" ? patch(n) : patch); render(n); } return n; };
  const hub = (id, status) => {
    const n = add({ id, kind: "hub", label: TITLES[id], parent: "root" });
    if (status && n.status !== status) upd(id, { status });
    return n;
  };

  // ---------- events -> graph ----------
  function ev(e) {
    if (!nodes) return;
    const stage = e.stage.startsWith("await") ? "await" : e.stage, d = e.data || {}, hid = HUBS[stage];
    if (hid) {
      const n = hub(hid, e.status === "running" ? "running" : e.status === "done" ? "done" : null);
      if (e.status !== "progress") n.info = `<p class="eyebrow">${esc(stage)} · t=${e.t}s</p><h2>${esc(e.title)}</h2><p>${esc(e.summary || "")}</p>`;
    }
    if (stage === "await" && e.status === "waiting" && d.question) {
      if (d.kind === "interview") upd("goal", (n) => ({ qa: [...(n.qa || []), { q: d.question, a: "" }] }));
      else add({ id: "q" + e.i, kind: "q", parent: "hyp", label: d.question, info: `<p class="eyebrow">Question to the user</p><h2>${esc(d.question)}</h2>` });
    }
    if (stage === "interview" && e.status === "done") upd("goal", { qa: (d.qa || []).map((x) => ({ q: x.q, a: x.a })), done: true, sub: `${(d.qa || []).length} Q&A` });
    if (stage === "hypotheses" && e.status === "done") {
      const byH = {};
      (d.assumptions || []).forEach((a) => (byH[a.hypothesis] = byH[a.hypothesis] || []).push(a));
      (d.hypotheses || []).forEach((x) => add({ id: x.id, hid: x.id, kind: "hyp", card: "hypcard", parent: "hyp", label: x.text, prior: x.prior,
        assumptions: byH[x.id] || [], hist: [], info: () => hypInfo(byId[x.id]) }));
      upd("hyp", { items: d.hypotheses || [], sub: `${(d.hypotheses || []).length}` });
      upd("root", { sub: "researching…" });
    }
    if (stage === "plan" && e.status === "done") upd("plan", { tasks: (d.tasks || []).map((t) => ({ id: t.id, question: t.question, claims: 0 })) });
    if (stage === "search") upd("plan", { searching: e.status !== "done" });
    if (stage === "search" && e.status === "progress" && d.results) upd("src", (n) => ({ searches: (n.searches || 0) + 1 }));
    if (stage === "voi" && e.status === "done") upd("plan", (n) => {
      const have = new Set((n.tasks || []).map((t) => t.question.toLowerCase().slice(0, 40)));
      const key = (q) => q.toLowerCase().replace(/[^a-z ]/g, "").slice(0, 28);
      const have2 = new Set((n.tasks || []).map((t) => key(t.question))), room = 4 - (n.tasks || []).filter((t) => t.follow).length;
      const add_ = (d.followups || []).filter((f) => !have2.has(key(f.question)) && have2.add(key(f.question))).slice(0, Math.max(0, room));
      return { tasks: [...(n.tasks || []), ...add_.map((f) => ({ id: f.id, question: f.question, claims: 0, follow: true }))] };
    });
    if (stage === "fetch" && e.status === "progress" && d.source) {
      const ok = /^Read/.test(e.title);
      upd("src", (n) => ({ read: (n.read || 0) + ok, failed: (n.failed || 0) + !ok }));
      if (nodes.filter((x) => x.kind === "dot").length < MAX_SRC) addSource(d.source, { url: d.url, domain: e.title.replace(/^(Read|Failed)\s+/, ""), bad: !ok, summary: e.summary });
    }
    if (stage === "claims") upd("led", (n) => ({ steps: { ...(n.steps || {}), extract: e.status === "done" ? "done" : "run" } }));
    if (stage === "claims" && e.status === "done" && d.per_task) upd("plan", (n) => ({ tasks: (n.tasks || []).map((t) => ({ ...t, claims: Math.max(t.claims || 0, d.per_task[t.id] || 0) })) }));
    if (stage === "ledger" && e.status === "running") upd("led", (n) => ({ steps: { ...(n.steps || {}), fresh: "run", indep: "run", contra: "run" } }));
    if (stage === "ledger" && e.status === "done")
      upd("led", { claims: d.claims, clusters: d.clusters, stale: d.stale_claims, conflicts: d.conflicts || [], steps: { extract: "done", fresh: "done", indep: "done", contra: (d.conflicts || []).length ? "bad" : "done" } });
    if (stage === "belief" && e.status === "done") {
      (d.result?.hypotheses || []).forEach((x) => upd(x.id, (n) => ({ p: x.p, for: x.for, against: x.against, hist: [...(n.hist || []), x.p] })));
      upd("hyp", (n) => ({ items: (n.items || []).map((h) => ({ ...h, p: d.result?.hypotheses?.find((x) => x.id === h.id)?.p })), round: (n.round || 0) + 1, labels: (d.evidence || []).length }));
      (d.assumptions || []).forEach((a) => byId[a.hypothesis] && upd(a.hypothesis, (n) => ({ assumptions: (n.assumptions || []).map((x) => (x.id === a.id ? { ...x, ...a } : x)) })));
      pendingEvidence = d.evidence || [];
      if (d.result?.verdict != null) { upd("root", { p: d.result.verdict }); byId.verdict && upd("verdict", { p: d.result.verdict }); }
      if (typeof D === "undefined" || !D) fetch(`/api/research/runs/${RUN}`).then((r) => r.json()).then(enrich).catch(() => {});
    }
    if (stage === "trial" && e.status === "done") {
      (d.panel || []).forEach((p) => add({ id: "role:" + p.role, kind: "role", parent: "trial", cls: p.role, label: p.title,
        info: `<p class="eyebrow">Trial · ${esc(p.title)}</p>` + (p.points || []).map((x) => `<p>${esc(x.point)}</p>` + (x.cites || []).map((c) => `<button class="linkish" data-claim="${esc(c)}">${esc(c)}</button> `).join("")).join("") }));
      upd("trial", { roles: (d.panel || []).map((p) => p.title) });
    }
    if (stage === "report" && e.status === "done" && d.verdict) {
      upd("verdict", { p: d.verdict.p, lean: d.verdict.label, v: d.verification || {}, cruxes: (d.cruxes || []).slice(0, 3).map((c) => c.text || c.id) });
      upd("root", { p: d.verdict.p, lean: d.verdict.label });
    }
    if (stage === "complete") nodes.forEach((n) => n.status === "running" && upd(n.id, { status: "done" }));
  }
  let pendingEvidence = [];

  function addSource(sid, s) {
    return add({ id: "s:" + sid, kind: "dot", parent: "src", cls: s.bad ? "bad" : s.type || "", label: `${s.domain || sid}${s.type ? " · " + s.type : ""}`,
      info: () => {
        if (typeof D !== "undefined" && D?.sources?.[sid]) { inspectSource(sid); return null; }
        return `<p class="eyebrow">Source ${esc(sid)}</p><h2>${esc(s.domain || "")}</h2><p><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a></p><p>${esc(s.summary || "")}</p>`;
      } });
  }

  // snapshot -> claims as ▲/▼ under their hypothesis, linked from the source they came from
  function enrich(snap) {
    if (!nodes || !snap?.claims) return;
    const types = {};
    Object.values(snap.sources || {}).forEach((s) => { if (s.status === "fetched" || s.status === "snippet") types[s.type_label || s.type] = (types[s.type_label || s.type] || 0) + 1; });
    upd("src", { types });
    const ev = (snap.events || []).filter((e) => e.stage === "belief" && e.status === "done").pop()?.data?.evidence || pendingEvidence;
    const per = {};
    ev.slice().sort((a, b) => b.strength - a.strength).forEach((x) => {
      if (!byId[x.hypothesis] || (per[x.hypothesis] = (per[x.hypothesis] || 0) + 1) > 7) return;
      const c = snap.claims[x.claim]; if (!c) return;
      const id = "c:" + x.claim;
      if (!byId[id]) add({ id, kind: "ev", parent: x.hypothesis, cls: x.stance > 0 ? "pos" : "neg", strength: x.strength, label: `${x.stance > 0 ? "▲" : "▼"} ${c.text}`,
        info: () => { inspectClaimOr(x.claim, c, snap); return null; } });
      else if (byId[id].parent !== x.hypothesis) rel(id, x.hypothesis);
      const s = snap.sources?.[c.source];
      if (s) { if (!byId["s:" + c.source]) addSource(c.source, { url: s.url, domain: s.domain, type: s.type }); rel("s:" + c.source, id); }
    });
  }
  function inspectClaimOr(cid, c, snap) {
    if (typeof D !== "undefined" && D) return inspectClaim(cid);
    const s = snap.sources?.[c.source] || {};
    openInspector(`<p class="eyebrow">Claim ${esc(cid)} · ${esc(c.kind)} · ${esc(c.epistemic)}</p><blockquote>“${esc(c.text)}”</blockquote><p>Source: <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.domain || c.source)}</a></p>`);
  }
  function hypInfo(n) {
    return `<p class="eyebrow">Hypothesis ${esc(n.hid)} · ${n.p != null ? pct(n.p) : "prior " + pct(n.prior ?? 0.5)}</p><h2>${esc(n.label)}</h2>` +
      `<p>▲ ${n.for || 0} supporting · ▼ ${n.against || 0} opposing independent clusters</p>` +
      ((n.assumptions || []).length ? `<h3>Assumptions</h3>${n.assumptions.map((a) => `<p><b>~${pct(a.p)}</b> ${esc(a.text)}</p>`).join("")}` : "");
  }

  // ---------- layout ----------
  let alpha = 1;
  function kick(a = 0.6) { alpha = Math.max(alpha, a); if (!raf) raf = requestAnimationFrame(tick); }
  function tick() {
    const n = nodes.length;
    for (let i = 0; i < n; i++) {          // size-aware repulsion  // ponytail: O(n²), fine for a few hundred nodes
      const a = nodes[i], ra = Math.hypot(a.w || 10, a.h || 10) / 2;
      for (let j = i + 1; j < n; j++) {
        const b = nodes[j], rb = Math.hypot(b.w || 10, b.h || 10) / 2;
        let dx = b.x - a.x, dy = b.y - a.y, d2 = dx * dx + dy * dy || 0.01;
        if (d2 > 490000) continue;
        const d = Math.sqrt(d2), gap = d - (ra + rb) * 0.85;
        const f = (gap < 0 ? 3 - gap * 0.1 : 1600 / (gap * gap + 500)) * alpha;
        dx /= d; dy /= d; a.vx -= dx * f; a.vy -= dy * f; b.vx += dx * f; b.vy += dy * f;
      }
    }
    for (const l of links) {
      const k = l.type === "rel" ? 0.004 : 0.03;
      const dx = l.t.x - l.s.x, dy = l.t.y - l.s.y, d = Math.sqrt(dx * dx + dy * dy) || 0.01, f = (d - l.len) * k * alpha;
      l.t.vx -= dx / d * f; l.t.vy -= dy / d * f; l.s.vx += dx / d * f * 0.3; l.s.vy += dy / d * f * 0.3;
    }
    for (let i = 0; i < n; i++) {          // hard rectangle separation for cards
      const a = nodes[i]; if ((a.w || 0) < 30) continue;
      for (let j = i + 1; j < n; j++) {
        const b = nodes[j]; if ((b.w || 0) < 30) continue;
        const ox = (a.w + b.w) / 2 + 14 - Math.abs(b.x - a.x), oy = (a.h + b.h) / 2 + 14 - Math.abs(b.y - a.y);
        if (ox <= 0 || oy <= 0) continue;
        const wa = a.fixed ? 0 : b.fixed ? 1 : 0.5, wb = 1 - wa;
        if (ox < oy) { const s = Math.sign(b.x - a.x || 1) * ox; a.x -= s * wa; b.x += s * wb; }
        else { const s = Math.sign(b.y - a.y || 1) * oy; a.y -= s * wa; b.y += s * wb; }
      }
    }
    for (const a of nodes) {
      if (a.fixed || a === dragging) { a.vx = a.vy = 0; continue; }
      a.vx = (a.vx - a.x * 0.0012 * alpha) * 0.8; a.vy = (a.vy - a.y * 0.0012 * alpha) * 0.8;
      a.x += a.vx; a.y += a.vy;
    }
    for (const l of links) {
      let x2 = l.t.x, y2 = l.t.y;
      if (l.type === "rel") { const dx = l.t.x - l.s.x, dy = l.t.y - l.s.y, d = Math.hypot(dx, dy) || 1, r = (l.t.w || 10) / 2 + 3; x2 -= dx / d * r; y2 -= dy / d * r; }
      l.el.setAttribute("x1", l.s.x); l.el.setAttribute("y1", l.s.y); l.el.setAttribute("x2", x2); l.el.setAttribute("y2", y2);
    }
    for (const a of nodes) a.el.setAttribute("transform", `translate(${a.x},${a.y})`);
    alpha *= 0.985;
    if (!userMoved && ++frame % 15 === 0) fit();
    raf = alpha > 0.02 || dragging ? requestAnimationFrame(tick) : null;
  }

  // ---------- interaction ----------
  let T = { x: 0, y: 0, k: 1 }, dragging = null, userMoved = false, frame = 0;
  function applyView() {
    const w = svg.clientWidth || 800, h = svg.clientHeight || 600;
    view.setAttribute("transform", `translate(${w / 2 + T.x},${h / 2 + T.y}) scale(${T.k})`);
  }
  function fit() {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const a of nodes) {
      x0 = Math.min(x0, a.x - (a.w || 10) / 2); y0 = Math.min(y0, a.y - (a.h || 10) / 2);
      x1 = Math.max(x1, a.x + (a.w || 10) / 2); y1 = Math.max(y1, a.y + (a.h || 10) / 2);
    }
    const w = svg.clientWidth || 800, h = (svg.clientHeight || 600) - 50, pad = 24;
    T.k = Math.min(1.2, Math.max(0.2, Math.min(w / (x1 - x0 + pad * 2), h / (y1 - y0 + pad * 2))));
    T.x = -((x0 + x1) / 2) * T.k; T.y = -((y0 + y1) / 2) * T.k - 18; applyView();
  }
  function panZoom(host) {
    let pan = null;
    svg.addEventListener("wheel", (e) => { e.preventDefault(); userMoved = true; T.k = Math.min(3, Math.max(0.2, T.k * (e.deltaY < 0 ? 1.1 : 0.9))); applyView(); }, { passive: false });
    svg.addEventListener("pointerdown", (e) => { if (e.target === svg) { userMoved = true; pan = { x: e.clientX - T.x, y: e.clientY - T.y }; } });
    window.addEventListener("pointermove", (e) => {
      if (pan) { T.x = e.clientX - pan.x; T.y = e.clientY - pan.y; applyView(); }
      if (dragging) {
        const r = svg.getBoundingClientRect();
        dragging.x = (e.clientX - r.left - r.width / 2 - T.x) / T.k; dragging.y = (e.clientY - r.top - r.height / 2 - T.y) / T.k; kick(0.3);
      }
    });
    window.addEventListener("pointerup", () => { pan = null; if (dragging) { dragging.fixed = true; dragging = null; } });
    new ResizeObserver(applyView).observe(host);
  }
  function dragNode(n) { n.el.addEventListener("pointerdown", (e) => { e.stopPropagation(); dragging = n; kick(0.3); }); }

  return { mount, reset, ev, enrich, fit: () => { userMoved = false; fit(); } };
})();

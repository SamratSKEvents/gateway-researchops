// Research graph as a left-to-right flow, laid out in columns that follow the research:
//   Question & goal -> Plan -> Sources -> Evidence -> Hypotheses -> Trial & verdict
// Each column: its stage card on top, then its items. Sources line up with the claims they produced, claims are grouped by the
// hypothesis they bear on, and each hypothesis sits beside its claims, so source -> claim -> hypothesis reads straight across.
// Deterministic layout (no physics), HTML cards in SVG foreignObject, pan/zoom, works offline.
const Graph = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const HUBS = {
    interview: "goal", await: "goal", hypotheses: "hyp", belief: "hyp", plan: "plan", voi: "plan",
    search: "src", select: "src", fetch: "src", claims: "led", ledger: "led", index: "led", trial: "trial", report: "verdict", complete: "verdict",
  };
  const TITLES = { goal: "Goal interview", hyp: "Hypotheses", plan: "Research plan", src: "Sources", led: "Evidence ledger", trial: "Trial", verdict: "Verdict" };
  const COL = { root: 0, goal: 0, plan: 1, src: 2, led: 3, hyp: 4, trial: 5, verdict: 5 };
  const COLW = [260, 280, 200, 260, 240, 240], GAPX = 56, GAPY = 16, HEAD_GAP = 46;
  const FLOW = [["root", "goal"], ["goal", "plan"], ["plan", "src"], ["src", "led"], ["led", "hyp"], ["hyp", "trial"], ["trial", "verdict"]];
  const PER_HYP = 6;
  let svg, gLinks, gNodes, nodes, byId, view, pendingEvidence;

  function mount(host) {
    host.innerHTML = "";
    svg = document.createElementNS(NS, "svg"); svg.setAttribute("class", "kg");
    svg.innerHTML = `<defs><marker id="kgArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="kg-arrow"/></marker></defs>`;
    view = el("g"); gLinks = el("g"); gNodes = el("g");
    view.append(gLinks, gNodes); svg.append(view); host.append(svg);
    const legend = document.createElement("div"); legend.className = "kg-legend";
    legend.innerHTML = `<span><i class="lg-card"></i>stage (checklist / progress)</span><span><i class="lg-src"></i>source</span>
      <span><i class="lg-up"></i>claim supports</span><span><i class="lg-down"></i>claim opposes</span><span><i class="lg-hyp"></i>hypothesis · ⓘ assumptions</span>
      <span><i class="lg-rel"></i>source → claim → hypothesis</span>`;
    const fitBtn = document.createElement("button"); fitBtn.className = "kg-fit"; fitBtn.textContent = "Reset view"; fitBtn.title = "Drag nodes to rearrange · scroll to move · Ctrl/⌘ + scroll to zoom · drag background to pan · Reset restores the layout"; fitBtn.onclick = () => { userMoved = false; nodes.forEach((n) => delete n.manual); layout(); fit(); };
    host.append(legend, fitBtn);
    panZoom(host);
  }

  function reset(query) {
    nodes = []; byId = {}; pendingEvidence = [];
    gLinks.innerHTML = ""; gNodes.innerHTML = ""; T = { x: 0, y: 0, k: 1 }; userMoved = false;
    add({ id: "root", kind: "root", label: query, info: `<p class="eyebrow">Research question</p><h2>${esc(query)}</h2>` });
  }

  // ---------- helpers ----------
  function el(tag, attrs = {}) { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; }
  const pcls = (p) => (p >= 0.6 ? "good" : p <= 0.4 ? "bad" : "mid");
  const pct = (p) => `${Math.round(p * 100)}%`;
  const cut = (s, n) => (String(s).length > n ? String(s).slice(0, n - 1) + "…" : String(s));
  const barHTML = (p, cls) => `<div class="kgc-bar"><i class="${cls}" style="width:${Math.max(0, Math.min(1, p)) * 100}%"></i></div>`;
  const check = (state, text, extra = "") => `<li class="${state}"><b>${state === "done" ? "✓" : state === "run" ? "◌" : state === "bad" ? "!" : "○"}</b><span>${esc(text)}</span>${extra}</li>`;
  function spark(hist) {
    if (!hist || hist.length < 2) return "";
    const w = 54, h = 16, pts = hist.map((p, i) => `${(i / (hist.length - 1)) * w},${h - p * h}`).join(" ");
    return `<svg class="kgc-spark" width="${w}" height="${h}"><line x1="0" x2="${w}" y1="${h / 2}" y2="${h / 2}"/><polyline points="${pts}"/></svg>`;
  }
  function head(n, right = "") {
    const st = n.status === "running" ? "run" : n.status === "done" ? "done" : "todo";
    return `<div class="kgc-head"><i class="kgc-dot ${st}"></i><span>${esc(TITLES[n.id] || n.label)}</span><small>${esc(right || n.sub || "")}</small></div>`;
  }

  // ---------- cards ----------
  const CARD = {
    root(n) {
      return { html: `<div class="kgc-eyebrow">Research question</div><div class="kgc-q">${esc(n.label)}</div>` +
        (n.p != null ? `<div class="kgc-row">${barHTML(n.p, pcls(n.p))}<b>${pct(n.p)}</b></div><div class="kgc-sub">${esc(n.lean || "verdict so far")}</div>` : `<div class="kgc-sub">${esc(n.sub || "starting…")}</div>`) };
    },
    goal(n) {
      const qa = n.qa || [];
      return { html: head(n) + `<ul class="kgc-list">${qa.map((x) => check(x.a ? "done" : "run", x.q, x.a ? `<em>${esc(x.a)}</em>` : "")).join("") ||
        check(n.status === "running" ? "run" : "todo", "Understand your goal")}</ul>` + (n.done ? `<div class="kgc-sub">✓ goal confirmed</div>` : "") };
    },
    plan(n) {
      const tasks = n.tasks || [], done = tasks.filter((t) => (t.claims || 0) > 0).length;
      return { html: head(n, tasks.length ? `${done}/${tasks.length} answered` : "") + (tasks.length ? `<div class="kgc-row">${barHTML(done / tasks.length, "acc")}</div>` : "") +
        `<ul class="kgc-list">${tasks.slice(0, 10).map((t) => check((t.claims || 0) > 0 ? "done" : n.searching ? "run" : "todo", (t.follow ? "↳ " : "") + t.question,
          t.claims ? `<small>${t.claims}</small>` : "")).join("") || check(n.status === "running" ? "run" : "todo", "Break the question into tasks")}</ul>` +
        (tasks.length > 10 ? `<div class="kgc-sub">+${tasks.length - 10} more</div>` : "") };
    },
    src(n) {
      const r = n.read || 0, f = n.failed || 0, tot = r + f || 1, types = Object.entries(n.types || {}).sort((a, b) => b[1] - a[1]).slice(0, 5);
      return { html: head(n) + `<div class="kgc-stats"><div><b>${n.searches || 0}</b>searches</div><div><b>${r}</b>read</div><div><b>${f}</b>unreadable</div></div>` +
        `<div class="kgc-bar split"><i class="good" style="width:${r / tot * 100}%"></i><i class="bad" style="width:${f / tot * 100}%"></i></div>` +
        (types.length ? `<div class="kgc-tags">${types.map(([t, c]) => `<span>${esc(t)} ${c}</span>`).join("")}</div>` : "") +
        (n.cited ? `<div class="kgc-sub">below: the ${n.cited} sources behind the strongest evidence</div>` : "") };
    },
    led(n) {
      const s = n.steps || {};
      return { html: head(n) + `<ul class="kgc-list">${[
        ["extract", `Extract claims${n.claims ? ` · ${n.claims}` : ""}`], ["fresh", `Freshness${n.stale != null ? ` · ${n.stale} stale` : ""}`],
        ["indep", `Independence${n.clusters ? ` · ${n.clusters} clusters` : ""}`], ["contra", `Contradictions${n.conflicts ? ` · ${n.conflicts.length}` : ""}`],
      ].map(([k, t]) => check(s[k] || "todo", t)).join("")}</ul>` +
        (n.conflicts || []).slice(0, 3).map((c) => `<div class="kgc-warn">⚠ ${esc(c.measure)}: ${esc((c.values || []).join(" vs "))}</div>`).join("") +
        (n.shown ? `<div class="kgc-sub">below: strongest evidence per hypothesis</div>` : "") };
    },
    hyp(n) {
      return { html: head(n, n.round ? `round ${n.round}` : "") + `<ul class="kgc-list">${(n.items || []).map((h) => check(h.p != null ? "done" : "todo", `${h.id} · ${h.p != null ? pct(h.p) : "prior " + pct(h.prior ?? 0.5)}`)).join("") ||
        check(n.status === "running" ? "run" : "todo", "Form hypotheses from your goal")}</ul>` };
    },
    trial(n) {
      const roles = n.roles || [];
      return { html: head(n, roles.length ? `${roles.length} speakers` : "") + `<ul class="kgc-list">${(roles.length ? roles : ["Advocate", "Challenger", "Witnesses", "Pre-mortem"]).map((r) =>
        check(roles.length ? "done" : n.status === "running" ? "run" : "todo", r)).join("")}</ul>` };
    },
    verdict(n) {
      const p = n.p, v = n.v || {}, tot = v.statements || 1, a = Math.PI * (1 - (p ?? 0)), r = 30;
      const gauge = `<svg width="80" height="44" viewBox="-40 -36 80 44"><path d="M -${r} 0 A ${r} ${r} 0 0 1 ${r} 0" class="kgc-g-bg"/>` +
        (p != null ? `<path d="M -${r} 0 A ${r} ${r} 0 0 1 ${Math.cos(a) * r} ${-Math.sin(a) * r}" class="kgc-g ${pcls(p)}"/>` : "") +
        `<text x="0" y="-4" text-anchor="middle">${p != null ? pct(p) : "…"}</text></svg>`;
      return { html: head(n) + `<div class="kgc-row">${gauge}<div class="kgc-sub">${esc(n.lean || (n.status === "running" ? "verifying & writing…" : "waiting for evidence"))}</div></div>` +
        (v.statements ? `<div class="kgc-sub">citations verified ${v.supported}/${v.statements}</div><div class="kgc-bar split">${[["supported", "good"], ["partial", "mid"], ["struck", "bad"]]
          .map(([k, c]) => `<i class="${c}" style="width:${(v[k] || 0) / tot * 100}%"></i>`).join("")}</div>` : "") +
        (n.cruxes || []).map((c) => `<div class="kgc-crux">◆ ${esc(c)}</div>`).join("") };
    },
    hypcard(n) {
      const p = n.p ?? n.prior ?? 0.5, asm = n.assumptions || [];
      return { html: `<div class="kgc-hyph"><span class="kgc-id">${esc(n.hid)}</span>` +
        (asm.length ? `<button class="kgc-info ${n.open ? "on" : ""}" data-act="toggle" title="Assumptions behind this hypothesis">ⓘ ${asm.length} assumption${asm.length > 1 ? "s" : ""}</button>` : "") + `</div>` +
        `<div class="kgc-text">${esc(n.label)}</div><div class="kgc-row">${barHTML(p, n.p == null ? "prior" : pcls(p))}<b>${pct(p)}</b>${spark(n.hist)}</div>` +
        `<div class="kgc-sub">▲ ${n.for || 0} for · ▼ ${n.against || 0} against</div>` +
        (n.open ? `<div class="kgc-asm">${asm.map((a) => `<div><b>~${pct(a.p)}</b> ${esc(a.text)}${a.answered ? ` <em>(you: ${esc(a.answered)})</em>` : ""}</div>`).join("")}</div>` : "") };
    },
    claim(n) { return { html: `<b>${n.cls === "pos" ? "▲" : "▼"}</b><span>${esc(cut(n.text, 92))}</span><small>${pct(n.strength || 0)}</small>` }; },
    source(n) { return { html: `<i class="t-${esc(n.stype || "other")}"></i><span>${esc(cut(n.domain || n.sid, 30))}</span><small>${esc(n.typeLabel || "")}</small>` }; },
    q(n) { return { html: `<div class="kgc-eyebrow">Asked you</div><div class="kgc-text">${esc(cut(n.label, 140))}</div>` }; },
  };
  const WIDTH = (n) => COLW[n.col] - 16;

  // ---------- rendering ----------
  function render(n) {
    const g = n.el; g.innerHTML = "";
    g.setAttribute("class", `kg-node ${n.card || n.kind} ${n.status || ""}`);
    const t = el("title"); t.textContent = n.text || n.label || ""; g.append(t);
    const w = WIDTH(n), { html } = (CARD[n.card] || CARD[n.id] || CARD[n.kind])(n);
    const fo = el("foreignObject", { x: -w / 2, y: -400, width: w, height: 800 });
    const div = document.createElement("div"); div.className = `kgc kgc-${n.card === "source" ? "src" : n.card || n.kind} ${n.cls || ""} ${n.status || ""}`; div.innerHTML = html;
    div.addEventListener("click", (e) => {
      if (e.target.closest("[data-act]")) { e.stopPropagation(); n.open = !n.open; render(n); layout(); }
    });
    fo.append(div); g.append(fo);
    const h = div.offsetHeight || 40;
    fo.setAttribute("y", -h / 2); fo.setAttribute("height", h + 2);
    n.w = w; n.h = h;
  }

  // ---------- model ----------
  function add(n) {
    if (byId[n.id]) { Object.assign(byId[n.id], n); render(byId[n.id]); schedule(); return byId[n.id]; }
    n.col = n.col ?? COL[n.id] ?? 0; n.x = n.x ?? colX(n.col); n.y = n.y ?? 0;
    nodes.push(n); byId[n.id] = n;
    n.el = el("g"); n.el.style.opacity = 0;
    n.el.ondblclick = (e) => {      // graph: details open on double click
      e.stopPropagation();
      if (n.justDragged) { n.justDragged = false; return; }       // a drag is not a click
      const h = typeof n.info === "function" ? n.info() : n.info; if (h) openInspector(h);
    };
    n.el.addEventListener("pointerdown", (e) => {                   // drag any node; its arrows follow
      if (e.button !== 0 || e.target.closest("button, a, [data-act]")) return;
      e.stopPropagation();
      drag = { n, x0: e.clientX, y0: e.clientY, nx: n.x, ny: n.y, moved: false };
    });
    gNodes.append(n.el); render(n); schedule();
    return n;
  }
  const upd = (id, patch) => { const n = byId[id]; if (n) { Object.assign(n, typeof patch === "function" ? patch(n) : patch); render(n); schedule(); } return n; };
  const hub = (id, status) => {
    const n = add({ id, kind: "hub", label: TITLES[id] });
    if (status && n.status !== status) upd(id, { status });
    return n;
  };
  function colX(c) { let x = 0; for (let i = 0; i < c; i++) x += COLW[i] + GAPX; return x + COLW[c] / 2; }

  // ---------- layout: columns, stage cards on top, items aligned by relation ----------
  let pending = false;
  function schedule() { if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; layout(); }); } }
  function layout() {
    if (!nodes) return;
    const stage = nodes.filter((n) => !n.item), topOf = {};
    let headH = 0;
    for (let c = 0; c < COLW.length; c++) {
      let y = 0;
      stage.filter((n) => n.col === c).forEach((n) => { n.x = colX(c); n.y = y + n.h / 2; y += n.h + GAPY; });
      topOf[c] = y; if (c !== 0 && c !== 5) headH = Math.max(headH, y);
    }
    const start = headH + HEAD_GAP;
    const hyps = nodes.filter((n) => n.card === "hypcard"), claimsOf = {};
    let y = start;
    for (const h of hyps) {          // evidence column: claims grouped by hypothesis, in hypothesis order
      const cs = nodes.filter((n) => n.card === "claim" && n.hyp === h.hid);
      claimsOf[h.id] = cs;
      if (!cs.length) continue;
      cs.forEach((c) => { c.x = colX(3); c.y = y + c.h / 2; y += c.h + 6; });
      y += 22;
    }
    place(hyps, (h) => { const cs = claimsOf[h.id]; return cs?.length ? (cs[0].y + cs[cs.length - 1].y) / 2 : null; }, colX(4), start);
    place(nodes.filter((n) => n.card === "source"),
      (s) => { const ys = (s.feeds || []).map((id) => byId[id]?.y).filter((v) => v != null); return ys.length ? ys.reduce((a, b) => a + b) / ys.length : null; }, colX(2), start);
    place(nodes.filter((n) => n.card === "q"), () => null, colX(0), topOf[0] + 10);
    for (const n of nodes) {
      if (n.manual) { n.x = n.manual.x; n.y = n.manual.y; }          // user-placed nodes stay where they were dropped
      n.el.setAttribute("transform", `translate(${n.x},${n.y})`); n.el.style.opacity = 1;
    }
    drawLinks();
    if (!userMoved) fit();
  }
  function place(list, want, x, minY) {   // desired y (or stacked), then sweep down so nothing overlaps
    const items = list.map((n, i) => ({ n, y: want(n) ?? Infinity, i })).sort((a, b) => a.y - b.y || a.i - b.i);
    let cur = minY;
    for (const it of items) {
      const top = it.y === Infinity ? cur : Math.max(cur, it.y - it.n.h / 2);
      it.n.x = x; it.n.y = top + it.n.h / 2; cur = top + it.n.h + GAPY;
    }
  }
  function curve(a, b, cls) {   // right edge of a -> left edge of b
    const x1 = a.x + a.w / 2, y1 = a.y, x2 = b.x - b.w / 2, y2 = b.y, mx = (x1 + x2) / 2;
    return el("path", { d: `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2 - 2} ${y2}`, class: "kg-link " + cls, "marker-end": "url(#kgArrow)" });
  }
  function drawLinks() {
    gLinks.innerHTML = "";
    for (const [a, b] of FLOW) {
      const A = byId[a], B = byId[b]; if (!A || !B) continue;
      if (A.col === B.col) gLinks.append(el("path", { d: `M ${A.x} ${A.y + A.h / 2} L ${B.x} ${B.y - B.h / 2 - 2}`, class: "kg-link flow", "marker-end": "url(#kgArrow)" }));
      else gLinks.append(curve(A, B, "flow"));
    }
    for (const n of nodes) {
      if (n.card === "claim" && byId[n.hypNode]) gLinks.append(curve(n, byId[n.hypNode], "rel " + n.cls));
      if (n.card === "claim") for (const a of n.also || []) if (byId["H:" + a.h]) gLinks.append(curve(n, byId["H:" + a.h], "rel faint " + a.cls));
      if (n.card === "source") for (const id of n.feeds || []) if (byId[id]) gLinks.append(curve(n, byId[id], "rel src"));
    }
  }

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
      else add({ id: "q" + e.i, item: true, card: "q", col: 0, label: d.question, info: `<p class="eyebrow">Question to the user</p><h2>${esc(d.question)}</h2>` });
    }
    if (stage === "interview" && e.status === "done") upd("goal", { qa: (d.qa || []).map((x) => ({ q: x.q, a: x.a })), done: true, sub: `${(d.qa || []).length} Q&A` });
    if (stage === "hypotheses" && e.status === "done") {
      const byH = {};
      (d.assumptions || []).forEach((a) => (byH[a.hypothesis] = byH[a.hypothesis] || []).push(a));
      (d.hypotheses || []).forEach((x) => add({ id: "H:" + x.id, hid: x.id, item: true, card: "hypcard", col: 4, label: x.text, prior: x.prior,
        assumptions: byH[x.id] || [], hist: [], info: () => hypInfo(byId["H:" + x.id]) }));
      upd("hyp", { items: d.hypotheses || [] }); upd("root", { sub: "researching…" });
    }
    if (stage === "plan" && e.status === "done") upd("plan", { tasks: (d.tasks || []).map((t) => ({ id: t.id, question: t.question, claims: 0 })) });
    if (stage === "search") upd("plan", { searching: e.status !== "done" });
    if (stage === "search" && e.status === "progress" && d.results) upd("src", (n) => ({ searches: (n.searches || 0) + 1 }));
    if (stage === "voi" && e.status === "done") upd("plan", (n) => {
      const key = (q) => q.toLowerCase().replace(/[^a-z ]/g, "").slice(0, 28);
      const have = new Set((n.tasks || []).map((t) => key(t.question))), room = 4 - (n.tasks || []).filter((t) => t.follow).length;
      const extra = (d.followups || []).filter((f) => !have.has(key(f.question)) && have.add(key(f.question))).slice(0, Math.max(0, room));
      return { tasks: [...(n.tasks || []), ...extra.map((f) => ({ id: f.id, question: f.question, claims: 0, follow: true }))] };
    });
    if (stage === "fetch" && e.status === "progress" && d.source) {
      const ok = /^Read/.test(e.title);
      upd("src", (n) => ({ read: (n.read || 0) + ok, failed: (n.failed || 0) + !ok }));
    }
    if (stage === "claims") upd("led", (n) => ({ steps: { ...(n.steps || {}), extract: e.status === "done" ? "done" : "run" } }));
    if (stage === "claims" && e.status === "done" && d.per_task) upd("plan", (n) => ({ tasks: (n.tasks || []).map((t) => ({ ...t, claims: Math.max(t.claims || 0, d.per_task[t.id] || 0) })) }));
    if (stage === "ledger" && e.status === "running") upd("led", (n) => ({ steps: { ...(n.steps || {}), fresh: "run", indep: "run", contra: "run" } }));
    if (stage === "ledger" && e.status === "done")
      upd("led", { claims: d.claims, clusters: d.clusters, stale: d.stale_claims, conflicts: d.conflicts || [], steps: { extract: "done", fresh: "done", indep: "done", contra: (d.conflicts || []).length ? "bad" : "done" } });
    if (stage === "belief" && e.status === "done") {
      (d.result?.hypotheses || []).forEach((x) => upd("H:" + x.id, (n) => ({ p: x.p, for: x.for, against: x.against, hist: [...(n.hist || []), x.p] })));
      upd("hyp", (n) => ({ items: (n.items || []).map((h) => ({ ...h, p: d.result?.hypotheses?.find((x) => x.id === h.id)?.p })), round: (n.round || 0) + 1 }));
      (d.assumptions || []).forEach((a) => upd("H:" + a.hypothesis, (n) => ({ assumptions: (n.assumptions || []).map((x) => (x.id === a.id ? { ...x, ...a } : x)) })));
      pendingEvidence = d.evidence || [];
      if (d.result?.verdict != null) { upd("root", { p: d.result.verdict }); byId.verdict && upd("verdict", { p: d.result.verdict }); }
      if (typeof D === "undefined" || !D) fetch(`/api/research/runs/${RUN}`).then((r) => r.json()).then(enrich).catch(() => {});
    }
    if (stage === "trial" && e.status === "done") {
      upd("trial", { roles: (d.panel || []).map((p) => p.title) });
      byId.trial.info = `<p class="eyebrow">Trial</p>` + (d.panel || []).map((p) => `<h3>${esc(p.title)}</h3>` + (p.points || []).map((x) => `<p>${esc(x.point)} ` +
        (x.cites || []).map((c) => `<button class="linkish" data-claim="${esc(c)}">${esc(c)}</button>`).join(" ") + `</p>`).join("")).join("");
    }
    if (stage === "report" && e.status === "done" && d.verdict) {
      upd("verdict", { p: d.verdict.p, lean: d.verdict.label, v: d.verification || {}, cruxes: (d.cruxes || []).slice(0, 3).map((c) => c.text || c.id) });
      upd("root", { p: d.verdict.p, lean: d.verdict.label });
    }
    if (stage === "complete") nodes.forEach((n) => n.status === "running" && upd(n.id, { status: "done" }));
  }

  // snapshot -> strongest claims per hypothesis (evidence column) and the sources they came from (sources column)
  function enrich(snap) {
    if (!nodes || !snap?.claims) return;
    const types = {};
    Object.values(snap.sources || {}).forEach((s) => { if (s.status === "fetched" || s.status === "snippet") types[s.type_label || s.type] = (types[s.type_label || s.type] || 0) + 1; });
    upd("src", { types });
    const evidence = (snap.events || []).filter((e) => e.stage === "belief" && e.status === "done").pop()?.data?.evidence || pendingEvidence;
    const per = {}, feeds = {};
    evidence.slice().sort((a, b) => b.strength - a.strength).forEach((x) => {
      if (!byId["H:" + x.hypothesis] || (per[x.hypothesis] = (per[x.hypothesis] || 0) + 1) > PER_HYP) return;
      const c = snap.claims[x.claim]; if (!c) return;
      const id = "C:" + x.claim;
      if (byId[id]) { const n = byId[id]; if (!n.also.some((a) => a.h === x.hypothesis) && n.hyp !== x.hypothesis) n.also.push({ h: x.hypothesis, cls: x.stance > 0 ? "pos" : "neg" }); return; }
      add({ id, item: true, card: "claim", col: 3, hyp: x.hypothesis, hypNode: "H:" + x.hypothesis, also: [], cls: x.stance > 0 ? "pos" : "neg", strength: x.strength,
        text: c.text, info: () => { claimInfo(x, c, snap); return null; } });
      (feeds[c.source] = feeds[c.source] || []).push(id);
    });
    for (const [sid, ids] of Object.entries(feeds)) {
      const s = snap.sources?.[sid] || {};
      add({ id: "S:" + sid, item: true, card: "source", col: 2, sid, domain: s.domain, stype: s.type, typeLabel: s.type_label ? s.type_label.split(" /")[0] : s.type,
        feeds: ids, info: () => { sourceInfo(sid, s); return null; } });
    }
    upd("src", { cited: Object.keys(feeds).length }); upd("led", { shown: true });
  }
  function claimInfo(x, c, snap) {
    if (typeof D !== "undefined" && D) return inspectClaim(x.claim);
    const s = snap.sources?.[c.source] || {};
    openInspector(`<p class="eyebrow">Claim ${esc(x.claim)} · ${x.stance > 0 ? "supports" : "opposes"} ${esc(x.hypothesis)} · strength ${pct(x.strength)}</p><blockquote>“${esc(c.text)}”</blockquote><p>Source: <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.domain || c.source)}</a></p>`);
  }
  function sourceInfo(sid, s) {
    if (typeof D !== "undefined" && D?.sources?.[sid]) return inspectSource(sid);
    openInspector(`<p class="eyebrow">Source ${esc(sid)} · ${esc(s.type_label || s.type || "")}</p><h2>${esc(s.title || s.domain || "")}</h2><p><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a></p>`);
  }
  function hypInfo(n) {
    return `<p class="eyebrow">Hypothesis ${esc(n.hid)} · ${n.p != null ? pct(n.p) : "prior " + pct(n.prior ?? 0.5)}</p><h2>${esc(n.label)}</h2>` +
      `<p>▲ ${n.for || 0} supporting · ▼ ${n.against || 0} opposing independent clusters</p>` +
      ((n.assumptions || []).length ? `<h3>Assumptions</h3>${n.assumptions.map((a) => `<p><b>~${pct(a.p)}</b> ${esc(a.text)}</p>`).join("")}` : "");
  }

  // ---------- view ----------
  let T = { x: 0, y: 0, k: 1 }, userMoved = false, drag = null;
  function applyView() {
    // keep at least part of the graph on screen: wheel / drag could push it fully out of view (looked like a black-out)
    if (nodes?.length && svg.clientWidth) {
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      for (const a of nodes) { x0 = Math.min(x0, a.x - a.w / 2); y0 = Math.min(y0, a.y - a.h / 2); x1 = Math.max(x1, a.x + a.w / 2); y1 = Math.max(y1, a.y + a.h / 2); }
      const W = svg.clientWidth, H = svg.clientHeight, m = 120;
      T.x = Math.min(Math.max(T.x, m - x1 * T.k), W - m - x0 * T.k);
      T.y = Math.min(Math.max(T.y, m - y1 * T.k), H - m - y0 * T.k);
    }
    view.setAttribute("transform", `translate(${T.x},${T.y}) scale(${T.k})`);
  }
  function fit() {
    if (!nodes?.length) return;
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const a of nodes) { x0 = Math.min(x0, a.x - a.w / 2); y0 = Math.min(y0, a.y - a.h / 2); x1 = Math.max(x1, a.x + a.w / 2); y1 = Math.max(y1, a.y + a.h / 2); }
    const W = svg.clientWidth || 1000, H = (svg.clientHeight || 700) - 60, pad = 20;
    T.k = Math.min(1, Math.max(0.6, W / (x1 - x0 + pad * 2)));   // fit the width at a readable size; scroll for the rest
    T.x = Math.max(pad, (W - (x1 - x0) * T.k) / 2) - x0 * T.k; T.y = 20 - y0 * T.k; applyView();
  }
  function panZoom(host) {
    let pan = null;
    svg.addEventListener("wheel", (e) => {
      e.preventDefault(); userMoved = true;
      if (!e.ctrlKey && !e.metaKey) { T.x -= e.shiftKey ? e.deltaY : e.deltaX; T.y -= e.shiftKey ? 0 : e.deltaY; return applyView(); }   // wheel scrolls, ctrl/⌘+wheel zooms
      const r = svg.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, k2 = Math.min(2.5, Math.max(0.2, T.k * (e.deltaY < 0 ? 1.12 : 0.89)));
      T.x = mx - (mx - T.x) * (k2 / T.k); T.y = my - (my - T.y) * (k2 / T.k); T.k = k2; applyView();   // zoom around the cursor
    }, { passive: false });
    svg.addEventListener("pointerdown", (e) => { if (!e.target.closest(".kg-node")) { userMoved = true; pan = { x: e.clientX - T.x, y: e.clientY - T.y }; } });
    window.addEventListener("pointermove", (e) => { if (pan) { T.x = e.clientX - pan.x; T.y = e.clientY - pan.y; applyView(); } });
    window.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = (e.clientX - drag.x0) / T.k, dy = (e.clientY - drag.y0) / T.k;
      if (!drag.moved && Math.hypot(dx, dy) < 4) return;
      drag.moved = true; userMoved = true;
      const n = drag.n;
      n.x = drag.nx + dx; n.y = drag.ny + dy; n.manual = { x: n.x, y: n.y };
      n.el.style.transition = "none";
      n.el.setAttribute("transform", `translate(${n.x},${n.y})`);
      drawLinks();
    });
    window.addEventListener("pointerup", () => {
      pan = null;
      if (drag) { if (drag.moved) drag.n.justDragged = true; drag.n.el.style.transition = ""; drag = null; }
    });
    new ResizeObserver(() => !userMoved && fit()).observe(host);
  }

  function refresh() { if (!nodes) return; nodes.forEach(render); layout(); }
  if (document.fonts) document.fonts.ready.then(refresh);
  return { mount, reset, ev, enrich, refresh, fit: () => { userMoved = false; fit(); } };
})();

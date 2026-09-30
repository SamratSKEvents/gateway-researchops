// Live research graph: one central question card; stages, hypotheses, tasks, sources, evidence and the trial branch out
// from it as events arrive. Each node's shape carries meaning (cards with progress, chips, dots, ▲/▼ evidence, diamonds for
// conflicts, a gauge for the verdict). Plain SVG + a tiny force layout (no library, works offline).
const Graph = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const HUBS = {   // stage -> hub node
    interview: ["goal", "Goal interview"], await: ["goal", "Goal interview"], hypotheses: ["hyp", "Hypotheses"], belief: ["hyp", "Hypotheses"],
    plan: ["plan", "Research plan"], voi: ["plan", "Research plan"], search: ["src", "Sources"], select: ["src", "Sources"], fetch: ["src", "Sources"],
    claims: ["led", "Evidence ledger"], ledger: ["led", "Evidence ledger"], index: ["led", "Evidence ledger"],
    trial: ["trial", "Trial"], report: ["verdict", "Verdict"], complete: ["verdict", "Verdict"],
  };
  const LEN = { hub: 190, hyp: 150, task: 120, src: 70, ev: 70, role: 100, q: 120, asm: 110, conf: 90, info: 110 };
  const MAX_SRC = 60;
  const CW = 6.1;   // approx px per character at 11px
  let svg, gLinks, gNodes, nodes, byId, links, view, raf, running, seenFollow;

  function mount(el) {
    el.innerHTML = "";
    svg = document.createElementNS(NS, "svg"); svg.setAttribute("class", "kg");
    view = document.createElementNS(NS, "g"); gLinks = document.createElementNS(NS, "g"); gNodes = document.createElementNS(NS, "g");
    view.append(gLinks, gNodes); svg.append(view); el.append(svg);
    const legend = document.createElement("div"); legend.className = "kg-legend";
    legend.innerHTML = [["card", "stage (live status)"], ["hypc", "hypothesis + probability"], ["chip", "research task"], ["dot", "source"],
      ["up", "supports"], ["down", "opposes"], ["dia", "conflict / crux"], ["badge", "trial role"]].map(([c, t]) => `<span><i class="lg-${c}"></i>${t}</span>`).join("");
    const fitBtn = document.createElement("button"); fitBtn.className = "kg-fit"; fitBtn.textContent = "Fit"; fitBtn.onclick = () => { userMoved = false; fit(); };
    el.append(legend, fitBtn);
    panZoom(el);
  }

  function reset(query) {
    nodes = []; byId = {}; links = []; running = {}; seenFollow = new Set();
    gLinks.innerHTML = ""; gNodes.innerHTML = ""; T = { x: 0, y: 0, k: 1 }; userMoved = false; applyView();
    add({ id: "root", kind: "root", label: query, info: `<p class="eyebrow">Research question</p><h2>${esc(query)}</h2>` });
    kick();
  }

  // ---------- svg helpers ----------
  const el = (tag, attrs = {}, text) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    return e;
  };
  function wrap(text, maxChars, maxLines) {
    const words = String(text).split(/\s+/), lines = [];
    let cur = "";
    for (const w of words) {
      if ((cur + " " + w).trim().length > maxChars) { lines.push(cur); cur = w; if (lines.length === maxLines) break; }
      else cur = (cur + " " + w).trim();
    }
    if (lines.length < maxLines && cur) lines.push(cur);
    if (lines.length === maxLines && words.join(" ").length > lines.join(" ").length) lines[maxLines - 1] = lines[maxLines - 1].replace(/.{0,2}$/, "…");
    return lines;
  }
  function textBlock(g, lines, x, y, cls, lh = 14) { lines.forEach((l, i) => g.append(el("text", { x, y: y + i * lh, class: cls }, l))); }
  function bar(g, x, y, w, p, cls) {
    g.append(el("rect", { x, y, width: w, height: 5, rx: 2.5, class: "kg-bar-bg" }));
    g.append(el("rect", { x, y, width: Math.max(0, Math.min(1, p)) * w, height: 5, rx: 2.5, class: "kg-bar " + (cls || "") }));
  }
  const pcls = (p) => (p >= 0.6 ? "good" : p <= 0.4 ? "bad" : "mid");

  // ---------- rendering by kind ----------
  function render(n) {
    const g = n.el; g.innerHTML = "";
    g.setAttribute("class", `kg-node ${n.kind} ${n.cls || ""} ${n.status || ""}`);
    g.append(el("title", {}, n.label));
    const R = RENDER[n.kind] || RENDER.dot;
    R(n, g);
  }
  const RENDER = {
    root(n, g) {       // question card + live verdict bar
      const lines = wrap(n.label, 34, 3), w = 250, h = 34 + lines.length * 16 + (n.p != null ? 26 : 0);
      g.append(el("rect", { x: -w / 2, y: -h / 2, width: w, height: h, rx: 14, class: "kg-shape" }));
      g.append(el("text", { x: -w / 2 + 14, y: -h / 2 + 18, class: "kg-eyebrow" }, "RESEARCH QUESTION"));
      textBlock(g, lines, -w / 2 + 14, -h / 2 + 36, "kg-title", 16);
      if (n.p != null) {
        const y = h / 2 - 16;
        bar(g, -w / 2 + 14, y, w - 90, n.p, pcls(n.p));
        g.append(el("text", { x: w / 2 - 14, y: y + 6, class: "kg-pct", "text-anchor": "end" }, `${Math.round(n.p * 100)}%`));
      }
      n.w = w; n.h = h;
    },
    hub(n, g) {        // stage card: title, live status line, optional progress bar
      const w = 190, h = n.progress ? 62 : 48;
      g.append(el("rect", { x: -w / 2, y: -h / 2, width: w, height: h, rx: 10, class: "kg-shape" }));
      g.append(el("circle", { cx: -w / 2 + 14, cy: -h / 2 + 16, r: 4.5, class: "kg-status" }));
      g.append(el("text", { x: -w / 2 + 26, y: -h / 2 + 20, class: "kg-title" }, n.label));
      g.append(el("text", { x: -w / 2 + 12, y: -h / 2 + 38, class: "kg-sub" }, (n.sub || (n.status === "running" ? "working…" : "")).slice(0, 30)));
      if (n.progress) {
        const [ok, bad] = n.progress, tot = ok + bad || 1, bw = w - 24;
        g.append(el("rect", { x: -w / 2 + 12, y: h / 2 - 14, width: bw, height: 5, rx: 2.5, class: "kg-bar-bg" }));
        g.append(el("rect", { x: -w / 2 + 12, y: h / 2 - 14, width: bw * ok / tot, height: 5, rx: 2.5, class: "kg-bar good" }));
        g.append(el("rect", { x: -w / 2 + 12 + bw * ok / tot, y: h / 2 - 14, width: bw * bad / tot, height: 5, class: "kg-bar bad" }));
      }
      n.w = w; n.h = h;
    },
    verdict(n, g) {    // gauge
      const r = 38, p = n.p ?? 0, a = Math.PI * (1 - p), x = Math.cos(a) * r, y = -Math.sin(a) * r;
      g.append(el("rect", { x: -70, y: -58, width: 140, height: 96, rx: 12, class: "kg-shape" }));
      g.append(el("path", { d: `M ${-r} 0 A ${r} ${r} 0 0 1 ${r} 0`, class: "kg-gauge-bg" }));
      if (n.p != null) g.append(el("path", { d: `M ${-r} 0 A ${r} ${r} 0 0 1 ${x} ${y}`, class: "kg-gauge " + pcls(p) }));
      g.append(el("text", { x: 0, y: -4, class: "kg-big", "text-anchor": "middle" }, n.p != null ? `${Math.round(p * 100)}%` : "…"));
      g.append(el("text", { x: 0, y: 26, class: "kg-sub", "text-anchor": "middle" }, n.sub || (n.status === "running" ? "deciding…" : "Verdict")));
      n.w = 140; n.h = 96;
    },
    hyp(n, g) {        // hypothesis card with probability bar
      const lines = wrap(n.label, 30, 2), w = 200, h = 22 + lines.length * 14 + 14;
      g.append(el("rect", { x: -w / 2, y: -h / 2, width: w, height: h, rx: 8, class: "kg-shape" }));
      textBlock(g, lines, -w / 2 + 10, -h / 2 + 17, "kg-text");
      const p = n.p ?? n.prior ?? 0.5;
      bar(g, -w / 2 + 10, h / 2 - 12, w - 56, p, n.p == null ? "prior" : pcls(p));
      g.append(el("text", { x: w / 2 - 10, y: h / 2 - 6, class: "kg-pct", "text-anchor": "end" }, `${Math.round(p * 100)}%`));
      n.w = w; n.h = h;
    },
    task(n, g) {       // one-line chip
      const t = n.label.length > 34 ? n.label.slice(0, 32) + "…" : n.label, w = t.length * CW + 20, h = 22;
      g.append(el("rect", { x: -w / 2, y: -h / 2, width: w, height: h, rx: 11, class: "kg-shape" }));
      g.append(el("text", { x: 0, y: 4, class: "kg-chip", "text-anchor": "middle" }, t));
      n.w = w; n.h = h;
    },
    q(n, g) {          // speech bubble: a question put to the user
      const lines = wrap(n.label, 30, 2), w = 196, h = 12 + lines.length * 14;
      g.append(el("path", { d: `M ${-w / 2} ${-h / 2} h ${w} v ${h} h ${-w + 26} l -10 9 v -9 h -16 z`, class: "kg-shape" }));
      textBlock(g, lines, -w / 2 + 9, -h / 2 + 15, "kg-text");
      n.w = w; n.h = h + 9;
    },
    asm(n, g) { RENDER.task(n, g); },
    role(n, g) {       // trial badge
      const w = n.label.length * 6.6 + 30, h = 26;
      g.append(el("rect", { x: -w / 2, y: -h / 2, width: w, height: h, rx: 6, class: "kg-shape" }));
      g.append(el("text", { x: 0, y: 4, class: "kg-chip", "text-anchor": "middle" }, n.label));
      n.w = w; n.h = h;
    },
    info(n, g) {       // verification: stacked bar supported / partial / struck
      const v = n.v || {}, tot = v.statements || 1, w = 170, bw = w - 20;
      g.append(el("rect", { x: -w / 2, y: -22, width: w, height: 44, rx: 8, class: "kg-shape" }));
      g.append(el("text", { x: -w / 2 + 10, y: -6, class: "kg-sub" }, `Citations verified ${v.supported ?? 0}/${v.statements ?? 0}`));
      let x = -w / 2 + 10;
      [["supported", "good"], ["partial", "mid"], ["struck", "bad"]].forEach(([k, c]) => {
        const ww = bw * (v[k] || 0) / tot; g.append(el("rect", { x, y: 6, width: ww, height: 7, class: "kg-bar " + c })); x += ww;
      });
      n.w = w; n.h = 44;
    },
    conf(n, g) {       // diamond: conflict (red) or crux (accent)
      g.append(el("path", { d: "M 0 -9 L 9 0 L 0 9 L -9 0 Z", class: "kg-shape" }));
      n.w = n.h = 18;
    },
    ev(n, g) {         // ▲ supports / ▼ opposes, size = strength
      const s = 4 + (n.strength || 0.5) * 5;
      g.append(el("path", { d: n.cls === "pos" ? `M 0 ${-s} L ${s} ${s * 0.8} L ${-s} ${s * 0.8} Z` : `M 0 ${s} L ${s} ${-s * 0.8} L ${-s} ${-s * 0.8} Z`, class: "kg-shape" }));
      n.w = n.h = s * 2;
    },
    dot(n, g) { g.append(el("circle", { r: 5, class: "kg-shape" })); n.w = n.h = 10; },
  };

  // ---------- model ----------
  function add(n) {
    if (byId[n.id]) { Object.assign(byId[n.id], n); render(byId[n.id]); return byId[n.id]; }
    const p = n.parent && byId[n.parent];
    const a = Math.random() * 6.283;
    Object.assign(n, { x: p ? p.x + Math.cos(a) * 30 : 0, y: p ? p.y + Math.sin(a) * 30 : 0, vx: 0, vy: 0 });
    if (n.kind === "root") n.fixed = true;
    nodes.push(n); byId[n.id] = n;
    if (p) {
      const l = { s: p, t: n, len: LEN[n.kind] || 90, el: el("line", { class: "kg-link " + (n.linkClass || "") }) };
      gLinks.append(l.el); links.push(l);
    }
    n.el = el("g");
    n.el.onclick = (e) => { e.stopPropagation(); if (n.info) openInspector(n.info); };
    dragNode(n);
    gNodes.append(n.el); render(n); kick();
    return n;
  }
  const upd = (id, patch) => { const n = byId[id]; if (n) { Object.assign(n, patch); render(n); } return n; };
  const hub = (stage, status) => {
    const h = HUBS[stage]; if (!h) return null;
    const n = add({ id: h[0], kind: h[0] === "verdict" ? "verdict" : "hub", label: h[1], parent: "root" });
    if (status && n.status !== status) upd(n.id, { status });
    return n;
  };

  // ---------- events -> graph ----------
  function ev(e) {
    if (!nodes) return;
    const stage = e.stage, d = e.data || {};
    const h = hub(stage, e.status === "running" ? "running" : e.status === "done" || e.status === "waiting" ? "done" : null);
    if (h && e.status !== "progress") {
      h.info = `<p class="eyebrow">${esc(stage)} · t=${e.t}s</p><h2>${esc(e.title)}</h2><p>${esc(e.summary || "")}</p>`;
      if (e.status === "running") upd(h.id, { sub: e.title.replace(/^Round \d+ \S+ /, "").slice(0, 30) });
    }

    if (stage === "await" && e.status === "waiting" && d.question) {
      add({ id: "q" + e.i, kind: "q", parent: d.kind === "interview" ? "goal" : "hyp", label: d.question,
            info: `<p class="eyebrow">Question to the user</p><h2>${esc(d.question)}</h2>` });
    }
    if (stage === "interview" && e.status === "done") upd("goal", { sub: `goal confirmed · ${(d.qa || []).length} answer(s)` });
    if (stage === "hypotheses" && e.status === "done") {
      (d.hypotheses || []).forEach((x) => add({ id: x.id, kind: "hyp", parent: "hyp", label: x.text, prior: x.prior, info: hypInfo(x) }));
      (d.assumptions || []).forEach((a) => add({ id: a.id, kind: "asm", parent: byId[a.hypothesis] ? a.hypothesis : "hyp", label: "Assumes: " + a.text,
        linkClass: "dash", info: `<p class="eyebrow">Assumption · ~${Math.round(a.p * 100)}%</p><h2>${esc(a.text)}</h2>` }));
      upd("hyp", { sub: `${(d.hypotheses || []).length} hypotheses · ${(d.assumptions || []).length} assumptions` });
    }
    if (stage === "plan" && e.status === "done") {
      (d.tasks || []).forEach((t) => add({ id: t.id, kind: "task", parent: "plan", label: t.question,
        info: `<p class="eyebrow">Research task ${esc(t.id)}</p><h2>${esc(t.question)}</h2><p>Search: “${esc(t.q)}”</p>` }));
      upd("plan", { sub: `${(d.tasks || []).length} tasks` });
    }
    if (stage === "voi" && e.status === "done")
      (d.followups || []).forEach((f) => {
        const key = f.question.toLowerCase().slice(0, 40);
        if (seenFollow.has(key) || seenFollow.size >= 8) return;
        seenFollow.add(key); add({ id: f.id, kind: "task", cls: "follow", linkClass: "dash", parent: byId[f.hypothesis] ? f.hypothesis : "plan",
        label: "↳ " + f.question, info: `<p class="eyebrow">Follow-up (value of information)</p><h2>${esc(f.question)}</h2>` });
      });
    if (stage === "search" && e.status === "progress" && e.data?.results) {
      const s = byId.src; if (s) upd("src", { searches: (s.searches || 0) + 1, sub: `${(s.searches || 0) + 1} searches` });
    }
    if (stage === "fetch" && e.status === "progress" && d.source) {
      const ok = /^Read/.test(e.title), s = byId.src, pr = s.progress || [0, 0];
      pr[ok ? 0 : 1]++;
      upd("src", { progress: pr, sub: `${pr[0]} read · ${pr[1]} unreadable` });
      if (pr[0] + pr[1] <= MAX_SRC) add({ id: "s:" + d.source, kind: "dot", parent: "src", cls: ok ? "" : "bad", label: `${e.title} — ${e.summary || ""}`,
        info: `<p class="eyebrow">Source ${esc(d.source)}</p><h2>${esc(e.title)}</h2><p><a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.url)}</a></p><p>${esc(e.summary || "")}</p>` });
    }
    if (stage === "ledger" && e.status === "done") {
      upd("led", { sub: `${d.claims} claims · ${d.clusters} independent` });
      (d.conflicts || []).slice(0, 4).forEach((c) => add({ id: `conf${c.a}${c.b}`, kind: "conf", parent: "led",
        label: `Conflict: ${c.measure} ${(c.values || []).join(" vs ")}`, info: `<p class="eyebrow">Contradiction between sources</p><h2>${esc(c.measure)}: ${esc((c.values || []).join(" vs "))}</h2><p>Claims ${esc(c.a)} and ${esc(c.b)}</p>` }));
    }
    if (stage === "belief" && e.status === "done") {
      (d.result?.hypotheses || d.hypotheses || []).forEach((x) => x.p != null && upd(x.id, { p: x.p }));
      const per = {};
      (d.evidence || []).slice().sort((a, b) => b.strength - a.strength).forEach((x) => {
        per[x.hypothesis] = (per[x.hypothesis] || 0) + 1;
        if (per[x.hypothesis] > 6 || !byId[x.hypothesis]) return;
        add({ id: "e:" + x.claim + x.hypothesis, kind: "ev", parent: x.hypothesis, cls: x.stance > 0 ? "pos" : "neg", strength: x.strength,
          label: `${x.stance > 0 ? "Supports" : "Opposes"} (${Math.round(x.strength * 100)}%) · claim ${x.claim}`,
          info: `<button class="linkish" data-claim="${esc(x.claim)}">Open claim ${esc(x.claim)}</button><p>${x.stance > 0 ? "Supports" : "Opposes"} ${esc(x.hypothesis)}, strength ${Math.round(x.strength * 100)}%, reliability ${Math.round((x.reliability || 0) * 100)}%, freshness ${Math.round((x.freshness || 0) * 100)}%.</p>` });
      });
      if (d.result?.verdict != null) { upd("root", { p: d.result.verdict }); byId.verdict && upd("verdict", { p: d.result.verdict }); }
    }
    if (stage === "trial" && e.status === "done") {
      (d.panel || []).forEach((p) => add({ id: "role:" + p.role, kind: "role", parent: "trial", cls: p.role, label: p.title,
        info: `<p class="eyebrow">Trial · ${esc(p.title)}</p>` + (p.points || []).map((x) => `<p>${esc(x.point)}</p>`).join("") }));
      upd("trial", { sub: `${(d.panel || []).length} speakers` });
    }
    if (stage === "report" && e.status === "done" && d.verdict) {
      upd("verdict", { p: d.verdict.p, sub: d.verdict.label || "" }); upd("root", { p: d.verdict.p });
      add({ id: "verif", kind: "info", parent: "verdict", v: d.verification || {}, label: "Citation verification" });
      (d.cruxes || []).slice(0, 3).forEach((c, i) => add({ id: "crux" + i, kind: "conf", cls: "crux", parent: "verdict", label: "Crux: " + (c.text || c.id),
        info: `<p class="eyebrow">Crux — could flip the verdict</p><h2>${esc(c.text || c.id)}</h2>` }));
    }
    if (stage === "complete") Object.values(byId).forEach((n) => n.status === "running" && upd(n.id, { status: "done" }));
  }
  function hypInfo(x) { return `<p class="eyebrow">Hypothesis ${esc(x.id)} · prior ${Math.round((x.prior ?? 0.5) * 100)}%</p><h2>${esc(x.text)}</h2>`; }

  // ---------- layout ----------
  let alpha = 1;
  function kick() { if (!raf) { alpha = 1; raf = requestAnimationFrame(tick); } else alpha = Math.max(alpha, 0.6); }
  function tick() {
    const n = nodes.length;
    for (let i = 0; i < n; i++) {          // size-aware repulsion  // ponytail: O(n²), fine for a few hundred nodes
      const a = nodes[i], ra = Math.max(a.w || 10, a.h || 10) / 2;
      for (let j = i + 1; j < n; j++) {
        const b = nodes[j], rb = Math.max(b.w || 10, b.h || 10) / 2;
        let dx = b.x - a.x, dy = b.y - a.y, d2 = dx * dx + dy * dy || 0.01;
        if (d2 > 360000) continue;
        const d = Math.sqrt(d2), gap = d - ra - rb;
        const f = (gap < 0 ? 2.5 - gap * 0.08 : 1400 / (gap * gap + 400)) * alpha;
        dx /= d; dy /= d; a.vx -= dx * f; a.vy -= dy * f; b.vx += dx * f; b.vy += dy * f;
      }
    }
    for (const l of links) {                // springs to parent
      const dx = l.t.x - l.s.x, dy = l.t.y - l.s.y, d = Math.sqrt(dx * dx + dy * dy) || 0.01, f = (d - l.len) * 0.035 * alpha;
      l.t.vx -= dx / d * f; l.t.vy -= dy / d * f; l.s.vx += dx / d * f * 0.25; l.s.vy += dy / d * f * 0.25;
    }
    for (const a of nodes) {
      if (a.fixed || a === dragging) { a.vx = a.vy = 0; continue; }
      a.vx = (a.vx - a.x * 0.0015 * alpha) * 0.8; a.vy = (a.vy - a.y * 0.0015 * alpha) * 0.8;
      a.x += a.vx; a.y += a.vy;
    }
    for (const l of links) { l.el.setAttribute("x1", l.s.x); l.el.setAttribute("y1", l.s.y); l.el.setAttribute("x2", l.t.x); l.el.setAttribute("y2", l.t.y); }
    for (const a of nodes) a.el.setAttribute("transform", `translate(${a.x},${a.y})`);
    alpha *= 0.985;
    if (!userMoved && ++frame % 20 === 0) fit();
    raf = alpha > 0.02 || dragging ? requestAnimationFrame(tick) : null;
  }

  // ---------- interaction ----------
  let T = { x: 0, y: 0, k: 1 }, dragging = null, userMoved = false, frame = 0;
  function applyView() {
    const w = svg.clientWidth || 800, h = svg.clientHeight || 600;
    view.setAttribute("transform", `translate(${w / 2 + T.x},${h / 2 + T.y}) scale(${T.k})`);
  }
  function fit() {   // keep the whole graph in view until the user pans/zooms
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const a of nodes) {
      x0 = Math.min(x0, a.x - (a.w || 10) / 2); y0 = Math.min(y0, a.y - (a.h || 10) / 2);
      x1 = Math.max(x1, a.x + (a.w || 10) / 2); y1 = Math.max(y1, a.y + (a.h || 10) / 2);
    }
    const w = svg.clientWidth || 800, h = (svg.clientHeight || 600) - 50, pad = 30;
    T.k = Math.min(1.3, Math.max(0.2, Math.min(w / (x1 - x0 + pad * 2), h / (y1 - y0 + pad * 2))));
    T.x = -((x0 + x1) / 2) * T.k; T.y = -((y0 + y1) / 2) * T.k - 20; applyView();
  }
  function panZoom(host) {
    let pan = null;
    svg.addEventListener("wheel", (e) => { e.preventDefault(); userMoved = true; T.k = Math.min(3, Math.max(0.2, T.k * (e.deltaY < 0 ? 1.1 : 0.9))); applyView(); }, { passive: false });
    svg.addEventListener("pointerdown", (e) => { if (e.target === svg) { userMoved = true; pan = { x: e.clientX - T.x, y: e.clientY - T.y }; } });
    window.addEventListener("pointermove", (e) => {
      if (pan) { T.x = e.clientX - pan.x; T.y = e.clientY - pan.y; applyView(); }
      if (dragging) {
        const r = svg.getBoundingClientRect();
        dragging.x = (e.clientX - r.left - r.width / 2 - T.x) / T.k; dragging.y = (e.clientY - r.top - r.height / 2 - T.y) / T.k; kick();
      }
    });
    window.addEventListener("pointerup", () => { pan = null; if (dragging) { dragging.fixed = dragging.kind === "root" || dragging.pinned; dragging = null; } });
    new ResizeObserver(applyView).observe(host);
  }
  function dragNode(n) { n.el.addEventListener("pointerdown", (e) => { e.stopPropagation(); dragging = n; n.pinned = true; kick(); }); }

  return { mount, reset, ev, fit: () => { userMoved = false; fit(); } };
})();

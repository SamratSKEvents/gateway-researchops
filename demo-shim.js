// Demo shim: answers the app's API calls from recorded JSON so the UI runs on GitHub Pages without a backend.
(() => {
  const RUNS = ["b3a11b1b86", "6a6f0be752"];
  const J = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { "Content-Type": "application/json" } });
  const file = (p) => fetch_(`demo/${p}`);
  const fetch_ = window.fetch.bind(window);
  const live = (what) => J({ error: `${what} needs the live backend — run ResearchOps locally (see README).`, demo: true }, 503);
  window.fetch = async (url, opt = {}) => {
    const u = new URL(url, location.href), p = u.pathname.replace(/^.*?\/api\//, "/api/"), post = (opt.method || "GET") === "POST";
    if (!p.startsWith("/api/")) return fetch_(url, opt);
    if (p === "/api/research/runs") return file("runs.json");
    if (p === "/api/research/health") return file("health.json");
    if (p === "/api/research" && post) return live("Starting new research");
    if (p.startsWith("/api/memory")) return file(`${RUNS[0]}/memory.json`);
    if (p.startsWith("/api/ai/usage")) return J({ runtime: { model: "recorded" }, usage: {} });
    const m = p.match(/^\/api\/research\/runs\/(\w+)(\/.*)?$/); if (!m) return J({}, 404);
    const [, rid, rest = ""] = m;
    if (!RUNS.includes(rid)) return J({ detail: "not in demo" }, 404);
    if (rest === "") return file(`${rid}/run.json`);
    if (rest.startsWith("/report.pdf")) return file(`${rid}/report.pdf`);
    if (rest.startsWith("/deck.pptx")) return file(`${rid}/deck.pptx`);
    if (rest === "/economics/simulate") {
      const sims = await (await file(`${rid}/simulate.json`)).json(), ov = JSON.parse(opt.body || "{}").overrides || {};
      const n = Object.keys(ov).length; if (!n) return J(sims.likely);
      const ec = (await (await file(`${rid}/economics.json`)).json()).economics.params;
      const isWorst = Object.entries(ov).every(([k, v]) => v === ec[k][{ price: "low", variable_cost: "high", cac: "high", churn: "high", fixed_cost: "high" }[k]]);
      const isBest = Object.entries(ov).every(([k, v]) => v === ec[k][{ price: "high", variable_cost: "low", cac: "low", churn: "low", fixed_cost: "low" }[k]]);
      return J(isWorst ? sims.worst : isBest ? sims.best : { ...sims.likely, warnings: ["Demo: slider changes need the live backend; showing the likely case."] });
    }
    if (rest === "/ask" && post) {
      const q = JSON.parse(opt.body || "{}").question || "", recorded = await (await file(`${rid}/ask.json`)).json();
      const hit = recorded.find((r) => r.question.toLowerCase() === q.toLowerCase()) || recorded[0];
      return J({ ...hit, question: q, answer: [{ id: "a0", text: `Demo mode — showing a recorded answer to: "${hit.question}". Live questions need the backend.`, cites: [] }, ...hit.answer] });
    }
    if (rest === "/whatif/ask" && post) return file(`${rid}/whatif.json`);
    if (rest === "/whatif/fork" && post) return live("What-if sliders");
    if (post) return live("This action");
    return file(`${rid}${rest}.json`);
  };
  window.EventSource = class { constructor() {} close() {} addEventListener() {} };
})();

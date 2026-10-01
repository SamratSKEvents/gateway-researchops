# ResearchOps
### The autonomous research agent that puts its own findings on trial.

> Ask a business question. ResearchOps interviews you about what you are actually trying to decide, breaks the question into research tasks, reads the web in parallel, argues both sides in an evidence court, red-teams its own conclusion, and hands you a **verdict with odds**, the **facts that could flip it**, and a **verbatim source quote behind every sentence**.

---

## The problem

Before a company launches a product, enters a market or answers a competitor, someone has to research it. Today that means dozens of tabs, copy-pasted numbers and a summary nobody can verify.

AI "deep research" tools made this faster, but not more trustworthy. Benchmarks of commercial research agents show citation quality and factual accuracy are their weakest points: fabricated links, true statements attached to the wrong source, and essays that never say *how sure* they are or *what would change the answer*.

A decision-maker does not need an essay. They need to know **whether to act, how confident to be, and which single fact the decision hinges on**.

## The idea

ResearchOps treats research as a **structured investigation followed by a trial**:

| Instead of… | ResearchOps does… |
|---|---|
| One prompt, one essay | A **goal interview** that blocks until it understands the decision, then hypotheses you confirm |
| Links attached after writing | A **claim ledger** of verbatim quotes built *before* any writing; every sentence cites it |
| "Ten articles agree" | **Source independence**: syndicated copies of one press release count once |
| Silent disagreement | **Contradictions surfaced** side by side, re-researched, and argued in court |
| One model grading itself | A separate **GPU entailment model** verifies citations; an LLM only settles ambiguous cases |
| A number the model made up | A **transparent log-odds belief engine** computes every probability from weighted, independent, fresh evidence |
| A fixed plan | **Value-of-information autonomy**: it researches whatever gap would move the verdict most |
| "Trust me" | A **red-team autopsy** that tries to break the conclusion and scores whether it survives |

---

## What you get

### 🕸 Live research graph (the main screen)
The whole investigation as a left-to-right flow: question → plan → sources → evidence → hypotheses → trial → verdict. Stage cards are live checklists and progress panels; sources line up with the claims they produced, claims line up with the hypotheses they move. Drag any node; double-click for details.

### ⚖️ Verdict
Probability with a range, must-do / must-not-do actions, the **cruxes** (facts that would flip the decision), a **research-debt register** (what is still weak or unverified) and a **minority report** recording the dissent.

### 📊 Comparison matrix
Competitors × the attributes that matter for this decision (price, funding, fleet, model…). Every cell cites its claim; anything not stated in the evidence stays blank instead of being guessed.

### 🏛 Evidence court
Any claim can be put on trial. Exhibits are chosen by the entailment model (claims that support or contradict it), prosecution and defence argue in crisp cited points, the judge rules **Affirmed / Qualified / Overruled**, and every turn is citation-checked. Hearings can be **played aloud** with a voice per role.

### 🔬 Red-team autopsy
A panel of auditors (temporal, source quality, evidence alignment, contradictions, data quality, assumptions, bias, conclusion overreach, completeness, logic, alternative hypotheses, methodology) audits the finished research. A Red Team Director turns the findings into a **survival verdict** with a transparent score, a "what would change the conclusion" list and a follow-up research queue.

### 💰 Unit economics + Monte Carlo
Price, cost to serve, acquisition cost, churn and fixed cost are read **from cited claims** (or marked as explicit assumptions). Then: LTV, LTV/CAC, payback, breakeven, a **worst-case → best-case scenario table**, tail risk (value at risk, expected shortfall, probability of losing money per customer), a **tornado chart** of what moves the outcome most, and live sliders over thousands of simulated futures. Impossible inputs raise a warning instead of hiding.

### 🔮 What-if lab
Drag the assumptions the agent inferred *from your own goals* (no generic "risk appetite" fields), or ask in plain English — *"what if a competitor cuts prices by 30%?"* The LLM only maps the question onto the model; the belief engine recomputes the verdict and shows exactly what changed.

### 🗺 Action plan
A phased roadmap (validate → pilot → scale) where every phase has a **measurable go/no-go gate** tied to the cruxes.

### 💬 Ask (follow-ups with RAG)
Ask anything about the research. Answers are retrieved from the run's evidence and every page any run has read, cited, and verified. If the evidence does not cover the question, it says so and offers to research it deeper.

### 📄 Decision report & slide deck
A technical PDF report (framed engineering-style sheets, document control, numbered sections, stamps) and an executive `.pptx` deck — both built only from the run's records.

### 🧠 Research memory
Across every investigation: related past research ranked by relevance, recurring claims, reused sources, named entities, cross-run contradictions and open questions.

### Also
Agents & conversation transcript, planner (task tree, uncertainties, plan versions, budget), replay timeline, evidence by hypothesis, sources with their role in the verdict, progress stepper, light / dark mode.

---

## How it works

```
 Question + constraints (geography, scope, timeframe, depth)
        │
        ▼
 Goal interview ──▶ Hypotheses + inferred assumptions (you confirm)
        │
        ▼
 Planner ──▶ tasks routed to Market / Competitor / Customer / Regulation agents
        │
        ▼
 Round 0: broad parallel search ─▶ fetch ─▶ claim extraction (zero-shot classifier)
        │                                         │
        │                         ledger: freshness · independence · contradictions
        ▼                                         ▼
 Belief engine (log-odds) ◀── stance labels (entailment model, LLM for indirect evidence)
        │
        ▼
 Value of information ──▶ deep follow-up rounds on the highest-value gap
        │                 (asks you only if your answer would change the outcome)
        ▼
 Challenge & verify: challenger attacks key claims, verifier re-researches,
                     entailment + relevance gate + LLM confirmation rule on each
        │
        ▼
 Trial (advocate · challenger · witnesses · pre-mortem) ──▶ cited report, every line verified
        │
        ▼
 Background: evidence court · autopsy · comparison matrix · unit economics · action plan · entities
```

**Design principles**
- **The model reads; code decides.** LLMs extract, classify and argue. Probabilities, rulings and economics are computed by transparent code.
- **No regex for meaning.** Understanding text (claim types, relevance, junk filtering, task routing, duplicates) uses a GPU zero-shot classifier and embeddings; regexes only parse format.
- **Nothing un-cited.** Fabricated sources cannot enter the ledger — every claim carries a verbatim quote from a fetched page.
- **Honest about gaps.** Missing data becomes a visible gap, not a guess.

## Tech

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI, asyncio, Server-Sent Events |
| LLM | Any OpenAI-compatible endpoint — Groq (`gpt-oss-120b`, multi-key pool with per-agent keys and failover) or local Ollama (`qwen3`) |
| Verification & classification | DeBERTa-v3-large NLI on GPU (CUDA), zero-shot labels, `nomic-embed-text` embeddings |
| Search | SearXNG, DuckDuckGo, SerpApi, Reddit (PullPush), headless-browser and Web Archive fallbacks, disk cache |
| Storage | SQLite (documents, chunks, embeddings, claims), JSON run snapshots |
| Reports | Headless Chromium → PDF, python-pptx |
| Frontend | Plain HTML/CSS/JS, SVG graph with HTML cards — no build step |

## Observability
Every stage emits an event with the real data it produced (the live log). LLM token use is accounted per run (`/api/ai/usage`), search provider health is tracked, and an optional tokens-per-minute budget keeps hosted APIs under their rate limits.

---

## Setup

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/), an NVIDIA GPU (for the entailment model; the app falls back to the LLM without one), and either a Groq API key or [Ollama](https://ollama.com) running locally. Optional: SearXNG on `localhost:9090`, a SerpApi key.

1. Install dependencies:
   ```bash
   uv sync
   uv run playwright install chromium
   ```
2. Pull the embedding model (and a local LLM if not using Groq):
   ```bash
   ollama pull nomic-embed-text
   ollama pull qwen3:4b        # only for local LLM
   ```
3. Create `.env` in the project root:
   ```ini
   LLM_BASE_URL=https://api.groq.com/openai/v1
   LLM_MODEL=openai/gpt-oss-120b
   LLM_API_KEYS=key1,key2,key3
   LLM_TPM=8000
   EMBED_BASE_URL=http://localhost:11434/v1
   EMBED_MODEL=nomic-embed-text
   SERPAPI_KEY=your-serpapi-key   # optional
   ```
4. Run:
   ```bash
   uv run uvicorn backend.app:app --port 8765
   ```
   or on Windows: `powershell -ExecutionPolicy Bypass -File run.ps1`

   Open **http://localhost:8765/** — API docs at `/docs`.

5. Tests:
   ```bash
   uv run pytest -q backend
   ```

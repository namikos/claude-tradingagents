---
name: trading-debate
description: Runs the full multi-agent trading debate workflow on a ticker — spawns analyst team in parallel, runs bull/bear debate, trader synthesis, risk approval. Use when the user asks for trading analysis, a buy/sell decision, or invokes /analyze TICKER.
---

# Trading Debate Orchestrator

You are the **Lead** (Portfolio Manager) coordinating a team of 8 specialized trading agents. Use Claude Code Agent Teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` must be enabled) for parallel execution and inter-agent messaging.

## Inputs

The user supplies a ticker symbol (e.g., `NVDA`, `AAPL`). Substitute it for `{TICKER}` everywhere below.

`$ARGUMENTS` may also include the flags `--mode` and `--style`. See **Mode Dispatch** below for parsing rules.

## Mode Dispatch

Before doing anything else, parse `$ARGUMENTS` to extract:

- `--mode` ∈ {`quick`, `standard`, `deep`}, default **`standard`**
- `--style` ∈ {`council`, `value`, `growth`, `macro`, `contrarian`}, default **`council`**

Then **print a cost banner to the user before spawning anything**:

```
===
Mode: {mode} | Style: {style} | Estimated cost: $X-Y | ETA: N min
===
```

Use this lookup for the cost/ETA values:

| Mode | Estimated cost | ETA |
|---|---|---|
| quick | $1–2 | 2–3 min |
| standard | $3–5 | 6–8 min |
| deep | $7–15 | 10–15 min |

### Mode → which analysts to spawn

| Mode | Analyst team |
|---|---|
| quick | fundamentals-analyst, technical-analyst (skip news + sentiment) |
| standard | all 4 analysts |
| deep | all 4 analysts |

### Style + Mode → which personas to spawn

Persona subagents are invoked via the Agent tool with `subagent_type: {name}-persona` (e.g. `buffett-persona`, `wood-persona`).

Style buckets:

| Style | Personas |
|---|---|
| value | buffett, graham, munger, pabrai, burry |
| growth | wood, lynch, fisher |
| macro | druckenmiller, damodaran, jhunjhunwala |
| contrarian | burry, taleb, ackman |
| council | composition depends on mode (see below) |

For `style=council`, pick the persona set by mode:

- `quick` (3 personas): buffett, wood, taleb
- `standard` (5 personas): buffett, wood, druckenmiller, taleb, burry (one per investing bucket plus buffett)
- `deep` (13 personas, all): buffett, graham, munger, pabrai, burry, wood, lynch, fisher, druckenmiller, damodaran, jhunjhunwala, taleb, ackman

For non-council styles, take the listed personas — capped at 3 in `quick`, 5 in `standard`, all in `deep`.

### Mode → which phases run

| Mode | Bull/Bear debate | Risk-approval loop |
|---|---|---|
| quick | SKIP (trader synthesises analysts + personas directly, no debate, single risk pass-through with no iteration) | NO loop — risk-manager comments only, does not gate |
| standard | YES (1 round max) | YES (1 reject→revise iteration) |
| deep | YES (2 rounds max) | YES (2 reject→revise iterations) |

The Trader is **always** instructed to read every signal-bearing file in `state/` (analyst reports, persona reports, debate transcript if present) and aggregate the JSON Signal Footers from each. See `agents/trader.md` for the aggregation contract.

## Workflow

### Phase 0 — Setup

1. Confirm `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set. If not, abort and instruct user to enable it.
2. Ensure `state/` exists (`mkdir -p state`).
3. Create the team using natural-language intent. The teammate roster is **mode-dependent**:

   - `quick`: fundamentals-analyst, technical-analyst, trader, risk-manager + the 3 council personas (or styled persona set, capped at 3).
   - `standard`: all 4 analysts, bull-researcher, bear-researcher, trader, risk-manager + the 5 personas chosen by style.
   - `deep`: all 4 analysts, bull-researcher, bear-researcher, trader, risk-manager + all 13 personas (or the styled persona set).

   Example (standard, council):
   > "Create a trading-analysis agent team for ticker {TICKER}. Spawn these teammates: fundamentals-analyst, technical-analyst, news-analyst, sentiment-analyst, bull-researcher, bear-researcher, trader, risk-manager, buffett-persona, wood-persona, druckenmiller-persona, taleb-persona, burry-persona. Sonnet for analysts and personas; Opus for the decision roles."

### Phase 1 — Parallel Analyst + Persona Research

Create one shared task per active analyst AND one per active persona. They all run **in parallel**:

| Task | Owner | Output | Mode |
|---|---|---|---|
| `analyze-fundamentals-{TICKER}` | fundamentals-analyst | `state/{TICKER}_fundamentals.md` | all |
| `analyze-technical-{TICKER}` | technical-analyst | `state/{TICKER}_technical.md` | all |
| `analyze-news-{TICKER}` | news-analyst | `state/{TICKER}_news.md` | standard, deep |
| `analyze-sentiment-{TICKER}` | sentiment-analyst | `state/{TICKER}_sentiment.md` | standard, deep |
| `persona-{NAME}-{TICKER}` (one per active persona) | `{name}-persona` | `state/{TICKER}_persona_{name}.md` | mode-dependent count |

Each task prompt should include the ticker and explicit instruction to write to the state file. Each report — analyst or persona — must end with the JSON Signal Footer (see agent prompts).

**Wait for `TeammateIdle` from every spawned worker** before proceeding.

### Phase 2 — Bull/Bear Debate (standard + deep only)

**Skip this entire phase if `mode=quick`.** In quick mode, jump straight to Phase 3.

1. Create `state/{TICKER}_debate.md` with header `# Bull/Bear Debate — {TICKER}`.
2. Create task `bull-bear-debate-{TICKER}` blocked by all active analyst tasks (and ideally the persona tasks too).
3. Spawn (or activate) `bull-researcher` and `bear-researcher` simultaneously.
4. Instruct both: read all available analyst + persona reports, then debate via `SendMessage` directly with each other. Cap rounds by mode: **`standard` → 1 round**, **`deep` → 2 rounds**. Append every exchange to `state/{TICKER}_debate.md`.
5. Wait for both to write their `## Bull closing argument` and `## Bear closing argument` sections, each ending with the JSON Signal Footer (incl. `counter_arguments`).

### Phase 3 — Trader Decision (with Plan Approval)

1. Create task `trader-decision-{TICKER}` blocked by Phase 1 (and Phase 2, when present).
2. Activate `trader`. Instruct them to:
   - Read **every** signal-bearing file in `state/`: all `state/{TICKER}_*.md` (analysts + bull/bear if present) and all `state/{TICKER}_persona_*.md` (personas)
   - Extract the JSON Signal Footer from each and run the aggregation described in `agents/trader.md` (`## Step 1: Aggregate all JSON signals`)
   - Write the trade plan — with the `## Signal Aggregation` subsection at the top — to `state/{TICKER}_trader_plan.md`
   - Send the plan to `risk-manager` via `SendMessage` for approval

### Phase 4 — Risk Approval Loop

1. `risk-manager` reads the plan, runs the mandatory MCP hard-cap checks (`atr_stop`, `kelly_position_size`), replies APPROVED or REJECTED with feedback.
2. Iteration cap by mode: **`quick` → 0 iterations** (advisory only — risk-manager comments but does not block; trader's plan stands), **`standard` → 1 reject→revise iteration**, **`deep` → 2 reject→revise iterations**. If still rejected after the cap, accept the risk-manager's final position (likely HOLD with explanation).
3. On APPROVED (or in `quick` mode after the advisory pass): `risk-manager` writes `state/{TICKER}_decision.md` with the signed-off plan.

### Phase 5 — Synthesis (Lead)

After `state/{TICKER}_decision.md` exists, you (the Lead) produce the final user-facing summary:

```markdown
# Trading Analysis: {TICKER} — {DATE}

**Final Recommendation:** BUY / HOLD / SELL  
**Conviction:** low / medium / high  
**Time Horizon:** ...  
**Position Size:** ...%  
**Entry / Stop / Target:** ... / ... / ...

## How the team arrived here
- Fundamentals view: <one-line>
- Technical view: <one-line>
- News view: <one-line>
- Sentiment view: <one-line>
- Bull case (1 sentence): ...
- Bear case (1 sentence): ...
- Risk Manager: APPROVED / CONDITIONAL / REJECTED-and-revised

## Key risks to monitor
- ...

## Full reports
state/{TICKER}_fundamentals.md, _technical.md, _news.md, _sentiment.md, _debate.md, _trader_plan.md, _decision.md
```

### Phase 6 — Cleanup

Ask the team to clean up: `"Clean up the team"`. The Lead handles cleanup; do NOT have teammates do it.

## Failsafes

- **Alpha Vantage rate limit hit** (25/day free tier): one or more analysts may report missing data. Have them note the gap in their report and proceed with what they have. Don't abort the workflow.
- **Debate stalls** (Bull and Bear endlessly agreeing or talking past each other): force-conclude after 2 rounds. Tell them via the Lead session to write closing arguments now.
- **Plan-approval thrash** (>2 reject cycles): record the disagreement in `state/{TICKER}_decision.md` and surface it to the user — the Lead's job is to deliver an answer, not to force consensus.
- **Team spawn fails** (Agent Teams not enabled or incompatible Claude Code version): fall back to **sequential subagent invocation** (Agent tool, one role at a time) and skip the live mailbox debate — instead, have Bull and Bear write their cases sequentially to `state/{TICKER}_debate.md`.

## Disclaimer

Final user-facing output must include: *"Research output, not financial advice."*

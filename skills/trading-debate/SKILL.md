---
name: trading-debate
description: Runs the full multi-agent trading debate workflow on a ticker — spawns analyst team in parallel, runs bull/bear debate, trader synthesis, risk approval. Use when the user asks for trading analysis, a buy/sell decision, or invokes /analyze TICKER.
---

# Trading Debate Orchestrator

You are the **Lead** (Portfolio Manager) coordinating a team of 8 specialized trading agents. Use Claude Code Agent Teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` must be enabled) for parallel execution and inter-agent messaging.

## Inputs

The user supplies a ticker symbol (e.g., `NVDA`, `AAPL`). Substitute it for `{TICKER}` everywhere below.

## Workflow

### Phase 0 — Setup

1. Confirm `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set. If not, abort and instruct user to enable it.
2. Ensure `state/` exists (`mkdir -p state`).
3. Create the team using natural-language intent:
   > "Create a trading-analysis agent team for ticker {TICKER}. Spawn 8 teammates from these subagent definitions: fundamentals-analyst, technical-analyst, news-analyst, sentiment-analyst, bull-researcher, bear-researcher, trader, risk-manager. Use Sonnet for the 4 analysts; Opus for the 4 decision roles."

### Phase 1 — Parallel Analyst Research

Create 4 shared tasks and assign one to each analyst. They run **in parallel**:

| Task | Owner | Output |
|---|---|---|
| `analyze-fundamentals-{TICKER}` | fundamentals-analyst | `state/{TICKER}_fundamentals.md` |
| `analyze-technical-{TICKER}` | technical-analyst | `state/{TICKER}_technical.md` |
| `analyze-news-{TICKER}` | news-analyst | `state/{TICKER}_news.md` |
| `analyze-sentiment-{TICKER}` | sentiment-analyst | `state/{TICKER}_sentiment.md` |

Each task prompt should include the ticker and explicit instruction to write to the state file.

**Wait for all 4 `TeammateIdle` events** before proceeding.

### Phase 2 — Bull/Bear Debate

1. Create `state/{TICKER}_debate.md` with header `# Bull/Bear Debate — {TICKER}`.
2. Create task `bull-bear-debate-{TICKER}` blocked by all 4 analyst tasks.
3. Spawn (or activate) `bull-researcher` and `bear-researcher` simultaneously.
4. Instruct both: read all 4 analyst reports, then debate via `SendMessage` directly with each other. **Cap at 2 rounds.** Append every exchange to `state/{TICKER}_debate.md`.
5. Wait for both to write their `## Bull closing argument` and `## Bear closing argument` sections.

### Phase 3 — Trader Decision (with Plan Approval)

1. Create task `trader-decision-{TICKER}` blocked by `bull-bear-debate-{TICKER}`.
2. Activate `trader`. Instruct them to:
   - Read all 4 analyst reports + debate transcript
   - Write trade plan to `state/{TICKER}_trader_plan.md`
   - Send the plan to `risk-manager` via `SendMessage` for approval

### Phase 4 — Risk Approval Loop

1. `risk-manager` reads the plan, replies APPROVED or REJECTED with feedback.
2. **Loop max 2 iterations** — if still rejected, accept the risk-manager's final position (likely HOLD with explanation).
3. On APPROVED: `risk-manager` writes `state/{TICKER}_decision.md` with the signed-off plan.

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

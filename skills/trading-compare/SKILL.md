---
name: trading-compare
description: Run trading analyses on multiple tickers in parallel and produce a side-by-side comparison table with persona heatmap, signals, and recommended picks ranked by aggregate confidence.
allowed-tools: Agent, Read, Write, Edit, mcp__tradingagents__quote
---

# Trading Compare — Multi-Ticker Side-by-Side

You are the **Comparator**: you fan out N parallel `trading-debate` runs, then aggregate their state files into a single ranked comparison.

## Inputs

Parse `$ARGUMENTS`:

| Arg | Required | Default | Notes |
|---|---|---|---|
| `TICKERS` | yes (positional) | — | comma-separated, e.g. `NVDA,AMD,INTC`. Max **10**. |
| `--mode` | no | `quick` | `quick` \| `standard`. `deep` is REJECTED here — see Cost banner. |
| `--style` | no | `council` | `council` \| `value` \| `growth` \| `macro` \| `contrarian` (passed through to each `trading-debate` invocation). |

If more than 10 tickers are supplied, abort with: *"Max 10 tickers per compare. Trim the list and re-run."*

If `--mode deep` is requested, abort with: *"`deep` mode is too expensive for parallel compare. Run `/deep TICKER` separately on the top picks after this compare finishes."*

## Cost banner

Before doing anything else, print a banner of the form:

```
Comparing {N} tickers in {mode} mode (style: {style})
  → estimated cost: ${low}–${high}
  → estimated wall time: {N * eta_per} min
```

Use these per-ticker estimates:

| Mode | Cost / ticker | ETA / ticker |
|---|---|---|
| `quick` | $0.50–$1.50 | ~3 min |
| `standard` | $2.00–$5.00 | ~6 min |

If the **upper bound** of estimated cost exceeds **$25**, ASK THE USER to confirm before spawning. Do not assume.

## Parallel execution

1. Ensure `state/` exists (`mkdir -p state`).
2. For each ticker `T`, spawn an `Agent` call in parallel (one tool message containing N parallel `Agent` invocations). Each call:
   - `subagent_type: "general-purpose"` (or the project's debate-runner agent if available)
   - `description: "trading-debate {T}"`
   - `prompt`: *"Invoke the `trading-debate` skill on ticker {T} with `--mode {mode}` and `--style {style}`. Write all artifacts to state/ as the skill normally would. Return a one-line completion status."*
3. **Wait for all N to complete.** If your runtime supports a TaskList, mark each spawn as a task and poll for `TeammateIdle` / completion events. Otherwise, the parallel `Agent` calls already block until all return.
4. Track per-ticker outcome: `succeeded` or `failed (reason)`. Do NOT abort the whole compare on one failure.

## Aggregation

For every ticker `T` that succeeded, read the produced state files:

- `state/{T}_fundamentals.md`
- `state/{T}_technical.md`
- `state/{T}_news.md`
- `state/{T}_sentiment.md`
- All `state/{T}_persona_*.md` (zero or more, depending on `--style`)
- `state/{T}_decision.md` (final BUY/HOLD/SELL)

From each report, extract the **JSON Signal Footer** (every analyst/persona must end with one — see project conventions). Each footer has at least: `signal` (BUY/HOLD/SELL), `confidence` (0–100), and where applicable `fair_value` and `top_risk`.

Then compute, per ticker:

- `bullish_score` = sum over agents of `(signal_weight * confidence)` where `BUY=+1`, `HOLD=0`, `SELL=-1`, normalized to `-100..+100`
- `avg_confidence` = mean of `confidence` across all agents
- `agreement_pct` = `(# agents with BUY) / (# agents) * 100`
- `median_fair_value` = median of `fair_value` across agents that supplied one
- `current_price` = `mcp__tradingagents__quote(T)` (one fresh call per ticker)
- `upside_pct` = `(median_fair_value - current_price) / current_price * 100`
- `top_risk` = most-cited `top_risk` string across agents (frequency tiebreaker → highest-confidence agent's risk)

For tickers that **failed**, all numeric cells are `n/a`.

## Output

Write everything to `state/compare_{T1}_{T2}_{T3}_..._{Tn}.md` (truncate filename at 100 chars, drop later tickers if needed but keep them in the body).

The file contains, in order:

### 1. Header table

```markdown
| Ticker | Bullish % | Avg Conf | Median Fair Value | Current | Upside % | Top Risk |
|---|---|---|---|---|---|---|
| NVDA | +72 | 78 | $145.00 | $128.40 | +12.9% | China export controls |
| AMD  | +18 | 64 | $112.00 | $108.10 | +3.6%  | Margin compression |
| ...  | ... | ... | ... | ... | ... | ... |
```

Sort rows by `Bullish %` descending.

### 2. Persona / analyst heatmap

Rows = tickers, columns = each analyst + persona seen across the run. Cells encode signal and confidence as **ASCII** (no emojis — the project avoids them):

- `[+NN]` = BUY with confidence NN
- `[-NN]` = SELL with confidence NN
- `[ NN]` = HOLD with confidence NN (note the leading space for column alignment)
- `[ -- ]` = no signal / agent did not run

Example:

```markdown
|        | Fund | Tech | News | Sent | Bull | Bear | Buffett | Burry |
|--------|------|------|------|------|------|------|---------|-------|
| NVDA   | [+82]| [+75]| [+68]| [+71]| [+85]| [-55]| [+70]   | [-60] |
| AMD    | [+60]| [ 50]| [+55]| [+45]| [+65]| [-50]| [ 55]   | [-45] |
```

### 3. Ranked recommendations

```markdown
## Top picks

1. **NVDA** — strongest aggregate (+72), 5/8 agents bullish at high conviction; primary risk is geopolitical, not operational.
2. **AMD** — modestly positive but no high-conviction bull; consider a watch rather than a buy.
3. **INTC** — mixed; only the contrarian persona is bullish.
```

One sentence each, max 3 picks.

### 4. Suggested next step

```markdown
## Next step
Run `/deep NVDA` to confirm the top pick before sizing a position.
```

### 5. Run summary footer

```markdown
---
Compared {N} tickers ({succeeded} succeeded, {failed} failed) in {mode} mode, style={style}.
Estimated cost: ${actual_low}–${actual_high}.
```

## Hard caps

- **Max 10 tickers** per run. Enforce at input parse.
- **Continue on partial failure**: if 1+ tickers fail their underlying `trading-debate`, fill those rows with `n/a` and note it in the run summary footer (e.g. `2 succeeded, 1 failed`). Do NOT block the whole comparison on one bad ticker.
- **Cost confirmation gate**: if upper-bound estimate exceeds $25, ask the user before spawning anything.
- **Mode lock**: reject `--mode deep` with a clear message; suggest running `/deep TICKER` after the compare finishes.

## Disclaimer

The compare table aggregates research output, not financial advice. Use it to triage candidates, not to size trades.

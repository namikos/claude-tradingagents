---
name: trading-backtest
description: Backtest the trading-debate workflow on historical data. Walks N trading days at a chosen step, runs a lite analysis at each, simulates trades from the resulting signals, then computes Sharpe/Sortino/Max-Drawdown/Win-rate.
allowed-tools: Agent, Read, Write, Edit, mcp__tradingagents__historical_price, mcp__tradingagents__sharpe_ratio, mcp__tradingagents__sortino_ratio, mcp__tradingagents__max_drawdown
---

# Trading Backtest Orchestrator

You are the **Backtest Lead**. You replay the trading-debate workflow (in lite form) over historical dates, simulate trades from each iteration's signal, and report performance vs. buy-and-hold. Treat each iteration date `T` as "today" — analysts must only use data dated **before** `T`.

## Inputs

Parse `$ARGUMENTS` (positional + flags):

- `TICKER` — required, first positional (e.g., `NVDA`).
- `--from YYYY-MM-DD` — required, backtest start.
- `--to YYYY-MM-DD` — required, must be ≤ today.
- `--step Nd` — default `5d`. Re-evaluate every N trading days.
- `--style value|growth|macro|contrarian|quick` — default `quick`.
- `--initial-capital N` — default `100000`.
- `--position-size-pct N` — default `10` (percent of capital per trade).

If any required field is missing, abort with a one-line usage example.

## Cost Banner

Compute `iterations = floor(business_days_between(from, to) / step_days)`. Print at start:

```
===
Backtest: {TICKER} from {from} to {to}
Iterations: ~{N} (every {step})
Style: {style} | Est. cost: ${N*0.20}-${N*0.30} | ETA: {N*1.5} min
===
```

If estimated cost > **$20**, ASK the user to confirm before continuing.

## Lite Workflow per iteration

For each iteration date `T`:

1. **Spawn analysts in parallel** via the Agent tool (Sonnet, no Agent Teams needed):
   - `fundamentals-analyst` — prompt: *"Analyze {TICKER} as of date {T}. Use ONLY data dated before {T} (no look-ahead). Output the standard report ending with FINAL TRANSACTION PROPOSAL: BUY/HOLD/SELL and a confidence 0-100. Write to `state/{TICKER}_bt_{T}_fundamentals.md`."*
   - `technical-analyst` — same shape, replace topic with technicals; pass close prices via `mcp__tradingagents__historical_price(ticker={TICKER}, end={T}, lookback=200)`.
   - **Skip** `news-analyst` and `sentiment-analyst` — those rely on real-time feeds we cannot backfill cleanly.

2. **Spawn 2 personas** (Opus) according to `--style`:
   - `value` → `buffett`, `graham`
   - `growth` → `wood`, `lynch`
   - `macro` → `druckenmiller`, `damodaran`
   - `contrarian` → `burry`, `taleb`
   - `quick` → `buffett`, `wood` (one value-bias, one growth-bias)

   Each persona receives the 2 analyst reports and the constraint *"Use only information available before {T}."* Each outputs a one-paragraph thesis + BUY/HOLD/SELL + confidence 0-100.

3. **Skip** the bull/bear debate, skip the risk-manager.

4. **Trader-lite (inline, do not spawn)** — synthesize the 4 signals yourself using this rule:

   ```
   Inputs: 4 signals each with action ∈ {BUY,HOLD,SELL} and confidence 0-100.
   score = Σ (sign(action) * confidence)   # BUY=+1, HOLD=0, SELL=-1
   if score >=  60 → BUY,  conf = min(100, score)
   if score <= -60 → SELL, conf = min(100, -score)
   else            → HOLD, conf = 100 - |score|
   ```

   Append decision to `state/{TICKER}_bt_signals.md` as `T | ACTION | conf`.

## Trade Simulation

Maintain portfolio state across iterations (in-memory; persist a JSON snapshot to `state/{TICKER}_bt_portfolio.json` after each step):

```
cash, shares, equity_curve = initial_capital, 0, []
for T, action, conf in signals:
    price = mcp__tradingagents__historical_price(ticker, date=T)
    if action == BUY  and shares == 0:
        spend  = cash * (position_size_pct/100)
        shares = floor(spend / price)
        cash  -= shares * price * 1.001          # 0.1% fee
        log("BUY",  T, price, shares, pnl=0)
    elif action == SELL and shares > 0:
        proceeds = shares * price * 0.999        # 0.1% fee
        pnl      = proceeds - cost_basis
        cash    += proceeds
        log("SELL", T, price, shares, pnl)
        shares = 0
    # HOLD → no-op
    equity_curve.append((T, cash + shares*price))
```

## Performance Computation

At end of loop:

- `returns` = day-over-day pct change of `equity_curve` values.
- `sharpe   = mcp__tradingagents__sharpe_ratio(returns)`
- `sortino  = mcp__tradingagents__sortino_ratio(returns)`
- `max_dd   = mcp__tradingagents__max_drawdown(equity_curve)`
- `win_rate = profitable_trades / total_closed_trades` (BUY+SELL pair = 1 trade).
- Buy-and-hold baseline: `bh_return = mcp__tradingagents__historical_price(ticker, date=to) / mcp__tradingagents__historical_price(ticker, date=from) - 1`.

## Output

Write `state/{TICKER}_backtest_{from}_{to}.md`:

```markdown
# Backtest — {TICKER} ({from} → {to})

**Params:** step={step}, style={style}, capital=${initial_capital}, size={position_size_pct}%

## Trade Log
| Date | Action | Price | Shares | P&L |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

## Equity Curve
`▁▂▃▄▅▆▇█▇▆▅` (normalize each point to 0..7, map to `▁▂▃▄▅▆▇█`)

## Summary
| Metric | Strategy | Buy & Hold |
|---|---|---|
| Total Return | X% | Y% |
| Sharpe | ... | ... |
| Sortino | ... | n/a |
| Max DD | ... | ... |
| Win Rate | ...% | n/a |
| # Trades | ... | 1 |

## Commentary
- Did strategy beat buy-and-hold? (yes/no, by how much)
- Best iteration: {date} → +{pnl}
- Worst iteration: {date} → {pnl}
- Notes on drawdown periods, signal flips, anything anomalous.
```

End with: *"Backtest is historical simulation, not a forecast. Not financial advice."*

## Hard Caps

- **Max 50 iterations** per backtest. If `iterations > 50`, abort and ask the user to widen `--step` or shorten the window.
- **Earliest data check**: call `mcp__tradingagents__historical_price(ticker, date=from)` once before the loop. If it errors / returns no data, bail with: *"No historical price data for {TICKER} on {from}. Try a later start date."*
- **Consecutive failures**: if **3 iterations in a row** error out (analyst spawn fails, missing price, etc.), abort the backtest and write a partial report up to the last good iteration.

## Failsafes

- If an analyst returns no clear signal, treat as `HOLD` with confidence 50 and continue.
- If `historical_price` is missing for a single date `T`, skip that iteration (counts toward the 3-consecutive-fail limit) and move on.
- Persist `state/{TICKER}_bt_portfolio.json` every step so a crash is resumable.

## Disclaimer

Output must include: *"Historical backtest, not financial advice. Past performance does not predict future returns."*

---
description: Backtest a trading strategy on historical data. Returns Sharpe, Sortino, Max Drawdown, equity curve.
argument-hint: TICKER --from YYYY-MM-DD --to YYYY-MM-DD [--style value|growth|macro|contrarian|council]
---

Run the **trading-backtest** skill on `$ARGUMENTS`.

If `$ARGUMENTS` is empty, ask the user for a ticker plus a date range.

Parse `$ARGUMENTS` for ticker, `--from`, `--to`, and optional `--style` (default `council`). Invoke the `trading-backtest` skill via the Skill tool, passing all parsed values.

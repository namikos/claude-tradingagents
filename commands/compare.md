---
description: Side-by-side analysis of multiple tickers with persona heatmap.
argument-hint: T1,T2,T3 [--mode quick|standard]
---

Run the **trading-compare** skill on `$ARGUMENTS`.

If `$ARGUMENTS` is empty, ask the user for a comma-separated list of tickers.

Parse `$ARGUMENTS` for the ticker list and an optional `--mode` (default `quick` to keep cost manageable for multi-ticker runs). Invoke the `trading-compare` skill via the Skill tool, passing the ticker list and mode.

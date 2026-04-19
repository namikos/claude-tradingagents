---
description: Full 4-analyst + 13-persona deep dive with bull/bear + DCF. Cost $7-15, ETA 10-15 min.
argument-hint: TICKER [--style council|value|growth|macro|contrarian]
---

Run the **trading-debate** skill on ticker `$ARGUMENTS` with `mode=deep`.

If `$ARGUMENTS` is empty, ask the user which ticker they want analyzed.

Parse `$ARGUMENTS` for an optional `--style` flag (default `council`). Invoke the `trading-debate` skill via the Skill tool, passing the ticker and the explicit flags `--mode deep --style {chosen-style}`.

---
description: Continuously monitor a ticker, alerting on significant moves or signal changes.
argument-hint: TICKER --interval 1h|4h|1d [--alert-on price-break|signal-flip|news]
---

Run the **trading-watch** skill on `$ARGUMENTS`.

If `$ARGUMENTS` is empty, ask the user for a ticker and a polling interval.

Parse `$ARGUMENTS` for ticker, `--interval` (required), and optional `--alert-on` triggers. Invoke the `trading-watch` skill via the Skill tool, passing the parsed values.

---
description: Standard 4-analyst + 5-persona + bull/bear + risk analysis. Default mode/style.
argument-hint: TICKER [--mode quick|standard|deep] [--style council|value|growth|macro|contrarian]
---

Run the **trading-debate** skill on ticker `$ARGUMENTS`.

If `$ARGUMENTS` is empty, ask the user which ticker they want analyzed.

Parse `$ARGUMENTS` for optional `--mode` (default `standard`) and `--style` (default `council`). Invoke the `trading-debate` skill via the Skill tool. Pass the ticker plus the resolved `--mode` and `--style` flags.

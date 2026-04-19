---
name: trading-watch
description: Continuously monitor a ticker on a recurring schedule. Re-runs a lite analysis at each interval and alerts when signal flips, price breaks key level, or sentiment shifts materially. Uses ScheduleWakeup for self-pacing.
allowed-tools: Agent, Read, Write, Edit, ScheduleWakeup, mcp__tradingagents__quote, mcp__tradingagents__news
---

# Trading Watch — Recurring Ticker Monitor

You are running a long-lived watch loop on a single ticker. **You execute exactly ONE iteration per invocation**, then either schedule the next iteration via `ScheduleWakeup` or stop. The user's original prompt is the source of truth for `--interval`, `--alert-on`, `--price-thresholds`, and `--max-iterations` — preserve it verbatim so the next wakeup re-parses identical args.

## Inputs

Parse `$ARGUMENTS`:

| Arg | Required | Default | Notes |
|---|---|---|---|
| `TICKER` | yes (positional) | — | e.g. `NVDA` |
| `--interval` | no | `1h` | one of `15m`, `1h`, `4h`, `1d` (min 15m, max 1d) |
| `--alert-on` | no | `all` | `price-break` \| `signal-flip` \| `news` \| `all` |
| `--price-thresholds` | no | — | `high=N,low=N` explicit absolute levels |
| `--max-iterations` | no | `24` | hard ceiling — user can extend explicitly |

If `--interval` is missing or invalid, default to `1h`. Convert to `delaySeconds` for ScheduleWakeup: `15m=900`, `1h=3600`, `4h=14400`, `1d=86400`.

## Mechanics — ScheduleWakeup pattern

This skill is a **single-iteration runner**:

1. Run ONE iteration (steps in *Per-iteration workflow* below).
2. At the end, if `iteration_count < max_iterations` and no fatal error, call:
   ```
   ScheduleWakeup(delaySeconds=<interval_seconds>, prompt="<ORIGINAL_USER_PROMPT>")
   ```
   The `prompt` MUST be the user's exact original prompt (e.g. `Run trading-watch on NVDA --interval 1h --alert-on all`) so the next wakeup re-enters this skill with identical args.
3. Stop (do NOT schedule another wakeup) when:
   - `iteration_count >= max_iterations`, OR
   - User interrupted (skill is re-invoked with `--stop`), OR
   - `mcp__tradingagents__quote` failed 3 consecutive iterations (see Hard caps), OR
   - The skill cannot determine the original prompt safely.

## Per-iteration workflow

1. **Resolve iteration number.** Read `state/{TICKER}_watch.md` if it exists. Find the highest `## Iteration N` header. The current iteration is `N+1`. If the file doesn't exist, this is iteration `1` — create the file with a header block:
   ```markdown
   # Watch — {TICKER}
   - Started: {ISO timestamp}
   - Interval: {interval}
   - Max iterations: {max_iterations}
   - Alert-on: {alert-on}
   - Running cost: $0.00
   ```

2. **Fetch fresh data.**
   - `mcp__tradingagents__quote(TICKER)` → current price, day change, volume.
   - `mcp__tradingagents__news(TICKER, days=1)` → fresh headlines + sentiment scores.
   - On quote failure, increment a `consecutive_quote_failures` counter persisted in the state header. After 3, abort (see Hard caps).

3. **Spawn lite analysts in parallel.** Use the `Agent` tool twice (parallel calls):
   - `subagent_type: "fundamentals-analyst"` — prompt: *"Quick check on {TICKER}. Do NOT write a full report. Read the latest quote ({price}) and last iteration's signal from state/{TICKER}_watch.md (if any). Respond with ONLY a JSON Signal Footer: `{\"signal\": \"BUY|HOLD|SELL\", \"confidence\": 0-100, \"key_change\": \"<one-line what shifted vs last check>\"}`."*
   - `subagent_type: "technical-analyst"` — same instruction shape, focused on price action / MACD / RSI.

4. **Diff against previous iteration.** Load the prior `## Iteration N-1` block (if any). Compute:
   - `signal_flipped`: bull→bear, bear→bull, or signal letter changed
   - `price_delta_pct`: `(current - last_price) / last_price * 100`
   - `price_break`: triggered if `--price-thresholds` set and current crosses high or low
   - `new_headlines`: headlines whose title is not in the prior iteration's headline list
   - `material_price_move`: `abs(price_delta_pct) >= 2.0`

5. **Determine triggered alerts** based on `--alert-on`:
   - `price-break` fires on `price_break` or `material_price_move`
   - `signal-flip` fires on `signal_flipped`
   - `news` fires when `len(new_headlines) > 0` AND any headline sentiment score crosses `±0.35`
   - `all` fires on any of the above

6. **Append iteration block** to `state/{TICKER}_watch.md`:
   ```markdown
   ## Iteration {N} — {ISO timestamp}
   - Price: ${current} ({±delta%} since last)
   - Fundamentals signal: {signal} (conf {conf}) — {key_change}
   - Technical signal: {signal} (conf {conf}) — {key_change}
   - Combined signal: {agreed signal or "MIXED"}
   - Signal flipped: yes/no
   - New headlines: {count}
     - {title 1}
     - {title 2}
   - Triggered alerts: [list, or "none"]
   ```
   Update the `Running cost` line in the header (estimate `$0.20` per iteration; bump and rewrite).

7. **If alerts fired**, also write a separate `state/{TICKER}_alert_{ISO_timestamp_compact}.md` (e.g. `NVDA_alert_20260419T131500.md`) containing:
   ```markdown
   # ALERT — {TICKER} — {timestamp}
   - Trigger(s): {list}
   - Price: ${current} ({±delta%})
   - Signal: {combined} (was {prior})
   - Top new headline: {title}
   - Recommended action: review state/{TICKER}_watch.md and consider running `/analyze {TICKER}` for a full re-debate.
   ```

8. **Schedule next iteration** (or stop — see Mechanics).

## Alerts

Alert files are intentionally separate from the rolling watch log so they are easy to find via `ls state/{TICKER}_alert_*.md`. Each alert is self-contained and human-scannable in <30 seconds. Do not delete or compact alerts — they are the audit trail.

## Hard caps

- **Max iterations**: stop after `--max-iterations` (default 24). At final iteration, append `## Watch ended — reached max iterations ({N})` to the state file.
- **Cost**: each iteration costs roughly $0.10–$0.30 (two lite Sonnet analysts + a few MCP calls). The `Running cost` line in the state header is the user's at-a-glance budget meter.
- **Quote failures**: after 3 consecutive `mcp__tradingagents__quote` failures, write a `## Watch ended — data unavailable` block and do NOT schedule another wakeup. Surface the failure prominently so the user can investigate.
- **Interval bounds**: never accept intervals shorter than 15m (rate-limit risk on Alpha Vantage free tier) or longer than 1d (defeats the purpose of "watch").

## Disclaimer

Watch alerts are research signals, not financial advice. Always run `/analyze {TICKER}` for a full debate before acting on a flipped signal.

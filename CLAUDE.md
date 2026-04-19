# TradingAgents — Substanz Edition (v2.1) — Claude Code Plugin

This is a Claude-Code-native multi-agent stock-trading research framework.
Port of [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
extended with the [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund)
13-investor-persona pattern. Apache-2.0.

Distributed as a Claude Code plugin: `agents/`, `agents/personas/`, `skills/`,
`commands/` live at the plugin root, plus an MCP server (`tools/mcp_server.py`)
exposing 41 tools.

## Architecture

### Base agents (always present)

| Role | Model | Purpose |
|---|---|---|
| Fundamentals Analyst | sonnet | Earnings, balance sheet, ratios |
| Technical Analyst | sonnet | MACD/RSI/SMA/EMA + price action |
| News Analyst | sonnet | Company + macro news |
| Sentiment Analyst | sonnet | Social/news sentiment scoring |
| Bull Researcher | opus | Argues *for* investment |
| Bear Researcher | opus | Argues *against*; debates Bull directly |
| Trader | opus | Aggregates JSON signals → writes plan |
| Risk Manager | opus | ATR + Kelly hard-cap checks; approves/rejects |

### 13 famous-investor personas (`agents/personas/`)

| Bucket | Personas |
|---|---|
| Value | buffett, graham, munger, pabrai |
| Contrarian/Special | burry, taleb, ackman |
| Growth | wood, lynch, fisher |
| Macro | druckenmiller, damodaran, jhunjhunwala |

Each persona reads the 4 analyst reports, calls 1–3 persona-specific MCP
tools, and writes `state/{TICKER}_persona_{name}.md` ending with a JSON
Signal Footer.

## JSON Signal Footer (canonical schema)

Every analyst, persona, bull, and bear report MUST end with one fenced
```json``` block:

```json
{
  "agent": "fundamentals-analyst",
  "signal": "bullish|bearish|neutral",
  "confidence": 0-100,
  "horizon": "1-3mo|3-6mo|6-12mo|1-3yr|3+yr",
  "fair_value": 245.00,
  "thesis_break_level": 165.00,
  "key_points": ["...", "..."],
  "key_risks": ["...", "..."],
  "counter_arguments": ["..."]
}
```

Personas use `"persona": "buffett"` instead of `"agent"`. `fair_value` and
`thesis_break_level` are persona-only (null if persona doesn't DCF, e.g.
Taleb). `counter_arguments` is bull/bear only. The trader aggregates these
for confidence-weighted scoring.

## Modes (controlled by `--mode` flag in trading-debate skill)

| Mode | Analysts | Personas | Bull/Bear | Risk-Loop |
|---|---|---|---|---|
| quick | 2 (fund+tech) | 3 | — | — |
| standard (default) | 4 | 5 | 1 round | 1 iter |
| deep | 4 | 13 + DCF | 2 rounds | 2 iter |

## Styles (filters which personas spawn)

| Style | Personas |
|---|---|
| value | buffett, graham, munger, pabrai, burry |
| growth | wood, lynch, fisher |
| macro | druckenmiller, damodaran, jhunjhunwala |
| contrarian | burry, taleb, ackman |
| council (default) | mode-dependent: 13 in deep, 5 in standard, 3 in quick |

## Workflow (orchestrated by `trading-debate` skill)

```
[Lead] parses --mode + --style, prints cost banner, creates tasks
  ├── analyze-fundamentals   → fundamentals-analyst (sonnet)   ─┐
  ├── analyze-technical      → technical-analyst (sonnet)       │ parallel
  ├── analyze-news           → news-analyst (sonnet)            │ (mode-gated)
  └── analyze-sentiment      → sentiment-analyst (sonnet)      ─┘
        ↓ TeammateIdle
  └── persona-{name} × N     → persona subagents (sonnet, parallel; style+mode-gated)
        ↓
  └── bull-bear-debate       → bull + bear (opus, mailbox; skipped in quick)
        ↓
  └── trader-decision        → trader (opus); reads ALL JSON signals
        ↓ plan approval
  └── risk-approval          → risk-manager (opus); ATR + Kelly hard caps
        ↓
[Lead] synthesizes Final Output
```

## File Conventions

All inter-agent state lives in `state/` (gitignored):

- `state/{TICKER}_fundamentals.md` — fundamentals analyst report
- `state/{TICKER}_technical.md` — technical analyst report
- `state/{TICKER}_news.md` — news analyst report
- `state/{TICKER}_sentiment.md` — sentiment analyst report
- `state/{TICKER}_persona_{name}.md` — persona reports (one per spawned)
- `state/{TICKER}_debate.md` — bull/bear debate transcript (appended live)
- `state/{TICKER}_trader_plan.md` — trader's signal-aggregated plan
- `state/{TICKER}_decision.md` — final decision after risk approval
- `state/{TICKER}_backtest_{from}_{to}.md` — backtester output
- `state/{TICKER}_watch.md` — watch-loop iteration log
- `state/compare_{T1}_{T2}_*.md` — multi-ticker compare output

**Always end an analyst/persona/bull/bear report with:**
1. A Markdown summary table or analysis section
2. The JSON Signal Footer (schema above)

The trader and risk-manager files end with the literal line:
`FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`

## Tools (MCP server `tradingagents`)

The `tools/mcp_server.py` FastMCP server is registered in `.mcp.json` and
exposes 41 tools (each must be in the agent's `tools:` whitelist as
`mcp__tradingagents__<name>`):

### Data sources (Alpha Vantage)
- `quote(ticker)`, `fundamentals(ticker)`, `balance_sheet`, `cashflow`,
  `income`, `news`, `global_news`, `technical(indicator,period)`, `insider`

### Data sources (yfinance — no API key)
- `history`, `info`, `yfin_news`, `options_chain`, `short_interest`

### Data sources (SEC EDGAR)
- `sec_filings(ticker, form_type, limit)` — uses EDGAR submissions JSON

### Quantitative methodology (NEW in v1.0)
- `dcf(ticker, growth_rate, discount_rate, terminal_growth, years)`
- `kelly_position_size(win_prob, win_pct, loss_pct, fraction=0.5)`
- `atr_stop(ticker, period=14, multiplier=2.0)`
- `sharpe_ratio(returns)`, `sortino_ratio(returns)`, `max_drawdown(equity)`
- `historical_price(ticker, date)` — drives backtester
- `factor_exposure(ticker)` — beta to SPY + sector correlation

Responses cached on disk (`${CLAUDE_PLUGIN_DATA}/cache/` or `state/cache/`)
for 1h (data) / 6h (SEC filings).

### v2.1 — Depth & Quant Layers (NEW, +17 tools → 41 total)

**Macro:**
- `fred(series_id, lookback_days)` — St. Louis Fed time series
- `vix_term_structure()` — VIX1D/VIX/VIX3M/VIX6M curve (contango/backwardation)
- `cboe_skew()` — CBOE SKEW tail-risk index

**Smart-Money:**
- `congress_trades(ticker)` — Senator/House trades (45-day disclosure)
- `options_flow(ticker)` — unusual options activity (Barchart scrape)
- `etf_holdings(ticker)` — ETFs holding this ticker
- `institutional_holdings(ticker)` — 13F-HR filings

**Forward-Looking:**
- `earnings_transcript(ticker, quarter, year)` — full call transcript (FMP)
- `finnhub_recommendations(ticker)` — analyst buy/hold/sell consensus
- `finnhub_calendar()` — upcoming earnings calendar
- `finnhub_ipo_calendar()` — upcoming IPOs

**Sentiment:**
- `reddit_mentions(ticker, subreddits, days)` — PRAW subreddit search
- `finbert_score(text)` — finance-domain BERT classifier (local, ~440MB)

**Quant (heavy deps; see `tools/requirements-quant.txt`):**
- `vectorbt_backtest(ticker, signals, start, end)` — vectorized backtest
- `risk_metrics(returns)` — Calmar/Omega/Tail-Ratio/CVaR (empyrical)
- `frac_diff(series, d)`, `triple_barrier_labels(...)` — López de Prado (mlfinlab)

**Persona uplift in v2.1:** Druckenmiller and Damodaran gain `fred` + `vix_term_structure`; Burry and Ackman gain `congress_trades` + `options_flow` + `institutional_holdings`; Wood and Lynch gain `etf_holdings` + `finnhub_recommendations`; all personas can pull `earnings_transcript` for forward-looking guidance.

### WebSearch / WebFetch
Native Claude Code tools. News + Sentiment analysts use them for breaking
headlines, Reddit/Twitter/Stocktwits discussions.

## Skills

- `skills/trading-debate/SKILL.md` — main mode-aware orchestrator
- `skills/trading-backtest/SKILL.md` — historical lite-workflow iteration
- `skills/trading-watch/SKILL.md` — ScheduleWakeup-based continuous monitor
- `skills/trading-compare/SKILL.md` — parallel multi-ticker compare

## Slash Commands

- `/analyze TICKER [--mode] [--style]` — default standard/council
- `/quick TICKER` — 2 analysts + 3 personas, no bull/bear
- `/deep TICKER [--style]` — 4 analysts + 13 personas + bull/bear + DCF
- `/backtest TICKER --from --to [--style]`
- `/watch TICKER --interval [--alert-on]`
- `/compare T1,T2,T3 [--mode]`

## Setup

End users (plugin install):
1. `/plugin marketplace add namikos/claude-tradingagents`
2. `/plugin install tradingagents@namikos-tradingagents`
3. Claude Code prompts for the Alpha Vantage API key (free at
   https://www.alphavantage.co/support/#api-key) — stored via `userConfig`
   (sensitive → OS keychain).
4. Make sure `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set.
5. `pip install -r tools/requirements.txt`
6. (Optional) `cd app && npm install && npm run dev` for the dashboard.
7. Use `/analyze TICKER`, `/quick TICKER`, `/deep TICKER`, etc.

## Caveats

- Alpha Vantage free tier: **25 requests/day**. Cache helps but plan
  accordingly. `/quick` ≈ 5 req, `/deep` ≈ 15–20.
- Token costs: `/quick` $1–2, `/analyze` $3–5, `/deep` $7–15.
- Plan-approval loop capped at 1 (standard) / 2 (deep) iterations.
- Watch loop bound to session lifetime + `ScheduleWakeup`.
- Dashboard is read-only — analyses still triggered via Claude Code.
- This is **NOT** financial advice. Output is research only.

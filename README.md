# TradingAgents — Substanz Edition (v2.1)

A Claude Code plugin that runs a **substance-maximizing, multi-perspective stock
research workflow** on any ticker. 4 base analysts run in parallel, then 13
famous-investor personas (Buffett, Burry, Wood, Druckenmiller, Taleb, …) weigh
in, a bull/bear pair debates the case, a trader writes a quant-backed plan, and
a risk manager signs off using ATR + Kelly hard caps.

Three workflow modes (`/quick`, `/analyze`, `/deep`) × five investor styles
(value / growth / macro / contrarian / council). Includes a backtester, a
continuous watch loop, a multi-ticker compare, and a read-only Next.js
dashboard.

> ⚠️ **Research, not financial advice.** Output is for educational use only.

---

## Credit & lineage

This project is a **port + extension** of two upstream projects:

- [**TauricResearch/TradingAgents**](https://github.com/TauricResearch/TradingAgents)
  — original LangGraph framework (agent role taxonomy, workflow shape,
  output conventions). The Claude-Code-native orchestration and MCP server
  are original to this repo.
- [**virattt/ai-hedge-fund**](https://github.com/virattt/ai-hedge-fund)
  — inspired the 13 famous-investor persona pattern and the JSON Signal
  Footer schema for structured agent outputs.

Both upstream projects and this plugin are released under **Apache License 2.0**.
See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE) for full attribution.

---

## What it does

```
        ┌── fundamentals-analyst (sonnet) ──┐
parallel├── technical-analyst    (sonnet) ──┤
        ├── news-analyst         (sonnet) ──┤
        └── sentiment-analyst    (sonnet) ──┘
                       ↓
        13 persona subagents in parallel (sonnet)
        Buffett · Graham · Munger · Pabrai · Burry · Taleb · Ackman ·
        Wood · Lynch · Fisher · Druckenmiller · Damodaran · Jhunjhunwala
                       ↓
        bull-researcher  ⇄  bear-researcher        (opus, mailbox debate, max 2 rounds)
                       ↓
        trader (opus) ─── reads ALL JSON signals ─── writes plan ───►
                       ↓
        risk-manager (opus) — uses atr_stop + kelly_position_size hard caps
                       ↓
                Final BUY/HOLD/SELL + position sizing + entry/stop/target
```

Every agent appends a **JSON Signal Footer** to its Markdown report; the
trader does confidence-weighted aggregation across all signals before writing
the plan.

---

## Modes

| Command | Analysts | Personas | Bull/Bear | Risk-Loop | Cost | ETA |
|---|---|---|---|---|---|---|
| `/quick TICKER` | 2 | 3 | — | — | $1–2 | 2–3 min |
| `/analyze TICKER` | 4 | 5 | 1 round | 1 iter | $3–5 | 6–8 min |
| `/deep TICKER` | 4 | **13** + DCF | 2 rounds | 2 iter | $7–15 | 10–15 min |

## Styles (which personas run)

| Style | Personas |
|---|---|
| `value` | buffett, graham, munger, pabrai, burry |
| `growth` | wood, lynch, fisher |
| `macro` | druckenmiller, damodaran, jhunjhunwala |
| `contrarian` | burry, taleb, ackman |
| `council` (default) | all 13 in `deep`, top 5 in `standard`, top 3 in `quick` |

Pass with `--style`: `/analyze NVDA --style value`, `/deep TSLA --style contrarian`.

## Other commands

- `/backtest TICKER --from 2024-01-01 --to 2024-06-30 [--style value]`
  — historical lite-workflow iteration, returns Sharpe / Sortino / Max-DD /
  win-rate vs buy-and-hold baseline.
- `/watch TICKER --interval 1h [--alert-on signal-flip|price-break|news]`
  — continuous monitor via `ScheduleWakeup`; max 24 iterations by default.
- `/compare T1,T2,T3 [--mode quick]` — parallel multi-ticker analysis with
  side-by-side persona heatmap and ranked top picks.

---

## Install

### 1. Add the marketplace and install

```text
/plugin marketplace add namikos/claude-tradingagents
/plugin install tradingagents@namikos-tradingagents
```

Claude Code will prompt for your **Alpha Vantage API key** (stored in your OS
keychain via the plugin's `userConfig`). Free key in 30 sec at
[alphavantage.co/support/#api-key](https://www.alphavantage.co/support/#api-key).

Optionally also set a **Financial Datasets API key** for premium fundamentals
(skipped if absent).

### 2. Enable Agent Teams (one-time)

Add to your `~/.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### 3. Install Python deps for the bundled MCP server

```bash
pip install -r ${CLAUDE_PLUGIN_ROOT}/tools/requirements.txt
```

This installs `mcp[cli]`, `httpx`, `yfinance`, `pandas`, `numpy`, `scipy`.

Optional — install heavy quant dependencies (~3GB, only if you use FinBERT/vectorbt/empyrical/mlfinlab):

```bash
pip install -r tools/requirements-quant.txt
```

### 4. (Optional) Run the read-only dashboard

```bash
cd ${CLAUDE_PLUGIN_ROOT}/app
npm install
npm run dev
# → http://localhost:3000
```

The dashboard is purely a viewer — it watches `state/` for changes and renders
the 13-persona heatmap, debate stream, and trade plan live. You still trigger
analyses via `/analyze`, `/deep`, etc. in Claude Code.

---

## Quantitative tools (MCP)

The bundled MCP server (`tools/mcp_server.py`) exposes 37 tools, callable by
agents as `mcp__tradingagents__<name>`:

### Data sources
- **Alpha Vantage**: `quote`, `fundamentals`, `balance_sheet`, `cashflow`,
  `income`, `news`, `global_news`, `technical` (MACD/RSI/SMA/EMA), `insider`
- **yfinance**: `history`, `info`, `yfin_news`, `options_chain`,
  `short_interest`
- **SEC EDGAR**: `sec_filings` (10-K / 10-Q / 8-K / Form-4)

### Quantitative methods
- `dcf` — discounted-cash-flow intrinsic value with margin-of-safety
- `kelly_position_size` — half-Kelly-capped position sizing
- `atr_stop` — Wilder ATR-based stop levels
- `sharpe_ratio`, `sortino_ratio`, `max_drawdown` — performance metrics
- `historical_price` — closing price on any past date (drives backtester)
- `factor_exposure` — beta to SPY + sector correlation

### v2.1 — Datentiefe (37 Tools total)

**Macro layer** (NEW v2.1):
- `fred(series_id, lookback_days)` — St. Louis Fed time series
- `vix_term_structure()`, `cboe_skew()` — fear gauge & tail-risk indicators

**Smart-Money layer** (NEW v2.1):
- `congress_trades(ticker)` — Senator/House-Member trades (45-day disclosure)
- `options_flow(ticker)` — unusual options activity (Barchart)
- `etf_holdings(ticker)` — which ETFs hold this ticker
- `institutional_holdings(ticker)` — 13F-HR filings (45-day lag)

**Forward-Looking layer** (NEW v2.1):
- `earnings_transcript(ticker, quarter, year)` — full earnings call transcript (FMP)
- `finnhub_recommendations(ticker)`, `finnhub_calendar()`, `finnhub_ipo_calendar()`

**Sentiment layer** (NEW v2.1):
- `reddit_mentions(ticker, subreddits, days)` — PRAW-based subreddit search
- `finbert_score(text)` — finance-specific BERT sentiment classifier (lokal, ~440MB)

**Quant layer** (NEW v2.1):
- `vectorbt_backtest(ticker, signals, start, end)` — vectorized portfolio backtest
- `risk_metrics(returns)` — Calmar, Omega, Tail-Ratio, Stability, CVaR (empyrical)
- `frac_diff(series, d)`, `triple_barrier_labels(...)` — López de Prado methods (mlfinlab)

---

## Output you get back

After `/analyze` or `/deep`:
- **Final recommendation** (BUY / HOLD / SELL) + conviction, time horizon,
  position size, entry / stop / target
- **One-line view from each analyst** (with confidence)
- **Persona consensus**: bullish % weighted by confidence, median fair value,
  tightest thesis-break level
- **Bull case / Bear case** (1 sentence each)
- **Risk-manager verdict** with monitor-this caveats and ATR/Kelly checks

Full state files in `state/`:

| File | Author |
|---|---|
| `state/{TICKER}_fundamentals.md` | fundamentals-analyst |
| `state/{TICKER}_technical.md` | technical-analyst |
| `state/{TICKER}_news.md` | news-analyst |
| `state/{TICKER}_sentiment.md` | sentiment-analyst |
| `state/{TICKER}_persona_buffett.md` ×13 | persona subagents |
| `state/{TICKER}_debate.md` | bull-researcher + bear-researcher |
| `state/{TICKER}_trader_plan.md` | trader |
| `state/{TICKER}_decision.md` | risk-manager |
| `state/{TICKER}_backtest_*.md` | trading-backtest skill |

Every analyst, persona, bull, and bear file ends with a **JSON Signal Footer**
that the trader parses for weighted aggregation.

---

## Plugin layout

```
.claude-plugin/
  plugin.json           ← plugin manifest (incl. userConfig for the API key)
  marketplace.json      ← single-plugin marketplace entry
agents/                 ← 8 base agents (4 analysts + bull/bear + trader + risk-manager)
agents/personas/        ← 13 famous-investor persona subagents
skills/
  trading-debate/       ← main mode-aware orchestrator (quick/standard/deep)
  trading-backtest/     ← historical lite-workflow iteration
  trading-watch/        ← ScheduleWakeup-based continuous monitor
  trading-compare/      ← parallel multi-ticker compare
commands/               ← /analyze, /quick, /deep, /backtest, /watch, /compare
tools/
  mcp_server.py         ← FastMCP server: 23 tools (data + quant)
  alpha_vantage.py      ← also runnable standalone
  yfin.py               ← also runnable standalone
  requirements.txt
app/                    ← read-only Next.js 15 dashboard (optional)
.mcp.json               ← registers the tradingagents MCP server
CLAUDE.md               ← shared context loaded by every teammate
LICENSE / NOTICE        ← Apache-2.0 + upstream attribution
```

---

## Caveats

- **Free-tier Alpha Vantage = 25 requests/day.** The MCP server caches results
  (1h default, 6h for SEC filings) in `${CLAUDE_PLUGIN_DATA}/cache/`. A
  `/quick` run burns ~5 requests; `/deep` burns ~15–20. Plan accordingly or
  upgrade your key.
- **Token cost scales with mode.** `/deep` uses Opus heavily (trader, risk,
  bull, bear) and Sonnet 17× (4 analysts + 13 personas). Realistic $7–15 per
  full deep run.
- **Agent Teams is experimental.** With `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`
  unset, the bull/bear debate falls back to sequential writes (no live
  mailbox).
- **Plan-approval loop is capped** at 1 (standard) / 2 (deep) iterations to
  avoid hangs.
- **Backtester is a lite simulator** — 2 analysts + 2 personas per iteration,
  no bull/bear. Realistic, not perfect; treat as a sanity check.
- **Watch loop is bound to session lifetime.** For 24/7 monitoring use OS
  cron + `claude -p`.
- **Dashboard is read-only and unstyled beyond Tailwind defaults.** It works;
  it's not a product.

---

## Contributing

PRs welcome — especially:

- Sharper persona prompts with newer real-life trades.
- New MCP tools (earnings transcripts, congressional trades, alt-data).
- Backtester portfolio-level support (currently single-ticker).
- Dashboard polish (charts, theming, ticker switcher).
- Fallback logic for Alpha Vantage rate-limits.

Please keep changes Apache-2.0-compatible and update `NOTICE` for any
substantial code derived from third parties.

---

## License

Apache License 2.0. See [`LICENSE`](LICENSE) for the full text and
[`NOTICE`](NOTICE) for attribution.

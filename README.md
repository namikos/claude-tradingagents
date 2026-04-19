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

**Optional v2.1 API keys** — all free-tier, all opt-in (tools return a clean
error if a key is missing instead of crashing):

| Key | Source | Powers |
|---|---|---|
| `fred_api_token` | [FRED API](https://fred.stlouisfed.org/docs/api/api_key.html) (free) | `fred()` macro time series |
| `fmp_api_token` | [Financial Modeling Prep](https://site.financialmodelingprep.com/developer) (250/day) | `earnings_transcript()` |
| `finnhub_api_token` | [Finnhub](https://finnhub.io) (60/min) | analyst recs + earnings/IPO calendar |
| `reddit_client_id` + `reddit_client_secret` + `reddit_user_agent` | [Reddit OAuth app](https://www.reddit.com/prefs/apps) | `reddit_mentions()` PRAW search |

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

The bundled MCP server (`tools/mcp_server.py`) exposes **41 tools**, callable
by agents as `mcp__tradingagents__<name>`:

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

### v2.1 — Depth & Quant Layers (17 new tools)

v2.1 adds five new analysis layers on top of the v2.0 core. Each layer is
opt-in: tools that need an API key or heavy dep return a structured
`{"error": "..."}` instead of crashing if it's missing.

**Macro layer** — what the broader market is doing
- `fred(series_id, lookback_days)` — St. Louis Fed time series (DGS10, VIXCLS,
  UNRATE, CPI, M2, ...). Grounds news headlines in actual macro data.
- `vix_term_structure()` — VIX/VIX9D/VIX3M/VVIX with auto-classification
  (calm/normal/stress + contango/backwardation). Feeds the regime-aware
  position-sizing rule in the risk-manager.
- `cboe_skew()` — SKEW Index (>150 = elevated tail risk).

**Smart-Money layer** — what insiders & institutions are actually doing
- `congress_trades(ticker)` — Senator + House-Member trades (45-day STOCK-Act
  disclosure window). Often a leading news catalyst.
- `options_flow(ticker)` — unusual options activity scraped from Barchart.
  Smart money frequently positions via options before equity moves.
- `etf_holdings(ticker)` — which ETFs hold this ticker, weighted by allocation.
  Surfaces ETF-flow risk (e.g. ARKK contagion → individual TSLA pressure).
- `institutional_holdings(ticker)` — latest 13F-HR filings from
  Berkshire / Scion / Pershing / ARK / Bridgewater / Renaissance. Lets you
  cross-check whether a persona's bull thesis matches what its real-life
  counterpart actually owns. **Trailing indicator (45-day lag.)**

**Forward-Looking layer** — what's about to happen
- `earnings_transcript(ticker, quarter, year)` — full earnings-call text
  via Financial Modeling Prep. Forward guidance + management tone.
- `finnhub_recommendations(ticker)` — analyst consensus trends over time
  (strong-buy / buy / hold / sell / strong-sell counts per period).
- `finnhub_calendar(from, to)` — earnings schedule (default: next 14d). The
  trader checks this before finalizing entry dates.
- `finnhub_ipo_calendar(from, to)` — upcoming IPOs (default: next 30d).

**Sentiment layer** — quantified retail/social signal
- `reddit_mentions(ticker, subreddits, days)` — PRAW-based subreddit search
  across r/wallstreetbets, r/investing, r/stocks. Replaces brittle WebSearch.
- `finbert_score(text)` — finance-specific BERT classifier
  (`ProsusAI/finbert`). Returns `{positive, negative, neutral}` confidences.
  Lazy-loaded on first call (~440MB cold-start, cached after).

**Quant layer** — institutional-grade backtest & risk
- `vectorbt_backtest(ticker, signals, start, end)` — vectorized portfolio
  backtest (ms-fast). Plug into `/backtest --engine vectorbt` for the new
  fast path; the legacy lite-loop remains the default for backwards-compat.
- `risk_metrics(returns)` — Calmar, Omega, Tail-Ratio, Stability, CVaR via
  `empyrical`. More robust than hand-rolled Sharpe for fat-tailed returns.
- `frac_diff(series, d)` — López de Prado fractional differentiation
  (preserves memory while achieving stationarity).
- `triple_barrier_labels(prices, ...)` — TBL labeling for ML pipelines.

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
  mcp_server.py         ← FastMCP server: 41 tools (data + quant + v2.1 layers)
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

### v2.1 specifics
- **FinBERT cold-start downloads ~440MB** (`ProsusAI/finbert`) on the very
  first `finbert_score()` call. Cached afterwards. Skip the install if you
  don't want it — `requirements-quant.txt` is opt-in.
- **`options_flow` HTML-scrapes Barchart.** If Barchart changes its DOM the
  tool returns `{"error": "barchart parse failed"}` — never a crash.
- **`institutional_holdings` is a trailing indicator.** 13F-HR filings have a
  45-day reporting lag, so the data is always one quarter behind.
- **`mlfinlab` API is unstable**, so `frac_diff` and `triple_barrier_labels`
  ship a local fallback implementation that doesn't depend on it.

---

## Contributing

PRs welcome — especially:

- Sharper persona prompts with newer real-life trades.
- New MCP tools (earnings whisper numbers, dark-pool flow, alt-data).
- Backtester portfolio-level support (currently single-ticker).
- Dashboard polish (charts, theming, ticker switcher) + v2.1 layer views.
- Fallback logic for Alpha Vantage rate-limits.
- Robust `options_flow` parser (Barchart DOM is fragile).

Please keep changes Apache-2.0-compatible and update `NOTICE` for any
substantial code derived from third parties.

---

## License

Apache License 2.0. See [`LICENSE`](LICENSE) for the full text and
[`NOTICE`](NOTICE) for attribution.

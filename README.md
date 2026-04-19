# TradingAgents — Multi-Agent Stock Research for Claude Code

A Claude Code plugin that runs a full multi-agent research pipeline on any
stock ticker — 4 parallel analysts, a live bull/bear debate, a trader, and a
risk manager — and produces a single buy/hold/sell recommendation with an
auditable paper trail.

> ⚠️ **Research, not financial advice.** Output is for educational use only.

---

## Credit & lineage

This project is a **port** of the excellent
[**TauricResearch/TradingAgents**](https://github.com/TauricResearch/TradingAgents)
LangGraph framework to native Claude Code primitives (Agent Teams, MCP, plugin
packaging). The agent role taxonomy, workflow shape, and output conventions
come from the upstream project; the orchestration layer, MCP server, and
plugin packaging are original to this repo.

If you find this useful, please ⭐ the **upstream project** as well:
👉 https://github.com/TauricResearch/TradingAgents

Both projects are released under the **Apache License 2.0**. See [`LICENSE`](LICENSE)
and [`NOTICE`](NOTICE) for full attribution and terms.

---

## What it does

Given a ticker like `NVDA`, the plugin spins up 8 specialized teammates that
collaborate end-to-end:

```
        ┌── fundamentals-analyst (sonnet) ──┐
parallel├── technical-analyst    (sonnet) ──┤
        ├── news-analyst         (sonnet) ──┤
        └── sentiment-analyst    (sonnet) ──┘
                       ↓
        bull-researcher  ⇄  bear-researcher        (opus, mailbox debate, max 2 rounds)
                       ↓
        trader  ──── plan ────► risk-manager        (opus, plan-approval loop, max 2x)
                       ↓
                Final BUY/HOLD/SELL
```

Every analyst writes a Markdown report into `state/{TICKER}_*.md`; the debate
transcript, trader plan, and final signed-off decision land there too — so you
can audit every step.

---

## Install

### 1. Add the marketplace and install

```text
/plugin marketplace add namikos/tradingagents
/plugin install tradingagents@namikos-tradingagents
```

Claude Code will prompt you for your **Alpha Vantage API key** and store it
securely (the plugin's `userConfig` marks it `sensitive: true`, so it goes
into your OS keychain).

> Get a free key in 30 seconds at
> [alphavantage.co/support/#api-key](https://www.alphavantage.co/support/#api-key).
> The free tier allows 25 requests/day; responses are cached locally for 1h.

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

Or install manually:

```bash
pip install 'mcp[cli]>=1.2.0' httpx 'yfinance>=0.2.40' 'requests>=2.31.0'
```

---

## Usage

```text
/analyze NVDA
```

…or just say:

> Run trading-debate on NVDA

The Lead session spawns the team, waits for the four analyst reports to land,
brokers the bull/bear debate, asks the trader to commit a plan, runs that plan
through the risk manager, and finally synthesizes a single recommendation.

### Output you get back

- A Markdown summary at the end of the conversation:
  - Final recommendation (BUY / HOLD / SELL) + conviction, time horizon,
    position size, entry / stop / target
  - A one-line view from each analyst
  - Bull case (1 sentence) and bear case (1 sentence)
  - Risk-manager verdict with monitor-this caveats
- Full state files in `state/`:

  | File | Author |
  |---|---|
  | `state/{TICKER}_fundamentals.md` | fundamentals-analyst |
  | `state/{TICKER}_technical.md` | technical-analyst |
  | `state/{TICKER}_news.md` | news-analyst |
  | `state/{TICKER}_sentiment.md` | sentiment-analyst |
  | `state/{TICKER}_debate.md` | bull-researcher + bear-researcher |
  | `state/{TICKER}_trader_plan.md` | trader |
  | `state/{TICKER}_decision.md` | risk-manager |

---

## Plugin layout

```
.claude-plugin/
  plugin.json           ← plugin manifest (incl. userConfig for the API key)
  marketplace.json      ← marketplace entry (single-plugin marketplace)
agents/                 ← 8 subagent definitions
skills/trading-debate/  ← orchestrator skill (the workflow)
commands/analyze.md     ← /analyze TICKER slash command
tools/
  mcp_server.py         ← FastMCP server: wraps Alpha Vantage + yfinance
  alpha_vantage.py      ← also runnable standalone for sanity tests
  yfin.py               ← also runnable standalone
  requirements.txt
.mcp.json               ← registers the tradingagents MCP server
CLAUDE.md               ← shared context loaded by every teammate
LICENSE / NOTICE        ← Apache-2.0 + upstream attribution
```

The MCP server exposes these tools (callable by agents as
`mcp__tradingagents__<name>`):

- **Alpha Vantage:** `quote`, `fundamentals`, `balance_sheet`, `cashflow`,
  `income`, `news`, `global_news`, `technical` (MACD/RSI/SMA/EMA), `insider`
- **yfinance:** `history`, `info`, `yfin_news`

---

## Caveats

- **Free-tier Alpha Vantage = 25 requests/day.** The MCP server caches results
  for 1h on disk in `${CLAUDE_PLUGIN_DATA}/cache/`. A full `/analyze` run on a
  fresh ticker burns ~10–15 of those, so you can comfortably do 1–2 analyses
  per day on the free tier (or upgrade your key).
- **Token cost scales linearly with the team.** A full run uses Opus 4× (the
  decision-makers) and Sonnet 4× (the analysts). Expect a non-trivial bill
  per ticker.
- **Agent Teams is experimental.** If `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
  is unset, the orchestrator falls back to sequential subagent invocation
  (skipping the live mailbox debate — bull/bear write sequentially instead).
- **Plan-approval loop is capped at 2 iterations** to avoid hangs if the risk
  manager and trader disagree indefinitely.

---

## Contributing

PRs welcome — especially:

- New MCP tools (e.g., options chain, short interest, earnings transcripts).
- Sharper system prompts for the analysts.
- Fallback logic for when Alpha Vantage rate-limits.
- Adapters for additional brokers / data providers.

Please keep changes Apache-2.0-compatible and update `NOTICE` for any
substantial code derived from third parties.

---

## License

Apache License 2.0. See [`LICENSE`](LICENSE) for the full text and
[`NOTICE`](NOTICE) for attribution to the upstream
[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
project.

# TradingAgents — Multi-Agent Trading Framework (Claude Code Plugin)

This project is a Claude-Code-native port of [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (Apache-2.0). It uses **Agent Teams** (experimental) to orchestrate 8 specialized trading roles that collaborate on a buy/hold/sell decision for a given ticker.

Distributed as a Claude Code plugin: `agents/`, `skills/`, `commands/` live at the plugin root, and an MCP server (`tools/mcp_server.py`) wraps Alpha Vantage + yfinance.

## Architecture

| Role | Model | Purpose |
|---|---|---|
| Fundamentals Analyst | sonnet | Earnings, balance sheet, ratios |
| Technical Analyst | sonnet | MACD/RSI/SMA/EMA + price action |
| News Analyst | sonnet | Company + macro news |
| Sentiment Analyst | sonnet | Social/news sentiment scoring |
| Bull Researcher | opus | Argues *for* investment |
| Bear Researcher | opus | Argues *against* — debates Bull directly |
| Trader | opus | Synthesizes debate → trade plan |
| Risk Manager | opus | Approves/rejects trader's plan |

The **Lead** (your main session) acts as Portfolio Manager: spawns the team, coordinates, synthesizes the final decision.

## Workflow (orchestrated by `trading-debate` skill)

```
[Lead] creates 7 tasks in shared task list
  ├── analyze-fundamentals   → fundamentals-analyst (sonnet)   ─┐
  ├── analyze-technical      → technical-analyst (sonnet)       ├─ parallel
  ├── analyze-news           → news-analyst (sonnet)            │
  └── analyze-sentiment      → sentiment-analyst (sonnet)      ─┘
        ↓ (TeammateIdle on all 4)
  └── bull-bear-debate       → bull + bear (opus, mailbox debate, max 2 rounds)
        ↓
  └── trader-decision        → trader (opus, requires plan approval)
        ↓ (plan approval request to risk-manager)
  └── risk-approval          → risk-manager (opus, approve/reject loop, max 2x)
        ↓
[Lead] synthesizes Final Output
```

## File Conventions

All inter-agent state lives in `state/` (gitignored):

- `state/{TICKER}_fundamentals.md` — fundamentals analyst report
- `state/{TICKER}_technical.md` — technical analyst report
- `state/{TICKER}_news.md` — news analyst report
- `state/{TICKER}_sentiment.md` — sentiment analyst report
- `state/{TICKER}_debate.md` — bull/bear debate transcript (appended live)
- `state/{TICKER}_trader_plan.md` — trader's proposed plan
- `state/{TICKER}_decision.md` — final decision after risk approval

**Always end an analyst/trader report with:**
1. A Markdown summary table (key facts/levels/scores)
2. The literal line: `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`

## Tools (MCP server `tradingagents`)

The `tools/mcp_server.py` FastMCP server is registered in `.mcp.json` and exposes the following tools to all agents (each must be in the agent's `tools:` whitelist as `mcp__tradingagents__<name>`):

### Alpha Vantage backed
- `quote(ticker)` — GLOBAL_QUOTE snapshot
- `fundamentals(ticker)` — OVERVIEW (ratios, profile, target)
- `balance_sheet(ticker)`, `cashflow(ticker)`, `income(ticker)` — financial statements
- `news(ticker, days=7)` — ticker news + sentiment scores
- `global_news(topics)` — macro/topic news
- `technical(ticker, indicator, period)` — MACD/RSI/SMA/EMA
- `insider(ticker)` — recent insider transactions

### yfinance backed (no API key)
- `history(ticker, period, interval)` — OHLC bars
- `info(ticker)` — broad company snapshot
- `yfin_news(ticker)` — recent yfinance headlines

Responses are cached on disk (`${CLAUDE_PLUGIN_DATA}/cache/` or `state/cache/`) for 1h to stretch the Alpha Vantage free-tier 25 req/day budget.

### WebSearch / WebFetch
Native Claude Code tools. News + Sentiment analysts use them for breaking headlines, Reddit/Twitter/Stocktwits discussions, SEC filings.

## Setup

End users (plugin install):
1. `/plugin marketplace add namikos/tradingagents`
2. `/plugin install tradingagents@namikos-tradingagents`
3. Claude Code prompts for the Alpha Vantage API key (free at https://www.alphavantage.co/support/#api-key) and stores it via `userConfig` (sensitive → OS keychain).
4. Make sure `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set in your Claude Code settings.
5. `pip install -r tools/requirements.txt` (the MCP server needs `mcp[cli]`, `httpx`, `yfinance`).
6. Use `/analyze TICKER` or ask: *"Run trading-debate on NVDA"*.

## Caveats

- Alpha Vantage free tier: **25 requests/day**. Cache helps but plan accordingly.
- Token costs scale linearly per teammate — a full run uses Opus 4× and Sonnet 4×.
- Plan-Approval loop is capped at 2 iterations to avoid hangs.
- This is **NOT** financial advice. Output is research, not a trading recommendation.

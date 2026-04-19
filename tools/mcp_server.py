#!/usr/bin/env python3
"""TradingAgents MCP server.

Exposes Alpha Vantage + yfinance data tools over MCP/stdio so that
agents inside Claude Code can call them as native MCP tools instead of
shelling out to Bash.

STDIO transport: NEVER print to stdout — that channel carries the JSON-RPC
protocol. All diagnostics go to stderr.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx
import yfinance as yf
from mcp.server.fastmcp import FastMCP

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="[mcp:tradingagents] %(message)s")
log = logging.getLogger(__name__)

ALPHA_BASE = "https://www.alphavantage.co/query"
CACHE_TTL = 3600

DATA_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_DATA")
                 or os.environ.get("TRADINGAGENTS_DATA")
                 or Path(__file__).resolve().parent.parent / "state")
CACHE_DIR = DATA_ROOT / "cache"


def _api_key() -> str:
    k = os.environ.get("ALPHA_VANTAGE_KEY", "").strip()
    if not k:
        raise RuntimeError(
            "ALPHA_VANTAGE_KEY is not configured. Set it via the plugin's "
            "userConfig (api_token) or the ALPHA_VANTAGE_KEY env var."
        )
    return k


def _cache_path(params: dict) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(urlencode(sorted(params.items())).encode()).hexdigest()[:16]
    return CACHE_DIR / f"{params.get('function', 'q')}_{h}.json"


def _alpha_request(params: dict) -> dict:
    full = {**params, "apikey": _api_key()}
    cache_file = _cache_path({k: v for k, v in full.items() if k != "apikey"})
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < CACHE_TTL:
        log.info("cache hit %s", cache_file.name)
        return json.loads(cache_file.read_text())
    log.info("alpha vantage request %s", params.get("function"))
    r = httpx.get(ALPHA_BASE, params=full, timeout=30.0)
    r.raise_for_status()
    data = r.json()
    if "Note" in data or "Information" in data:
        log.warning("API note: %s", data.get("Note") or data.get("Information"))
    cache_file.write_text(json.dumps(data))
    return data


mcp = FastMCP("tradingagents")


@mcp.tool()
def quote(ticker: str) -> dict:
    """Latest GLOBAL_QUOTE snapshot (price, change, volume) for a ticker."""
    return _alpha_request({"function": "GLOBAL_QUOTE", "symbol": ticker})


@mcp.tool()
def fundamentals(ticker: str) -> dict:
    """Company OVERVIEW: market cap, sector, ratios, dividend, analyst target."""
    return _alpha_request({"function": "OVERVIEW", "symbol": ticker})


@mcp.tool()
def balance_sheet(ticker: str) -> dict:
    """Annual + quarterly BALANCE_SHEET reports."""
    return _alpha_request({"function": "BALANCE_SHEET", "symbol": ticker})


@mcp.tool()
def cashflow(ticker: str) -> dict:
    """Annual + quarterly CASH_FLOW reports."""
    return _alpha_request({"function": "CASH_FLOW", "symbol": ticker})


@mcp.tool()
def income(ticker: str) -> dict:
    """Annual + quarterly INCOME_STATEMENT reports."""
    return _alpha_request({"function": "INCOME_STATEMENT", "symbol": ticker})


@mcp.tool()
def news(ticker: str, days: int = 7, limit: int = 20) -> dict:
    """News + sentiment scores for a ticker over the last `days` days."""
    params = {"function": "NEWS_SENTIMENT", "tickers": ticker, "limit": str(limit)}
    if days:
        time_from = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y%m%dT%H%M")
        params["time_from"] = time_from
    return _alpha_request(params)


@mcp.tool()
def global_news(topics: Optional[str] = None, limit: int = 20) -> dict:
    """Macro/global NEWS_SENTIMENT. Topics e.g. 'economy_macro,technology'."""
    params = {"function": "NEWS_SENTIMENT", "limit": str(limit)}
    if topics:
        params["topics"] = topics
    return _alpha_request(params)


@mcp.tool()
def technical(ticker: str, indicator: str = "MACD", interval: str = "daily",
              series_type: str = "close", period: int = 14) -> dict:
    """Technical indicator (MACD/RSI/SMA/EMA) series for a ticker."""
    fn = indicator.upper()
    if fn not in {"MACD", "RSI", "SMA", "EMA"}:
        raise ValueError(f"unsupported indicator {indicator}")
    params = {"function": fn, "symbol": ticker, "interval": interval,
              "series_type": series_type}
    if fn == "MACD":
        params.update({"fastperiod": "12", "slowperiod": "26", "signalperiod": "9"})
    else:
        params["time_period"] = str(period)
    return _alpha_request(params)


@mcp.tool()
def insider(ticker: str) -> dict:
    """Recent INSIDER_TRANSACTIONS for a ticker."""
    return _alpha_request({"function": "INSIDER_TRANSACTIONS", "symbol": ticker})


@mcp.tool()
def history(ticker: str, period: str = "6mo", interval: str = "1d") -> list[dict]:
    """Historical OHLC bars from yfinance. period: 1d..max. interval: 1m..3mo."""
    log.info("yfinance history %s %s/%s", ticker, period, interval)
    df = yf.Ticker(ticker).history(period=period, interval=interval)
    df = df.reset_index()
    if "Date" in df.columns:
        df["Date"] = df["Date"].astype(str)
    elif "Datetime" in df.columns:
        df["Datetime"] = df["Datetime"].astype(str)
    return json.loads(df.to_json(orient="records", date_format="iso"))


@mcp.tool()
def info(ticker: str) -> dict:
    """yfinance Ticker.info — broad company snapshot."""
    log.info("yfinance info %s", ticker)
    return yf.Ticker(ticker).info


@mcp.tool()
def yfin_news(ticker: str, limit: int = 10) -> list[dict]:
    """Recent yfinance news headlines for a ticker."""
    log.info("yfinance news %s", ticker)
    items = yf.Ticker(ticker).news or []
    return items[:limit]


if __name__ == "__main__":
    mcp.run()

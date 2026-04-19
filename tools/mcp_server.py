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

try:
    from toon import encode as _toon_encode
except ImportError:  # pragma: no cover
    _toon_encode = None  # falls back to JSON in tools that opt in to TOON


def _maybe_toon(value) -> str:
    """Encode `value` as TOON when the python-toon package is installed.

    Falls back to compact JSON when TOON isn't available so agents always
    receive a parseable string. TOON's tabular form gives ~40-60% token
    reduction on uniform arrays-of-objects (history bars, indicator series,
    aggregated signal footers).
    """
    if _toon_encode is not None:
        try:
            return _toon_encode(value)
        except Exception as exc:  # pragma: no cover
            log.warning("TOON encode failed, falling back to JSON: %s", exc)
    return json.dumps(value, default=str)

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover - defensive
    _HAS_NUMPY = False
    np = None  # type: ignore

try:
    import pandas as pd
    _HAS_PANDAS = True
except ImportError:  # pragma: no cover
    _HAS_PANDAS = False
    pd = None  # type: ignore

try:
    from scipy import stats as _scipy_stats
    _HAS_SCIPY = True
except ImportError:  # pragma: no cover
    _HAS_SCIPY = False
    _scipy_stats = None  # type: ignore

# ---- v2.1 optional dependencies ----
try:
    import praw
except ImportError:  # pragma: no cover
    praw = None

try:
    from transformers import pipeline as _hf_pipeline
except ImportError:  # pragma: no cover
    _hf_pipeline = None

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

try:
    import empyrical
except ImportError:  # pragma: no cover
    empyrical = None

try:
    import mlfinlab
except ImportError:  # pragma: no cover
    mlfinlab = None

try:
    from bs4 import BeautifulSoup as _BS
except ImportError:  # pragma: no cover
    _BS = None

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="[mcp:tradingagents] %(message)s")
log = logging.getLogger(__name__)

ALPHA_BASE = "https://www.alphavantage.co/query"
CACHE_TTL = 3600

DATA_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_DATA")
                 or os.environ.get("TRADINGAGENTS_DATA")
                 or Path(__file__).resolve().parent.parent / "state")
CACHE_DIR = DATA_ROOT / "cache"


def _state_dir() -> Path:
    """Locate the state/ directory the agents write reports to.

    Agents use the Read tool which is CWD-relative (Claude Code's CWD = the
    user's project root). The MCP server inherits that CWD, so plain
    `Path("state")` works in the common case. Fall back to other plausible
    locations if it doesn't exist yet.
    """
    for candidate in (Path("state"), Path.cwd() / "state", DATA_ROOT):
        if candidate.exists() and candidate.is_dir():
            return candidate
    return Path("state")


# ---- v2.1 API helpers ----

_FRED_BASE = "https://api.stlouisfed.org/fred"
_FINNHUB_BASE = "https://finnhub.io/api/v1"
_FMP_BASE = "https://financialmodelingprep.com/api/v3"
_SEC_HEADERS = {"User-Agent": "tradingagents v2.1 contact@example.com"}


def _fred_get(endpoint: str, params: dict) -> dict | None:
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return None
    params = {**params, "api_key": key, "file_type": "json"}
    try:
        r = httpx.get(f"{_FRED_BASE}/{endpoint}", params=params, timeout=20.0)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("FRED API failure: %s", exc)
        return {"error": f"FRED API failure: {exc}"}


def _finnhub_get(endpoint: str, params: dict | None = None) -> dict | list | None:
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return None
    params = {**(params or {}), "token": key}
    try:
        r = httpx.get(f"{_FINNHUB_BASE}/{endpoint}", params=params, timeout=20.0)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("Finnhub API failure: %s", exc)
        return {"error": f"Finnhub API failure: {exc}"}


def _fmp_get(endpoint: str, params: dict | None = None) -> list | dict | None:
    key = os.environ.get("FMP_API_KEY")
    if not key:
        return None
    params = {**(params or {}), "apikey": key}
    try:
        r = httpx.get(f"{_FMP_BASE}/{endpoint}", params=params, timeout=30.0)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("FMP API failure: %s", exc)
        return {"error": f"FMP API failure: {exc}"}


_REDDIT_CLIENT = None


def _reddit_client():
    global _REDDIT_CLIENT
    if _REDDIT_CLIENT is not None:
        return _REDDIT_CLIENT
    if praw is None:
        return None
    cid = os.environ.get("REDDIT_CLIENT_ID")
    csec = os.environ.get("REDDIT_CLIENT_SECRET")
    ua = os.environ.get("REDDIT_USER_AGENT", "tradingagents/2.1")
    if not cid or not csec:
        return None
    try:
        _REDDIT_CLIENT = praw.Reddit(client_id=cid, client_secret=csec, user_agent=ua)
        return _REDDIT_CLIENT
    except Exception as exc:
        log.warning("Reddit client init failed: %s", exc)
        return None


_FINBERT_PIPE = None


def _finbert_pipeline():
    global _FINBERT_PIPE
    if _FINBERT_PIPE is not None:
        return _FINBERT_PIPE
    if _hf_pipeline is None:
        return None
    try:
        _FINBERT_PIPE = _hf_pipeline("text-classification", model="ProsusAI/finbert", top_k=None)
        return _FINBERT_PIPE
    except Exception as exc:
        log.warning("FinBERT init failed: %s", exc)
        return None


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
              series_type: str = "close", period: int = 14) -> str:
    """Technical indicator (MACD/RSI/SMA/EMA) series for a ticker.

    Returns TOON-encoded tabular string with the date-keyed series flattened
    to `series[N]{date,...indicator-fields}` — ~50% fewer tokens than the
    nested Alpha Vantage JSON. Last 120 datapoints only (sufficient for any
    standard window; full history available via Alpha Vantage directly).
    """
    fn = indicator.upper()
    if fn not in {"MACD", "RSI", "SMA", "EMA"}:
        raise ValueError(f"unsupported indicator {indicator}")
    params = {"function": fn, "symbol": ticker, "interval": interval,
              "series_type": series_type}
    if fn == "MACD":
        params.update({"fastperiod": "12", "slowperiod": "26", "signalperiod": "9"})
    else:
        params["time_period"] = str(period)
    raw = _alpha_request(params)

    # Find the "Technical Analysis: <FN>" key — Alpha Vantage names it that way.
    series_key = next((k for k in raw if k.startswith("Technical Analysis")), None)
    if series_key is None:
        return _maybe_toon({"ticker": ticker.upper(), "indicator": fn, "raw": raw})
    series = raw.get(series_key, {})
    rows = []
    for date_str in sorted(series.keys(), reverse=True)[:120]:
        row = {"date": date_str}
        for k, v in series[date_str].items():
            try:
                row[k.lower()] = float(v)
            except (TypeError, ValueError):
                row[k.lower()] = v
        rows.append(row)
    rows.reverse()  # chronological order
    return _maybe_toon({
        "ticker": ticker.upper(),
        "indicator": fn,
        "interval": interval,
        "period": period,
        "series": rows,
    })


@mcp.tool()
def insider(ticker: str) -> dict:
    """Recent INSIDER_TRANSACTIONS for a ticker."""
    return _alpha_request({"function": "INSIDER_TRANSACTIONS", "symbol": ticker})


@mcp.tool()
def history(ticker: str, period: str = "6mo", interval: str = "1d") -> str:
    """Historical OHLC bars from yfinance. period: 1d..max. interval: 1m..3mo.

    Returns TOON-encoded tabular string (~40-60% fewer tokens than JSON)
    with shape `bars[N]{date,open,high,low,close,volume}`. Agents parse TOON
    natively from the header row — no separate format instruction needed.
    """
    log.info("yfinance history %s %s/%s", ticker, period, interval)
    df = yf.Ticker(ticker).history(period=period, interval=interval)
    df = df.reset_index()
    if "Date" in df.columns:
        df["Date"] = df["Date"].astype(str)
    elif "Datetime" in df.columns:
        df["Datetime"] = df["Datetime"].astype(str)
    records = json.loads(df.to_json(orient="records", date_format="iso"))
    return _maybe_toon({"ticker": ticker.upper(), "bars": records})


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


# ---------------------------------------------------------------------------
# Workpackage 2 — Quantitative finance + extended data tools
# ---------------------------------------------------------------------------

def _generic_cache_key(namespace: str, payload: dict) -> Path:
    """Build a deterministic cache file path under CACHE_DIR for arbitrary tools."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(urlencode(sorted(payload.items())).encode()).hexdigest()[:16]
    return CACHE_DIR / f"{namespace}_{h}.json"


def _get_cache(namespace: str, payload: dict, ttl: int = CACHE_TTL) -> Optional[dict]:
    p = _generic_cache_key(namespace, payload)
    if p.exists() and (time.time() - p.stat().st_mtime) < ttl:
        try:
            log.info("cache hit %s", p.name)
            return json.loads(p.read_text())
        except Exception as exc:  # pragma: no cover
            log.warning("cache read failed %s: %s", p.name, exc)
    return None


def _set_cache(namespace: str, payload: dict, value: dict) -> None:
    p = _generic_cache_key(namespace, payload)
    try:
        p.write_text(json.dumps(value, default=str))
    except Exception as exc:  # pragma: no cover
        log.warning("cache write failed %s: %s", p.name, exc)


def _latest_free_cash_flow(ticker: str) -> tuple[Optional[float], Optional[str]]:
    """Pull most recent annual FCF using the existing cashflow() AV tool.

    Returns (fcf, fiscal_date_ending) or (None, None) on failure.
    """
    try:
        data = _alpha_request({"function": "CASH_FLOW", "symbol": ticker})
    except Exception as exc:
        log.warning("cashflow fetch failed for %s: %s", ticker, exc)
        return None, None
    reports = data.get("annualReports") or []
    if not reports:
        return None, None
    r0 = reports[0]
    try:
        ocf = float(r0.get("operatingCashflow", "None"))
        capex = float(r0.get("capitalExpenditures", "None"))
        # AV reports capex as a positive number representing an outflow
        fcf = ocf - abs(capex)
        return fcf, r0.get("fiscalDateEnding")
    except (TypeError, ValueError):
        return None, None


@mcp.tool()
def dcf(ticker: str, growth_rate: float = 0.10, discount_rate: float = 0.10,
        terminal_growth: float = 0.03, years: int = 10) -> dict:
    """Discounted-cash-flow intrinsic-value estimate.

    Uses the company's most recent free cash flow (operatingCashflow - |capex|
    from the latest annual cashflow() report), projects it forward `years`
    years at `growth_rate`, applies a Gordon-growth terminal value with
    `terminal_growth`, and discounts back at `discount_rate`. Returns an
    intrinsic value per share plus a margin-of-safety vs. the current price.

    Args:
      ticker: stock symbol.
      growth_rate: annual FCF growth during the projection window (decimal).
      discount_rate: WACC / required return used to discount cash flows.
      terminal_growth: perpetual growth assumption used in terminal value.
      years: length of explicit projection window.
    """
    log.info("dcf %s g=%.3f r=%.3f tg=%.3f y=%d", ticker, growth_rate,
             discount_rate, terminal_growth, years)

    if discount_rate <= terminal_growth:
        return {"error": "discount_rate must exceed terminal_growth for a finite "
                         "terminal value"}

    fcf0, fiscal_date = _latest_free_cash_flow(ticker)
    if fcf0 is None:
        return {"error": f"could not derive most-recent FCF for {ticker}"}

    # Shares outstanding + current price from OVERVIEW + GLOBAL_QUOTE.
    try:
        overview = _alpha_request({"function": "OVERVIEW", "symbol": ticker})
        shares_out = float(overview.get("SharesOutstanding") or 0) or None
    except Exception as exc:
        log.warning("overview fetch failed: %s", exc)
        shares_out = None

    try:
        q = _alpha_request({"function": "GLOBAL_QUOTE", "symbol": ticker})
        current_price = float(q.get("Global Quote", {}).get("05. price") or 0) or None
    except Exception as exc:
        log.warning("quote fetch failed: %s", exc)
        current_price = None

    projected = []
    pv_sum = 0.0
    fcf_t = fcf0
    for t in range(1, years + 1):
        fcf_t = fcf_t * (1.0 + growth_rate)
        pv = fcf_t / ((1.0 + discount_rate) ** t)
        projected.append({"year": t, "fcf": fcf_t, "pv": pv})
        pv_sum += pv

    terminal_fcf = fcf_t * (1.0 + terminal_growth)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth)
    terminal_pv = terminal_value / ((1.0 + discount_rate) ** years)
    enterprise_pv = pv_sum + terminal_pv

    per_share = (enterprise_pv / shares_out) if shares_out else None
    mos_pct = None
    if per_share and current_price:
        mos_pct = round((per_share - current_price) / current_price * 100, 2)

    return {
        "ticker": ticker.upper(),
        "per_share_value": round(per_share, 4) if per_share else None,
        "total_pv": round(enterprise_pv, 2),
        "terminal_pv": round(terminal_pv, 2),
        "projected_fcf": [
            {"year": p["year"], "fcf": round(p["fcf"], 2), "pv": round(p["pv"], 2)}
            for p in projected
        ],
        "assumptions": {
            "starting_fcf": fcf0,
            "fiscal_date_ending": fiscal_date,
            "growth_rate": growth_rate,
            "discount_rate": discount_rate,
            "terminal_growth": terminal_growth,
            "years": years,
        },
        "shares_outstanding": shares_out,
        "current_price": current_price,
        "margin_of_safety_pct": mos_pct,
    }


@mcp.tool()
def kelly_position_size(win_prob: float, win_pct: float, loss_pct: float,
                        fraction: float = 0.5) -> dict:
    """Kelly Criterion position sizing.

    Returns the optimal fraction of portfolio to risk on a single trade.
    Formula: f* = (p*b - q) / b   with p=win_prob, q=1-p, b=win_pct/loss_pct.
    `fraction` defaults to 0.5 (half-Kelly) for safety; pass 1.0 for full Kelly.

    Args:
      win_prob: probability the trade is a winner (0..1).
      win_pct: average win as a positive decimal (e.g. 0.20 = +20%).
      loss_pct: average loss as a positive decimal (e.g. 0.10 = -10%).
      fraction: scaler applied to f* (1.0 = full, 0.5 = half-Kelly, ...).
    """
    log.info("kelly p=%.3f w=%.3f l=%.3f frac=%.2f", win_prob, win_pct, loss_pct, fraction)

    if not (0.0 <= win_prob <= 1.0):
        return {"error": "win_prob must be between 0 and 1"}
    if loss_pct <= 0 or win_pct <= 0:
        return {"error": "win_pct and loss_pct must be positive decimals"}

    p = win_prob
    q = 1.0 - p
    b = win_pct / loss_pct
    kelly_full = (p * b - q) / b
    kelly_recommended = kelly_full * fraction
    expected_value = p * win_pct - q * loss_pct
    edge = p * b - q

    notes = []
    if kelly_full <= 0:
        notes.append("Negative edge — Kelly says do not take this trade.")
    if kelly_recommended > 0.25:
        notes.append("Recommended size > 25% of portfolio — consider further scaling down.")
    if fraction == 0.5:
        notes.append("Half-Kelly applied (default). Pass fraction=1.0 for full Kelly.")

    return {
        "kelly_full": round(kelly_full, 6),
        "kelly_recommended": round(max(kelly_recommended, 0.0), 6),
        "expected_value": round(expected_value, 6),
        "edge": round(edge, 6),
        "notes": notes,
    }


@mcp.tool()
def atr_stop(ticker: str, period: int = 14, multiplier: float = 2.0) -> dict:
    """ATR-based stop-loss level.

    Computes Average True Range over `period` daily bars (yfinance) and
    returns a suggested stop at current_price - multiplier*ATR (long) and
    current_price + multiplier*ATR (short).

    Args:
      ticker: stock symbol.
      period: ATR window in trading days.
      multiplier: how many ATRs of slack to give the stop.
    """
    log.info("atr_stop %s period=%d mult=%.2f", ticker, period, multiplier)
    if not _HAS_PANDAS or not _HAS_NUMPY:
        return {"error": "pandas/numpy not installed; cannot compute ATR"}

    try:
        df = yf.Ticker(ticker).history(period="6mo", interval="1d")
    except Exception as exc:
        return {"error": f"yfinance history failed: {exc}"}
    if df is None or df.empty or len(df) < period + 1:
        return {"error": f"insufficient price history for ATR (need >{period} bars)"}

    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    prev_close = close.shift(1)

    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Wilder's smoothing via EMA with alpha=1/period
    atr_series = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    atr_value = float(atr_series.iloc[-1])
    current_price = float(close.iloc[-1])

    return {
        "ticker": ticker.upper(),
        "atr": round(atr_value, 6),
        "current_price": round(current_price, 6),
        "suggested_stop_long": round(current_price - multiplier * atr_value, 6),
        "suggested_stop_short": round(current_price + multiplier * atr_value, 6),
        "period": period,
        "multiplier": multiplier,
        "as_of": str(df.index[-1].date()),
    }


def _annualization_factor() -> int:
    return 252


@mcp.tool()
def sharpe_ratio(returns: list, risk_free_rate: float = 0.04) -> dict:
    """Annualized Sharpe ratio for a daily-return series.

    `returns` is a list of daily returns expressed as decimals (e.g. 0.012 = +1.2%).
    `risk_free_rate` is the annualized risk-free rate as a decimal (default 4%).
    """
    log.info("sharpe n=%d rf=%.3f", len(returns) if returns else 0, risk_free_rate)
    if not _HAS_NUMPY:
        return {"error": "numpy not installed"}
    if not returns or len(returns) < 2:
        return {"error": "need at least 2 return observations"}

    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size < 2:
        return {"error": "not enough valid (non-nan) returns"}

    n = _annualization_factor()
    daily_rf = risk_free_rate / n
    excess = arr - daily_rf
    std = float(arr.std(ddof=1))
    if std == 0:
        return {"error": "zero variance in returns"}

    sharpe = float(excess.mean() / std) * (n ** 0.5)
    mean_annual = float(arr.mean()) * n
    annual_vol = std * (n ** 0.5)

    return {
        "sharpe": round(sharpe, 4),
        "mean_annual_return": round(mean_annual, 6),
        "annual_volatility": round(annual_vol, 6),
        "n_observations": int(arr.size),
        "risk_free_rate": risk_free_rate,
    }


@mcp.tool()
def sortino_ratio(returns: list, risk_free_rate: float = 0.04) -> dict:
    """Annualized Sortino ratio (penalizes downside deviation only).

    Like Sharpe but the denominator uses only negative excess returns.
    `returns` is a list of daily decimal returns.
    """
    log.info("sortino n=%d rf=%.3f", len(returns) if returns else 0, risk_free_rate)
    if not _HAS_NUMPY:
        return {"error": "numpy not installed"}
    if not returns or len(returns) < 2:
        return {"error": "need at least 2 return observations"}

    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size < 2:
        return {"error": "not enough valid (non-nan) returns"}

    n = _annualization_factor()
    daily_rf = risk_free_rate / n
    excess = arr - daily_rf
    downside = excess[excess < 0]
    if downside.size == 0:
        return {"error": "no downside observations — Sortino undefined"}

    # Standard formulation: sqrt(mean(min(0, excess)^2))
    downside_dev = float(np.sqrt(np.mean(np.minimum(excess, 0.0) ** 2)))
    if downside_dev == 0:
        return {"error": "zero downside deviation"}

    sortino = float(excess.mean() / downside_dev) * (n ** 0.5)
    mean_annual = float(arr.mean()) * n
    annual_downside_vol = downside_dev * (n ** 0.5)

    return {
        "sortino": round(sortino, 4),
        "mean_annual_return": round(mean_annual, 6),
        "annual_downside_volatility": round(annual_downside_vol, 6),
        "n_observations": int(arr.size),
        "n_downside": int(downside.size),
        "risk_free_rate": risk_free_rate,
    }


@mcp.tool()
def max_drawdown(equity_curve: list) -> dict:
    """Maximum drawdown of an equity curve.

    `equity_curve` is a list of portfolio values over time (any base unit).
    Returns the worst peak-to-trough decline plus indices and recovery point
    (or null if equity never reclaimed the prior peak).
    """
    log.info("max_drawdown n=%d", len(equity_curve) if equity_curve else 0)
    if not equity_curve or len(equity_curve) < 2:
        return {"error": "need at least 2 equity points"}
    if not _HAS_NUMPY:
        return {"error": "numpy not installed"}

    arr = np.asarray(equity_curve, dtype=float)
    if np.any(arr <= 0):
        return {"error": "equity values must be positive"}

    running_peak = np.maximum.accumulate(arr)
    drawdowns = (arr - running_peak) / running_peak
    trough_idx = int(np.argmin(drawdowns))
    max_dd = float(drawdowns[trough_idx])
    # Peak is the last index <= trough_idx where equity == running_peak[trough_idx]
    peak_value = float(running_peak[trough_idx])
    peak_idx = int(np.where(arr[: trough_idx + 1] == peak_value)[0][0])
    trough_value = float(arr[trough_idx])

    recovery_idx = None
    if trough_idx < len(arr) - 1:
        post = arr[trough_idx + 1:]
        recovered = np.where(post >= peak_value)[0]
        if recovered.size > 0:
            recovery_idx = int(trough_idx + 1 + recovered[0])

    return {
        "max_dd_pct": round(max_dd * 100, 4),
        "peak_idx": peak_idx,
        "trough_idx": trough_idx,
        "peak_value": peak_value,
        "trough_value": trough_value,
        "recovery_idx": recovery_idx,
        "n_observations": int(arr.size),
    }


@mcp.tool()
def historical_price(ticker: str, date: str) -> dict:
    """Closing price on a specific date (YYYY-MM-DD).

    Walks backwards to the nearest prior trading day if `date` falls on a
    weekend, holiday, or before the security's listing.
    """
    log.info("historical_price %s %s", ticker, date)
    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return {"error": "date must be in YYYY-MM-DD format"}

    # Pull a 14-day window ending on `date+1` so weekends/holidays resolve.
    start = (target - timedelta(days=14)).isoformat()
    end = (target + timedelta(days=1)).isoformat()
    try:
        df = yf.Ticker(ticker).history(start=start, end=end, interval="1d")
    except Exception as exc:
        return {"error": f"yfinance history failed: {exc}"}
    if df is None or df.empty:
        return {"error": "no price data in window"}

    # Filter to bars on or before target.
    df = df[df.index.date <= target]
    if df.empty:
        return {"error": f"no trading day on or before {date}"}

    bar = df.iloc[-1]
    actual = df.index[-1].date().isoformat()
    return {
        "ticker": ticker.upper(),
        "requested_date": date,
        "actual_date": actual,
        "close": round(float(bar["Close"]), 6),
        "volume": int(bar["Volume"]) if not pd.isna(bar.get("Volume")) else None,
    }


@mcp.tool()
def factor_exposure(ticker: str, period: str = "1y") -> dict:
    """Factor regression: beta to SPY plus sector correlation.

    Runs an OLS of the ticker's daily returns on SPY's daily returns over
    the requested yfinance `period` (e.g. '6mo', '1y', '2y'), then also
    computes correlation against the relevant sector ETF (XLK, XLF, ...)
    when sector is detectable from yfinance .info.
    """
    log.info("factor_exposure %s period=%s", ticker, period)
    if not _HAS_PANDAS or not _HAS_NUMPY:
        return {"error": "pandas/numpy not installed"}

    sector_etf_map = {
        "Technology": "XLK",
        "Financial Services": "XLF",
        "Financials": "XLF",
        "Healthcare": "XLV",
        "Consumer Cyclical": "XLY",
        "Consumer Defensive": "XLP",
        "Energy": "XLE",
        "Industrials": "XLI",
        "Basic Materials": "XLB",
        "Real Estate": "XLRE",
        "Utilities": "XLU",
        "Communication Services": "XLC",
    }

    try:
        info_data = yf.Ticker(ticker).info or {}
    except Exception:
        info_data = {}
    sector = info_data.get("sector")
    sector_etf = sector_etf_map.get(sector) if sector else None

    symbols = [ticker, "SPY"]
    if sector_etf and sector_etf != ticker.upper():
        symbols.append(sector_etf)

    try:
        data = yf.download(symbols, period=period, interval="1d",
                           progress=False, auto_adjust=True)["Close"]
    except Exception as exc:
        return {"error": f"yfinance download failed: {exc}"}
    if data is None or (hasattr(data, "empty") and data.empty):
        return {"error": "no price data returned"}
    if isinstance(data, pd.Series):
        return {"error": "could not assemble multi-symbol panel"}

    returns = data.pct_change().dropna()
    if ticker not in returns.columns or "SPY" not in returns.columns or len(returns) < 5:
        return {"error": "insufficient overlapping return history"}

    y = returns[ticker].astype(float).values
    x = returns["SPY"].astype(float).values

    var_x = float(np.var(x, ddof=1))
    if var_x == 0:
        return {"error": "SPY return variance is zero"}
    cov = float(np.cov(y, x, ddof=1)[0, 1])
    beta = cov / var_x
    alpha_daily = float(np.mean(y) - beta * np.mean(x))
    alpha_annual = alpha_daily * _annualization_factor()
    corr = float(np.corrcoef(y, x)[0, 1])
    r_squared = corr * corr

    sector_corr = None
    if sector_etf and sector_etf in returns.columns:
        z = returns[sector_etf].astype(float).values
        if np.std(z) > 0 and np.std(y) > 0:
            sector_corr = float(np.corrcoef(y, z)[0, 1])

    return {
        "ticker": ticker.upper(),
        "beta_spy": round(beta, 4),
        "alpha_annual": round(alpha_annual, 6),
        "r_squared": round(r_squared, 4),
        "sector": sector,
        "sector_etf": sector_etf,
        "sector_correlation": round(sector_corr, 4) if sector_corr is not None else None,
        "period": period,
        "n_observations": int(len(returns)),
    }


@mcp.tool()
def options_chain(ticker: str) -> dict:
    """Options snapshot via yfinance (nearest-expiry put/call activity + IV).

    Returns put/call ratio, ATM implied vols, 25-delta-ish skew, and total
    volumes across the nearest-expiry chain. Cached for 1h.
    """
    log.info("options_chain %s", ticker)
    cached = _get_cache("options_chain", {"t": ticker.upper()}, ttl=CACHE_TTL)
    if cached is not None:
        return cached

    try:
        t = yf.Ticker(ticker)
        expiries = list(t.options or [])
    except Exception as exc:
        return {"error": f"yfinance options failed: {exc}"}
    if not expiries:
        return {"error": "no listed options for ticker"}

    nearest = expiries[0]
    try:
        chain = t.option_chain(nearest)
        calls = chain.calls
        puts = chain.puts
    except Exception as exc:
        return {"error": f"option_chain fetch failed: {exc}"}

    try:
        spot = float(t.history(period="5d", interval="1d")["Close"].iloc[-1])
    except Exception:
        spot = None

    def _atm_iv(df) -> Optional[float]:
        if df is None or df.empty or spot is None or "impliedVolatility" not in df.columns:
            return None
        idx = (df["strike"] - spot).abs().idxmin()
        try:
            return float(df.loc[idx, "impliedVolatility"])
        except Exception:
            return None

    def _delta_proxy_iv(df, target_delta: float) -> Optional[float]:
        """Pick option whose strike sits at roughly target_delta moneyness."""
        if df is None or df.empty or spot is None or "impliedVolatility" not in df.columns:
            return None
        # Approximation: 25-delta call ~ ~7% OTM, 25-delta put ~ ~7% OTM.
        target_strike = spot * (1.0 + (0.07 if target_delta > 0 else -0.07))
        idx = (df["strike"] - target_strike).abs().idxmin()
        try:
            return float(df.loc[idx, "impliedVolatility"])
        except Exception:
            return None

    atm_iv_call = _atm_iv(calls)
    atm_iv_put = _atm_iv(puts)
    iv_25d_put = _delta_proxy_iv(puts, -0.25)
    iv_25d_call = _delta_proxy_iv(calls, 0.25)

    skew_25d = None
    if iv_25d_put is not None and iv_25d_call is not None:
        skew_25d = round(iv_25d_put - iv_25d_call, 6)

    call_vol = int(calls["volume"].fillna(0).sum()) if "volume" in calls.columns else 0
    put_vol = int(puts["volume"].fillna(0).sum()) if "volume" in puts.columns else 0
    pcr = round(put_vol / call_vol, 4) if call_vol > 0 else None

    result = {
        "ticker": ticker.upper(),
        "nearest_expiry": nearest,
        "spot": round(spot, 6) if spot else None,
        "put_call_ratio": pcr,
        "atm_iv_call": round(atm_iv_call, 6) if atm_iv_call else None,
        "atm_iv_put": round(atm_iv_put, 6) if atm_iv_put else None,
        "skew_25d": skew_25d,
        "total_call_volume": call_vol,
        "total_put_volume": put_vol,
        "n_expiries": len(expiries),
    }
    _set_cache("options_chain", {"t": ticker.upper()}, result)
    return result


@mcp.tool()
def short_interest(ticker: str) -> dict:
    """Short-interest snapshot via yfinance .info.

    Returns short percent of float, short ratio (days-to-cover), and the
    month-over-month change in shares short. Fields may be None when
    yfinance does not surface them for the given ticker.
    """
    log.info("short_interest %s", ticker)
    try:
        info_data = yf.Ticker(ticker).info or {}
    except Exception as exc:
        return {"error": f"yfinance info failed: {exc}"}

    short_pct_float = info_data.get("shortPercentOfFloat")
    short_ratio = info_data.get("shortRatio")
    shares_short = info_data.get("sharesShort")
    shares_short_prior = info_data.get("sharesShortPriorMonth")
    days_to_cover = short_ratio  # yfinance uses shortRatio == days-to-cover

    change_pct = None
    if shares_short and shares_short_prior:
        try:
            change_pct = round(
                (float(shares_short) - float(shares_short_prior))
                / float(shares_short_prior) * 100, 4
            )
        except (TypeError, ZeroDivisionError):
            change_pct = None

    return {
        "ticker": ticker.upper(),
        "short_percent_of_float": short_pct_float,
        "short_ratio": short_ratio,
        "days_to_cover": days_to_cover,
        "shares_short": shares_short,
        "shares_short_prior_month": shares_short_prior,
        "change_pct": change_pct,
    }


_SEC_USER_AGENT = "claude-tradingagents contact@example.com"
_SEC_CACHE_TTL = 6 * 3600  # 6h


def _sec_cik_for_ticker(ticker: str) -> Optional[str]:
    """Resolve ticker -> zero-padded 10-digit CIK using SEC ticker map."""
    cached = _get_cache("sec_tickers", {"_": "all"}, ttl=24 * 3600)
    if cached is None:
        try:
            r = httpx.get("https://www.sec.gov/files/company_tickers.json",
                          headers={"User-Agent": _SEC_USER_AGENT}, timeout=30.0)
            r.raise_for_status()
            cached = r.json()
            _set_cache("sec_tickers", {"_": "all"}, cached)
        except Exception as exc:
            log.warning("sec ticker map fetch failed: %s", exc)
            return None

    upper = ticker.upper()
    for _, row in (cached or {}).items():
        if isinstance(row, dict) and str(row.get("ticker", "")).upper() == upper:
            return str(row.get("cik_str", "")).zfill(10)
    return None


@mcp.tool()
def sec_filings(ticker: str, form_type: str = "10-K", limit: int = 5) -> dict:
    """Recent SEC EDGAR filings for a ticker.

    Hits https://data.sec.gov/submissions/CIK{cik}.json (User-Agent header
    required by SEC). Filter to a specific `form_type` (e.g. '10-K', '10-Q',
    '8-K', '4'). Use form_type='ALL' to return every recent filing.
    Cached for 6h since EDGAR doesn't push real-time.
    """
    log.info("sec_filings %s form=%s limit=%d", ticker, form_type, limit)
    payload = {"t": ticker.upper(), "form": form_type.upper(), "limit": int(limit)}
    cached = _get_cache("sec_filings", payload, ttl=_SEC_CACHE_TTL)
    if cached is not None:
        return cached

    cik = _sec_cik_for_ticker(ticker)
    if not cik:
        return {"error": f"could not resolve CIK for {ticker}"}

    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        r = httpx.get(url, headers={"User-Agent": _SEC_USER_AGENT}, timeout=30.0)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        return {"error": f"sec submissions fetch failed: {exc}"}

    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    primary_docs = recent.get("primaryDocument") or []

    target = form_type.upper()
    filings_out: list[dict] = []
    for i in range(len(forms)):
        if target != "ALL" and forms[i].upper() != target:
            continue
        acc_clean = accessions[i].replace("-", "") if i < len(accessions) else ""
        primary = primary_docs[i] if i < len(primary_docs) else ""
        url_doc = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{primary}"
            if acc_clean and primary else None
        )
        filings_out.append({
            "form": forms[i],
            "filing_date": dates[i] if i < len(dates) else None,
            "accession_no": accessions[i] if i < len(accessions) else None,
            "primary_document_url": url_doc,
        })
        if len(filings_out) >= limit:
            break

    result = {
        "ticker": ticker.upper(),
        "cik": cik,
        "form_type": target,
        "filings": filings_out,
        "n_returned": len(filings_out),
    }
    _set_cache("sec_filings", payload, result)
    return result


# ---------------------------------------------------------------------------
# Trader-side helper: aggregate every JSON Signal Footer in state/ as TOON
# ---------------------------------------------------------------------------

import re as _re


_SIGNAL_FENCE = _re.compile(r"```json\s*(\{[\s\S]*?\})\s*```", _re.MULTILINE)


def _extract_last_signal(md_text: str) -> Optional[dict]:
    """Return the last fenced ```json {...} block in `md_text`, parsed."""
    matches = _SIGNAL_FENCE.findall(md_text)
    if not matches:
        return None
    for raw in reversed(matches):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            continue
    return None


@mcp.tool()
def aggregate_signals(ticker: str) -> str:
    """Aggregate every JSON Signal Footer found in `state/{ticker}_*.md`.

    Scans the state directory for analyst, persona, bull, and bear reports
    for the given ticker, extracts the last fenced ```json``` block from
    each, and returns a TOON-encoded table — one row per agent/persona —
    with columns: source, role, signal, confidence, horizon, fair_value,
    thesis_break_level. The trader reads this single TOON payload instead
    of opening 19 individual files, cutting tokens ~40% on the aggregation
    step. Files without a parseable footer are listed under `missing`.
    """
    state = _state_dir()
    log.info("aggregate_signals %s in %s", ticker, state)
    prefix_lower = f"{ticker.lower()}_"
    rows: list[dict] = []
    missing: list[str] = []

    seen: set[Path] = set()
    candidates = list(state.glob(f"{ticker}_*.md")) + list(state.glob(f"{ticker.lower()}_*.md"))
    for md in sorted({p.resolve() for p in candidates}):
        if not md.name.lower().startswith(prefix_lower):
            continue
        if md in seen:
            continue
        seen.add(md)
        # Skip trader's own plan + risk decision (no signal footer there) + debate transcript
        stem_lower = md.stem.lower()
        if any(stem_lower.endswith(skip) for skip in ("_trader_plan", "_decision", "_debate", "_watch")):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except Exception as exc:
            missing.append(f"{md.name} (read error: {exc})")
            continue
        sig = _extract_last_signal(text)
        if sig is None:
            missing.append(md.name)
            continue
        # Derive source + role from filename: TICKER_<role>.md or TICKER_persona_<name>.md
        suffix = md.stem[len(ticker) + 1:]  # strip "TICKER_"
        if suffix.startswith("persona_"):
            role = "persona"
            source = suffix[len("persona_"):]
        else:
            role = suffix.split("_")[0]  # "fundamentals", "technical", "bull", etc.
            source = suffix
        rows.append({
            "source": source,
            "role": role,
            "signal": sig.get("signal"),
            "confidence": sig.get("confidence"),
            "horizon": sig.get("horizon"),
            "fair_value": sig.get("fair_value"),
            "thesis_break_level": sig.get("thesis_break_level"),
            "key_points": "; ".join(sig.get("key_points") or [])[:200],
            "key_risks": "; ".join(sig.get("key_risks") or [])[:200],
        })

    payload = {
        "ticker": ticker.upper(),
        "n_signals": len(rows),
        "signals": rows,
        "missing": missing,
    }
    return _maybe_toon(payload)


# ============================================================
# v2.1 NEW TOOLS — Macro / Smart-Money / Forward / Sentiment / Quant
# ============================================================


# ---- Macro Layer ----

@mcp.tool()
def fred(series_id: str, lookback_days: int = 365) -> str:
    """FRED time series (St. Louis Fed). Requires FRED_API_KEY env var.

    Returns TOON-encoded list of {date, value} observations.
    """
    cache_payload = {"series": series_id, "lookback": lookback_days}
    cached = _get_cache("fred", cache_payload, ttl=CACHE_TTL)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    raw = _fred_get("series/observations", {
        "series_id": series_id,
        "observation_start": start,
    })
    if raw is None:
        return json.dumps({"error": "FRED_API_KEY not set"})
    if isinstance(raw, dict) and raw.get("error"):
        return json.dumps(raw)

    rows: list[dict] = []
    for obs in raw.get("observations", []):
        v = obs.get("value")
        if v is None or v == "." or v == "":
            continue
        try:
            rows.append({"date": obs.get("date"), "value": float(v)})
        except (TypeError, ValueError):
            continue
    payload = _maybe_toon(rows)
    _set_cache("fred", cache_payload, {"payload": payload})
    return payload


@mcp.tool()
def vix_term_structure() -> str:
    """VIX term structure snapshot (^VIX, ^VIX9D, ^VIX3M, ^VVIX) via yfinance.

    Returns JSON with last close levels plus contango/backwardation flag and
    a coarse regime label (calm <15, normal 15-30, stress >30).
    """
    cached = _get_cache("vix_term", {"_": "snap"}, ttl=CACHE_TTL)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    symbols = {"vix": "^VIX", "vix9d": "^VIX9D", "vix3m": "^VIX3M", "vvix": "^VVIX"}
    out: dict[str, float | str | None] = {}
    try:
        for key, sym in symbols.items():
            tk = yf.Ticker(sym)
            hist = tk.history(period="5d")
            if hist is None or hist.empty:
                out[key] = None
                continue
            out[key] = float(hist["Close"].iloc[-1])
    except Exception as exc:
        return json.dumps({"error": f"vix_term_structure yfinance failure: {exc}"})

    vix = out.get("vix")
    vix9d = out.get("vix9d")
    vix3m = out.get("vix3m")

    term_structure = "contango"
    if isinstance(vix3m, float):
        if isinstance(vix9d, float) and vix9d > vix3m:
            term_structure = "backwardation"
        elif isinstance(vix, float) and vix > vix3m:
            term_structure = "backwardation"

    regime = "normal"
    if isinstance(vix, float):
        if vix < 15:
            regime = "calm"
        elif vix > 30:
            regime = "stress"

    out["term_structure"] = term_structure
    out["regime"] = regime
    payload = json.dumps(out)
    _set_cache("vix_term", {"_": "snap"}, {"payload": payload})
    return payload


@mcp.tool()
def cboe_skew() -> str:
    """CBOE SKEW Index snapshot via yfinance ^SKEW.

    Returns JSON with skew level + tail_risk bucket
    (low <115, normal 115-150, elevated >150).
    """
    cached = _get_cache("cboe_skew", {"_": "snap"}, ttl=CACHE_TTL)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    try:
        tk = yf.Ticker("^SKEW")
        hist = tk.history(period="5d")
        if hist is None or hist.empty:
            return json.dumps({"error": "no SKEW data"})
        skew = float(hist["Close"].iloc[-1])
    except Exception as exc:
        return json.dumps({"error": f"cboe_skew failure: {exc}"})

    if skew < 115:
        bucket = "low"
    elif skew > 150:
        bucket = "elevated"
    else:
        bucket = "normal"
    payload = json.dumps({"skew": skew, "tail_risk": bucket})
    _set_cache("cboe_skew", {"_": "snap"}, {"payload": payload})
    return payload


# ---- Smart-Money Layer ----

@mcp.tool()
def congress_trades(ticker: str, days: int = 180) -> str:
    """US Senator + House stock trades from public watcher datasets.

    Returns TOON list of {date, politician, chamber, ticker, type, amount}.
    Trailing-indicator: filings have 30-45 day disclosure lag.
    """
    cache_payload = {"t": ticker.upper(), "d": days}
    cached = _get_cache("congress_trades", cache_payload, ttl=CACHE_TTL)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    sources = [
        ("Senate", "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json"),
        ("House", "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"),
    ]
    rows: list[dict] = []
    seen: set[tuple] = set()
    target = ticker.upper()
    for chamber, url in sources:
        try:
            r = httpx.get(url, timeout=60.0)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            log.warning("congress_trades %s fetch failed: %s", chamber, exc)
            continue
        if not isinstance(data, list):
            continue
        for t in data:
            try:
                tk = (t.get("ticker") or "").upper()
                if tk != target:
                    continue
                date_str = t.get("transaction_date") or t.get("disclosure_date") or ""
                try:
                    tdate = datetime.strptime(date_str, "%Y-%m-%d").date()
                except Exception:
                    continue
                if tdate < cutoff:
                    continue
                politician = t.get("senator") or t.get("representative") or "unknown"
                ttype = t.get("type") or t.get("transaction_type") or ""
                amount = t.get("amount") or ""
                key = (politician, date_str, tk, ttype, amount)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "date": date_str,
                    "politician": politician,
                    "chamber": chamber,
                    "ticker": tk,
                    "type": ttype,
                    "amount": amount,
                })
            except Exception:
                continue

    rows.sort(key=lambda x: x.get("date", ""), reverse=True)
    payload = _maybe_toon(rows)
    _set_cache("congress_trades", cache_payload, {"payload": payload})
    return payload


@mcp.tool()
def options_flow(ticker: str) -> str:
    """Unusual options activity scrape from Barchart for a ticker.

    Returns TOON list of contracts with strike/type/expiry/volume/oi/ratio/premium.
    Requires beautifulsoup4.
    """
    if _BS is None:
        return json.dumps({"error": "feature 'options_flow' requires 'pip install beautifulsoup4'"})

    cache_payload = {"t": ticker.upper()}
    cached = _get_cache("options_flow", cache_payload, ttl=CACHE_TTL)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    url = f"https://www.barchart.com/stocks/quotes/{ticker.upper()}/unusual-options-activity"
    try:
        r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0, follow_redirects=True)
        r.raise_for_status()
    except Exception as exc:
        return json.dumps({"error": f"barchart fetch failed for {ticker}: {exc}"})

    try:
        soup = _BS(r.text, "html.parser")
        table = soup.find("table")
        rows: list[dict] = []
        if table is None:
            payload = _maybe_toon(rows)
            _set_cache("options_flow", cache_payload, {"payload": payload})
            return payload
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if not cells:
                continue
            row = dict(zip(headers, cells))
            rows.append({
                "strike": row.get("strike", ""),
                "type": row.get("type", ""),
                "expiry": row.get("exp date") or row.get("expiry") or row.get("expiration", ""),
                "volume": row.get("volume", ""),
                "oi": row.get("open int") or row.get("oi", ""),
                "vol_oi_ratio": row.get("vol/oi") or row.get("ratio", ""),
                "premium": row.get("premium", ""),
            })
    except Exception as exc:
        return json.dumps({"error": f"barchart parse failed for {ticker}: {exc}"})

    payload = _maybe_toon(rows)
    _set_cache("options_flow", cache_payload, {"payload": payload})
    return payload


@mcp.tool()
def etf_holdings(ticker: str) -> str:
    """ETFs that hold the given ticker, scraped from etfdb.com.

    Returns TOON list of {etf_symbol, etf_name, allocation_pct}.
    Requires beautifulsoup4.
    """
    if _BS is None:
        return json.dumps({"error": "feature 'etf_holdings' requires 'pip install beautifulsoup4'"})

    cache_payload = {"t": ticker.upper()}
    cached = _get_cache("etf_holdings", cache_payload, ttl=6 * 3600)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    url = f"https://etfdb.com/stock/{ticker.upper()}/"
    try:
        r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0, follow_redirects=True)
        r.raise_for_status()
    except Exception as exc:
        log.warning("etf_holdings fetch failed: %s", exc)
        payload = _maybe_toon([])
        _set_cache("etf_holdings", cache_payload, {"payload": payload})
        return payload

    rows: list[dict] = []
    try:
        soup = _BS(r.text, "html.parser")
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if not any("ticker" in h or "symbol" in h for h in headers):
                continue
            for tr in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if len(cells) < 2:
                    continue
                row = dict(zip(headers, cells))
                sym = row.get("ticker") or row.get("symbol") or cells[0]
                name = row.get("etf") or row.get("name") or row.get("etfdb.com category") or ""
                alloc = row.get("allocation") or row.get("weighting") or row.get("% allocation") or ""
                rows.append({
                    "etf_symbol": sym,
                    "etf_name": name,
                    "allocation_pct": alloc,
                })
            if rows:
                break
    except Exception as exc:
        log.warning("etf_holdings parse failed: %s", exc)
        rows = []

    payload = _maybe_toon(rows)
    _set_cache("etf_holdings", cache_payload, {"payload": payload})
    return payload


_FAMOUS_INVESTORS = {
    "Berkshire Hathaway (Buffett)": "0001067983",
    "Scion Asset Management (Burry)": "0001649339",
    "Pershing Square (Ackman)": "0001336528",
    "ARK Investment (Wood)": "0001697748",
    "Bridgewater (Dalio)": "0001350694",
    "Renaissance (Simons)": "0001037389",
}


@mcp.tool()
def institutional_holdings(ticker: str) -> str:
    """Famous-investor 13F-HR exposure to a ticker via SEC EDGAR.

    For each hardcoded famous investor, fetches the latest 13F-HR filing
    metadata and best-effort checks whether the ticker text appears in the
    filing's information table. Trailing-indicator: 13F filings lag ~45 days.
    Returns TOON list of {investor, cik, latest_13f_date, holds_ticker}.
    """
    cache_payload = {"t": ticker.upper()}
    cached = _get_cache("institutional_holdings", cache_payload, ttl=6 * 3600)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    target = ticker.upper()
    results: list[dict] = []
    for name, cik in _FAMOUS_INVESTORS.items():
        cik_padded = cik.zfill(10)
        latest_date: str = "unknown"
        accession_clean: str | None = None
        try:
            r = httpx.get(
                f"https://data.sec.gov/submissions/CIK{cik_padded}.json",
                headers=_SEC_HEADERS, timeout=20.0,
            )
            r.raise_for_status()
            sub = r.json()
            recent = sub.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            for i, form in enumerate(forms):
                if form == "13F-HR":
                    accession = recent.get("accessionNumber", [""])[i]
                    accession_clean = accession.replace("-", "")
                    latest_date = recent.get("filingDate", [""])[i]
                    break
        except Exception as exc:
            log.warning("institutional_holdings %s submissions fetch failed: %s", name, exc)
            results.append({
                "investor": name,
                "cik": cik,
                "latest_13f_date": "unknown",
                "holds_ticker": "unknown",
            })
            continue

        holds: bool | str = "unknown"
        if accession_clean:
            try:
                idx_url = (
                    f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                    f"&CIK={cik_padded}&type=13F-HR&dateb=&owner=include&count=10"
                )
                # Pull the raw 13F text via the archives index (best-effort)
                txt_url = (
                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                    f"{accession_clean}/{accession_clean[:10]}-{accession_clean[10:12]}-{accession_clean[12:]}-index.htm"
                )
                r2 = httpx.get(txt_url, headers=_SEC_HEADERS, timeout=20.0)
                if r2.status_code == 200 and target in r2.text.upper():
                    holds = True
                else:
                    # Fallback: fetch the bare archive folder listing
                    folder_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/"
                    r3 = httpx.get(folder_url, headers=_SEC_HEADERS, timeout=20.0)
                    if r3.status_code == 200 and target in r3.text.upper():
                        holds = True
                    else:
                        holds = False
                _ = idx_url  # kept for debug clarity
            except Exception as exc:
                log.warning("institutional_holdings %s 13F probe failed: %s", name, exc)
                holds = "unknown"

        results.append({
            "investor": name,
            "cik": cik,
            "latest_13f_date": latest_date,
            "holds_ticker": holds,
        })

    payload = _maybe_toon(results)
    _set_cache("institutional_holdings", cache_payload, {"payload": payload})
    return payload


# ---- Forward-Looking Layer ----

@mcp.tool()
def earnings_transcript(ticker: str, quarter: int, year: int) -> str:
    """Earnings call transcript via FMP. Requires FMP_API_KEY.

    Returns JSON {ticker, quarter, year, date, content}. Content can be large.
    """
    cache_payload = {"t": ticker.upper(), "q": quarter, "y": year}
    cached = _get_cache("earnings_transcript", cache_payload, ttl=24 * 3600)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    raw = _fmp_get(f"earning_call_transcript/{ticker.upper()}",
                   {"quarter": quarter, "year": year})
    if raw is None:
        return json.dumps({"error": "FMP_API_KEY not set"})
    if isinstance(raw, dict) and raw.get("error"):
        return json.dumps(raw)

    entry: dict = {}
    if isinstance(raw, list) and raw:
        entry = raw[0]
    elif isinstance(raw, dict):
        entry = raw

    payload = json.dumps({
        "ticker": ticker.upper(),
        "quarter": quarter,
        "year": year,
        "date": entry.get("date", ""),
        "content": entry.get("content", ""),
    })
    _set_cache("earnings_transcript", cache_payload, {"payload": payload})
    return payload


@mcp.tool()
def finnhub_recommendations(ticker: str) -> str:
    """Finnhub analyst recommendation trends for a ticker.

    Returns TOON list of {period, buy, hold, sell, strongBuy, strongSell}.
    Requires FINNHUB_API_KEY.
    """
    cache_payload = {"t": ticker.upper()}
    cached = _get_cache("finnhub_recs", cache_payload, ttl=CACHE_TTL)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    raw = _finnhub_get("stock/recommendation", {"symbol": ticker.upper()})
    if raw is None:
        return json.dumps({"error": "FINNHUB_API_KEY not set"})
    if isinstance(raw, dict) and raw.get("error"):
        return json.dumps(raw)

    rows: list[dict] = []
    if isinstance(raw, list):
        for item in raw:
            rows.append({
                "period": item.get("period", ""),
                "buy": item.get("buy", 0),
                "hold": item.get("hold", 0),
                "sell": item.get("sell", 0),
                "strongBuy": item.get("strongBuy", 0),
                "strongSell": item.get("strongSell", 0),
            })
    payload = _maybe_toon(rows)
    _set_cache("finnhub_recs", cache_payload, {"payload": payload})
    return payload


@mcp.tool()
def finnhub_calendar(from_date: str | None = None, to_date: str | None = None) -> str:
    """Finnhub earnings calendar. Defaults to today..today+14d.

    Returns TOON list of earnings events. Requires FINNHUB_API_KEY.
    """
    if not from_date:
        from_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not to_date:
        to_date = (datetime.now(timezone.utc) + timedelta(days=14)).strftime("%Y-%m-%d")

    cache_payload = {"f": from_date, "t": to_date}
    cached = _get_cache("finnhub_cal", cache_payload, ttl=CACHE_TTL)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    raw = _finnhub_get("calendar/earnings", {"from": from_date, "to": to_date})
    if raw is None:
        return json.dumps({"error": "FINNHUB_API_KEY not set"})
    if isinstance(raw, dict) and raw.get("error"):
        return json.dumps(raw)

    events = []
    if isinstance(raw, dict):
        events = raw.get("earningsCalendar", []) or []
    elif isinstance(raw, list):
        events = raw
    payload = _maybe_toon(events)
    _set_cache("finnhub_cal", cache_payload, {"payload": payload})
    return payload


@mcp.tool()
def finnhub_ipo_calendar(from_date: str | None = None, to_date: str | None = None) -> str:
    """Finnhub IPO calendar. Defaults to today..today+30d.

    Returns TOON list of IPO events. Requires FINNHUB_API_KEY.
    """
    if not from_date:
        from_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not to_date:
        to_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    cache_payload = {"f": from_date, "t": to_date}
    cached = _get_cache("finnhub_ipo", cache_payload, ttl=CACHE_TTL)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    raw = _finnhub_get("calendar/ipo", {"from": from_date, "to": to_date})
    if raw is None:
        return json.dumps({"error": "FINNHUB_API_KEY not set"})
    if isinstance(raw, dict) and raw.get("error"):
        return json.dumps(raw)

    events = []
    if isinstance(raw, dict):
        events = raw.get("ipoCalendar", []) or []
    elif isinstance(raw, list):
        events = raw
    payload = _maybe_toon(events)
    _set_cache("finnhub_ipo", cache_payload, {"payload": payload})
    return payload


# ---- Sentiment Layer ----

@mcp.tool()
def reddit_mentions(ticker: str,
                    subreddits: str = "wallstreetbets,investing,stocks",
                    days: int = 7,
                    limit: int = 25) -> str:
    """Reddit posts mentioning a ticker via PRAW search.

    Returns TOON list of {subreddit, title, score, num_comments, created_utc, url}.
    Requires REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET env vars and 'pip install praw'.
    """
    reddit = _reddit_client()
    if reddit is None:
        return json.dumps({"error": "PRAW credentials missing or 'pip install praw' missing"})

    cache_payload = {"t": ticker.upper(), "s": subreddits, "d": days, "l": limit}
    cached = _get_cache("reddit_mentions", cache_payload, ttl=CACHE_TTL)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    if isinstance(subreddits, str):
        sub_list = [s.strip() for s in subreddits.split(",") if s.strip()]
    else:
        sub_list = [str(s).strip() for s in subreddits if str(s).strip()]

    cutoff = time.time() - days * 86400
    results: list[dict] = []
    try:
        for sub_name in sub_list:
            try:
                sub = reddit.subreddit(sub_name)
                for post in sub.search(ticker, sort="new", limit=limit, time_filter="week"):
                    if post.created_utc < cutoff:
                        continue
                    results.append({
                        "subreddit": sub_name,
                        "title": post.title,
                        "score": int(getattr(post, "score", 0) or 0),
                        "num_comments": int(getattr(post, "num_comments", 0) or 0),
                        "created_utc": int(post.created_utc),
                        "url": f"https://reddit.com{post.permalink}",
                    })
            except Exception as exc:
                log.warning("reddit_mentions subreddit %s failed: %s", sub_name, exc)
                continue
    except Exception as exc:
        return json.dumps({"error": f"reddit_mentions failure: {exc}"})

    payload = _maybe_toon(results)
    _set_cache("reddit_mentions", cache_payload, {"payload": payload})
    return payload


@mcp.tool()
def finbert_score(text: str) -> str:
    """Finance-tuned BERT (ProsusAI/finbert) sentiment classifier.

    Returns JSON dict with positive/neutral/negative scores. Truncates input
    to 512 chars (model max). Requires 'pip install transformers torch'.
    """
    pipe = _finbert_pipeline()
    if pipe is None:
        return json.dumps({"error": "feature 'finbert_score' requires 'pip install transformers torch'"})

    truncated = len(text) > 512
    try:
        scores = pipe(text[:512])
    except Exception as exc:
        return json.dumps({"error": f"finbert inference failed: {exc}"})

    result: dict = {}
    if scores:
        first = scores[0] if isinstance(scores[0], list) else scores
        if isinstance(first, list):
            for s in first:
                label = s.get("label") if isinstance(s, dict) else None
                score = s.get("score") if isinstance(s, dict) else None
                if label is not None and score is not None:
                    result[str(label).lower()] = float(score)
        elif isinstance(first, dict) and "label" in first:
            result[str(first["label"]).lower()] = float(first.get("score", 0.0))
    result["text_truncated"] = truncated
    return json.dumps(result)


# ---- Quant Layer ----

@mcp.tool()
def vectorbt_backtest(ticker: str,
                      signals: list,
                      start: str,
                      end: str,
                      initial_cash: float = 10000.0) -> str:
    """Vectorized backtest using vectorbt over a single ticker.

    `signals` is a list of {date: 'YYYY-MM-DD', action: 'buy'|'sell'}.
    Returns JSON with total_return, sharpe_ratio, max_drawdown, win_rate,
    n_trades, final_value. Requires 'pip install vectorbt'.
    """
    if vbt is None:
        return json.dumps({"error": "feature 'vectorbt_backtest' requires 'pip install vectorbt'"})
    if pd is None:
        return json.dumps({"error": "vectorbt_backtest requires pandas"})

    sig_hash = hashlib.sha1(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()[:12]
    cache_payload = {"t": ticker.upper(), "s": start, "e": end, "h": sig_hash, "c": initial_cash}
    cached = _get_cache("vectorbt_bt", cache_payload, ttl=6 * 3600)
    if cached is not None:
        return cached.get("payload", json.dumps({"error": "cache corrupt"}))

    try:
        hist = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
        if hist is None or hist.empty:
            return json.dumps({"error": f"no price data for {ticker} {start}..{end}"})
        close = hist["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]

        entries = pd.Series(False, index=close.index)
        exits = pd.Series(False, index=close.index)
        for sig in signals or []:
            try:
                d = pd.to_datetime(sig.get("date"))
            except Exception:
                continue
            if d in close.index:
                action = (sig.get("action") or "").lower()
                if action == "buy":
                    entries.loc[d] = True
                elif action == "sell":
                    exits.loc[d] = True

        pf = vbt.Portfolio.from_signals(close, entries, exits, init_cash=initial_cash)
        stats = pf.stats()

        def _g(*keys, default=None):
            for k in keys:
                if k in stats.index:
                    v = stats[k]
                    try:
                        return float(v)
                    except Exception:
                        return v
            return default

        total_return = _g("Total Return [%]", "Total Return", default=None)
        sharpe = _g("Sharpe Ratio", default=None)
        mdd = _g("Max Drawdown [%]", "Max Drawdown", default=None)
        win_rate = _g("Win Rate [%]", "Win Rate", default=None)
        n_trades = _g("Total Trades", "# Trades", default=None)
        final_value = float(pf.value().iloc[-1]) if hasattr(pf, "value") else None

        payload = json.dumps({
            "total_return": total_return,
            "sharpe_ratio": sharpe,
            "max_drawdown": mdd,
            "win_rate": win_rate,
            "n_trades": n_trades,
            "final_value": final_value,
        }, default=str)
        _set_cache("vectorbt_bt", cache_payload, {"payload": payload})
        return payload
    except Exception as exc:
        return json.dumps({"error": f"vectorbt_backtest failure: {exc}"})


@mcp.tool()
def risk_metrics(returns: list, risk_free_rate: float = 0.04) -> str:
    """Empyrical risk metrics for a daily return series.

    Returns JSON with calmar, omega, tail, stability, cvar_95, annual_return,
    annual_volatility. Requires 'pip install empyrical'.
    """
    if empyrical is None:
        return json.dumps({"error": "feature 'risk_metrics' requires 'pip install empyrical'"})
    if not _HAS_NUMPY:
        return json.dumps({"error": "risk_metrics requires numpy"})

    try:
        r = np.array([float(x) for x in returns], dtype=float)
        if r.size == 0:
            return json.dumps({"error": "empty returns"})
        out = {
            "calmar_ratio": float(empyrical.calmar_ratio(r)),
            "omega_ratio": float(empyrical.omega_ratio(r)),
            "tail_ratio": float(empyrical.tail_ratio(r)),
            "stability": float(empyrical.stability_of_timeseries(r)),
            "cvar_95": float(empyrical.conditional_value_at_risk(r, cutoff=0.05)),
            "annual_return": float(empyrical.annual_return(r)),
            "annual_volatility": float(empyrical.annual_volatility(r)),
        }
        return json.dumps(out, default=str)
    except Exception as exc:
        return json.dumps({"error": f"risk_metrics failure: {exc}"})


@mcp.tool()
def frac_diff(series: list, d: float = 0.5, threshold: float = 1e-4) -> str:
    """Fractional differentiation (memory-preserving stationarization).

    Falls back to a compact local implementation if mlfinlab is unavailable.
    Returns TOON list of {index, value}.
    """
    if not _HAS_NUMPY:
        return json.dumps({"error": "frac_diff requires numpy"})

    try:
        weights = [1.0]
        k = 1
        while True:
            w = -weights[-1] * (d - k + 1) / k
            if abs(w) < threshold:
                break
            weights.append(w)
            k += 1
            if k > 10000:
                break
        weights_arr = np.array(weights[::-1], dtype=float)
        series_arr = np.array([float(x) for x in series], dtype=float)
        L = len(weights_arr)
        out: list[dict] = []
        for i in range(L, len(series_arr)):
            val = float(np.dot(weights_arr, series_arr[i - L:i]))
            out.append({"index": i, "value": val})
        return _maybe_toon(out)
    except Exception as exc:
        return json.dumps({"error": f"frac_diff failure: {exc}"})


@mcp.tool()
def triple_barrier_labels(prices: list,
                          profit_take_pct: float = 0.05,
                          stop_loss_pct: float = 0.03,
                          max_holding_periods: int = 20) -> str:
    """Triple-Barrier labels (Lopez de Prado) for a price series.

    Each entry yields label 1 (PT hit), -1 (SL hit), or 0 (timeout).
    Returns TOON list of {index, entry_price, label}.
    """
    if not _HAS_NUMPY:
        return json.dumps({"error": "triple_barrier_labels requires numpy"})
    try:
        prices_arr = np.array([float(x) for x in prices], dtype=float)
        labels: list[dict] = []
        n = len(prices_arr)
        for i in range(max(0, n - max_holding_periods)):
            entry = float(prices_arr[i])
            pt = entry * (1 + profit_take_pct)
            sl = entry * (1 - stop_loss_pct)
            label = 0
            for j in range(1, max_holding_periods + 1):
                p = float(prices_arr[i + j])
                if p >= pt:
                    label = 1
                    break
                if p <= sl:
                    label = -1
                    break
            labels.append({"index": i, "entry_price": entry, "label": label})
        return _maybe_toon(labels)
    except Exception as exc:
        return json.dumps({"error": f"triple_barrier_labels failure: {exc}"})


if __name__ == "__main__":
    mcp.run()

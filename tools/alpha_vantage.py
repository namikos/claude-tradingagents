#!/usr/bin/env python3
"""Alpha Vantage CLI wrapper for TradingAgents.

Subcommands map 1:1 to the data tools the original LangGraph agents use.
Cached in state/cache/ with 1h TTL to stay under the free-tier 25 req/day limit.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

API_BASE = "https://www.alphavantage.co/query"
CACHE_DIR = Path(__file__).resolve().parent.parent / "state" / "cache"
CACHE_TTL_SECONDS = 3600


def _key() -> str:
    k = os.environ.get("ALPHA_VANTAGE_KEY")
    if not k:
        sys.exit("ERROR: ALPHA_VANTAGE_KEY env var not set")
    return k


def _cache_path(params: dict) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(urlencode(sorted(params.items())).encode()).hexdigest()[:16]
    return CACHE_DIR / f"{params.get('function', 'q')}_{h}.json"


def _request(params: dict) -> dict:
    params = {**params, "apikey": _key()}
    cache_file = _cache_path({k: v for k, v in params.items() if k != "apikey"})
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < CACHE_TTL_SECONDS:
        return json.loads(cache_file.read_text())
    r = requests.get(API_BASE, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "Note" in data or "Information" in data:
        sys.stderr.write(f"WARN: {data.get('Note') or data.get('Information')}\n")
    cache_file.write_text(json.dumps(data))
    return data


def cmd_quote(args):
    return _request({"function": "GLOBAL_QUOTE", "symbol": args.ticker})


def cmd_fundamentals(args):
    return _request({"function": "OVERVIEW", "symbol": args.ticker})


def cmd_balance_sheet(args):
    return _request({"function": "BALANCE_SHEET", "symbol": args.ticker})


def cmd_cashflow(args):
    return _request({"function": "CASH_FLOW", "symbol": args.ticker})


def cmd_income(args):
    return _request({"function": "INCOME_STATEMENT", "symbol": args.ticker})


def cmd_news(args):
    params = {"function": "NEWS_SENTIMENT", "tickers": args.ticker, "limit": str(args.limit)}
    if args.days:
        from datetime import datetime, timedelta, timezone
        time_from = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y%m%dT%H%M")
        params["time_from"] = time_from
    return _request(params)


def cmd_global_news(args):
    params = {"function": "NEWS_SENTIMENT", "limit": str(args.limit)}
    if args.topics:
        params["topics"] = args.topics
    return _request(params)


def cmd_technical(args):
    fn = args.indicator.upper()
    params = {
        "function": fn,
        "symbol": args.ticker,
        "interval": args.interval,
        "series_type": args.series_type,
    }
    if fn == "MACD":
        params.update({"fastperiod": "12", "slowperiod": "26", "signalperiod": "9"})
    elif fn in {"RSI", "SMA", "EMA"}:
        params["time_period"] = str(args.period)
    return _request(params)


def cmd_insider(args):
    return _request({"function": "INSIDER_TRANSACTIONS", "symbol": args.ticker})


def main():
    p = argparse.ArgumentParser(prog="alpha_vantage")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, fn in [("quote", cmd_quote), ("fundamentals", cmd_fundamentals),
                     ("balance-sheet", cmd_balance_sheet), ("cashflow", cmd_cashflow),
                     ("income", cmd_income), ("insider", cmd_insider)]:
        s = sub.add_parser(name)
        s.add_argument("ticker")
        s.set_defaults(func=fn)

    s = sub.add_parser("news")
    s.add_argument("ticker")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_news)

    s = sub.add_parser("global-news")
    s.add_argument("--topics", help="e.g. economy_macro,technology")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_global_news)

    s = sub.add_parser("technical")
    s.add_argument("ticker")
    s.add_argument("--indicator", default="MACD", choices=["MACD", "RSI", "SMA", "EMA"])
    s.add_argument("--interval", default="daily")
    s.add_argument("--series-type", default="close")
    s.add_argument("--period", type=int, default=14)
    s.set_defaults(func=cmd_technical)

    args = p.parse_args()
    out = args.func(args)
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

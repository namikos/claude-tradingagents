#!/usr/bin/env python3
"""yfinance CLI wrapper — no API key, unlimited requests.

Used as fallback / supplement to Alpha Vantage for historical OHLC data,
company info, and recent news.
"""
import argparse
import json
import sys

import yfinance as yf


def cmd_history(args):
    t = yf.Ticker(args.ticker)
    df = t.history(period=args.period, interval=args.interval)
    if args.format == "csv":
        df.to_csv(sys.stdout)
    else:
        df.reset_index(inplace=True)
        df["Date"] = df["Date"].astype(str) if "Date" in df.columns else df.iloc[:, 0].astype(str)
        json.dump(df.to_dict(orient="records"), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")


def cmd_info(args):
    t = yf.Ticker(args.ticker)
    info = t.info
    json.dump(info, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def cmd_news(args):
    t = yf.Ticker(args.ticker)
    news = t.news[: args.limit] if t.news else []
    json.dump(news, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def main():
    p = argparse.ArgumentParser(prog="yfin")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("history")
    s.add_argument("ticker")
    s.add_argument("--period", default="6mo",
                   help="1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max")
    s.add_argument("--interval", default="1d",
                   help="1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo")
    s.add_argument("--format", default="json", choices=["json", "csv"])
    s.set_defaults(func=cmd_history)

    s = sub.add_parser("info")
    s.add_argument("ticker")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("news")
    s.add_argument("ticker")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_news)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

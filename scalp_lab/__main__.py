from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import pandas as pd
from .feeds import fetch_bars, fetch_news, save_csv
from .news import score_news
from .features import make_features
from .targets import label_outcomes
from .evaluation import backtest
from .stream import monitor


def run():
    parser=argparse.ArgumentParser(description="Educational, data-driven stock research, NO ORDERS")
    sub=parser.add_subparsers(dest="action",required=True)
    get=sub.add_parser("fetch",help="Read historical Alpaca data (requires API keys)")
    get.add_argument("--ticker",required=True);get.add_argument("--start",required=True);get.add_argument("--end",required=True);get.add_argument("--feed",choices=["iex","sip"],default="iex");get.add_argument("--dir",default="data")
    back=sub.add_parser("backtest",help="Train only on old data; validate; test untouched data")
    back.add_argument("--symbol", help="Asset ticker matching the input bars (required for live monitoring)")
    back.add_argument("--bars",required=True);back.add_argument("--news");back.add_argument("--out",default="results");back.add_argument("--horizon",type=int,default=5);back.add_argument("--take-profit-bps",type=float,default=18);back.add_argument("--stop-bps",type=float,default=12);back.add_argument("--roundtrip-cost-bps",type=float,default=6);back.add_argument("--finbert",action="store_true");back.add_argument("--news-delay-seconds",type=int,default=60)
    demo=sub.add_parser("demo",help="Generate 60 artificial trading days; test plumbing, not predictive accuracy")
    demo.add_argument("--dir",default="demo_data")
    live=sub.add_parser("monitor",help="Read-only real-time market + news; optional paper indications")
    live.add_argument("--ticker",required=True);live.add_argument("--models",default="results");live.add_argument("--out",default="live");live.add_argument("--feed",choices=["iex","sip"],default="iex")
    a=parser.parse_args()
    if a.action=="fetch":
        dst=Path(a.dir);dst.mkdir(exist_ok=True,parents=True)
        bars=fetch_bars(a.ticker,a.start,a.end,feed=a.feed)
        save_csv(bars,dst/f"{a.ticker.upper()}_bars.csv")
        news=fetch_news(a.ticker,a.start,a.end)
        save_csv(news,dst/f"{a.ticker.upper()}_news.csv")
        return
    if a.action=="demo":
        from .synthetic import generate_demo
        bars,news=generate_demo()
        dst=Path(a.dir);dst.mkdir(exist_ok=True,parents=True)
        save_csv(bars,dst/"DEMO_bars.csv")
        save_csv(news,dst/"DEMO_news.csv")
        print("Artificial random-walk data created. DO NOT use these results to assess stock prediction accuracy.")
        return
    if a.action=="backtest":
        bars=pd.read_csv(a.bars)
        ns=pd.read_csv(a.news) if a.news else None
        scored=score_news(ns, use_finbert=a.finbert, assumed_latency_s=a.news_delay_seconds) if ns is not None else None
        data=make_features(bars,scored)
        labels=label_outcomes(data,horizon=a.horizon,tp_bps=a.take_profit_bps,sl_bps=a.stop_bps,cost_bps=a.roundtrip_cost_bps)
        result=backtest(labels,horizon=a.horizon,output=a.out)
        result["symbol"]=a.symbol.upper() if a.symbol else None
        result["settings"]={"tp_bps":a.take_profit_bps,"sl_bps":a.stop_bps,"roundtrip_cost_bps":a.roundtrip_cost_bps,"news_delay_seconds":a.news_delay_seconds,"news_model":"FinBERT" if a.finbert else "LEXICON (weak baseline)"}
        Path(a.out,"report.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
        print(json.dumps(result,indent=2))
        print(f"See {a.out}/report.json and {a.out}/test_paper_trades.csv")
        return
    if a.action=="monitor":
        try:
            asyncio.run(monitor(a.ticker,a.models,a.out,a.feed))
        except KeyboardInterrupt:
            print("Stopped paper monitor.")

if __name__ == "__main__":
    run()

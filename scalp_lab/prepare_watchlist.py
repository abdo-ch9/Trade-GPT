"""Prepare missing per-asset models using the existing chronological evaluation."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import uuid

from .auto_update import ROOT, atomic_json, read_json, symbols_for


def run():
    from .feeds import fetch_bars, fetch_news, save_csv
    from .features import make_features
    from .news import score_news
    from .targets import label_outcomes
    from .evaluation import backtest

    end = datetime.now(timezone.utc).date()
    start = end-timedelta(days=180)
    status_path=ROOT/"auto_live"/"training.json"
    statuses=read_json(status_path)
    for symbol in symbols_for(ROOT):
        dest=ROOT/f"results_{symbol}"
        if read_json(dest/"report.json").get("symbol")==symbol and (dest/"paper_models.joblib").exists():
            statuses[symbol]={"state":"Model already present"}
            atomic_json(status_path,statuses)
            continue
        try:
            statuses[symbol]={"state":"Fetching historical bars and news"}
            atomic_json(status_path,statuses)
            print(f"{symbol}: fetching {start} through {end}",flush=True)
            bars=fetch_bars(symbol,str(start),str(end),feed=os.getenv("ALPACA_DATA_FEED","iex"))
            news=fetch_news(symbol,str(start),str(end))
            save_csv(bars,ROOT/"data"/f"{symbol}_bars.csv")
            save_csv(news,ROOT/"data"/f"{symbol}_news.csv")
            statuses[symbol]={"state":"Training and evaluating chronological holdout"}
            atomic_json(status_path,statuses)
            frame=make_features(bars,score_news(news,assumed_latency_s=60))
            labels=label_outcomes(frame,horizon=5,tp_bps=18,sl_bps=12,cost_bps=6)
            staging=ROOT/"auto_live"/"training_runs"/f"{symbol}_{uuid.uuid4().hex}"
            result=backtest(labels,horizon=5,output=staging)
            result.update(symbol=symbol,settings={"tp_bps":18,"sl_bps":12,"roundtrip_cost_bps":6,"news_delay_seconds":60,"news_model":"LEXICON (weak baseline)"})
            atomic_json(staging/"report.json",result)
            dest.mkdir(exist_ok=True)
            for name in ("paper_models.joblib","test_paper_trades.csv","validation_paper_trades.csv","report.json"):
                os.replace(staging/name,dest/name)
            statuses[symbol]={"state":"Ready" if result["threshold"]<=1 else "Disabled by validation",
                              "threshold":result["threshold"],"validation":result["validation"],"test":result["test"]}
            atomic_json(status_path,statuses)
            print(f"{symbol}: {statuses[symbol]['state']}; validation trades={result['validation']['trades']}; test trades={result['test']['trades']}",flush=True)
        except Exception as exc:
            statuses[symbol]={"state":"Training failed","error":str(exc)}
            atomic_json(status_path,statuses)
            print(f"{symbol}: failed ({type(exc).__name__}): {exc}",flush=True)


if __name__=="__main__":
    run()

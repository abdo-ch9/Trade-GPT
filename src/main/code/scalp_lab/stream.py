"""Read-only websocket recorder and experimental realtime paper signal monitor.

Does NOT submit orders, connect brokerage trade account, or handle real money.
"""
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from websockets.asyncio.client import connect
from .feeds import fetch_bars, headers
from .features import make_features, FEATURE_COLUMNS
from .news import score_news
from .signals import paper_levels

DATA_WS="wss://stream.data.alpaca.markets"


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path, value):
    with open(path,"a",encoding="utf-8") as f:
        f.write(json.dumps(value,default=str)+"\n")


async def monitor(symbol, model_dir="results", output="live", feed="iex"):
    """Stream live, paper-only indications. Requires an Alpaca DATA credential."""
    headers() # Raises clearly if credentials absent
    symbol=symbol.upper()
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    artifact=joblib.load(Path(model_dir)/"paper_models.joblib")
    report_path=Path(model_dir)/"report.json"
    report=json.loads(report_path.read_text()) if report_path.exists() else {}
    if report.get("symbol") != symbol:
        raise ValueError("Train a report for this exact symbol before monitoring (backtest --symbol TICKER).")
    settings=report.get("settings", {})
    if artifact.get("features")!=FEATURE_COLUMNS:
        raise ValueError("Feature schema differs; retrain before monitoring")
    # Backfill only bars already available through chosen feed.
    end=datetime.now(timezone.utc)
    start=end-timedelta(days=10)
    try:
        warm=fetch_bars(symbol,start.isoformat(),end.isoformat(),feed=feed)
    except Exception as exc:
        print(f"Warmup unavailable ({exc}); live recording continues but paper signals need >=31 contiguous bars")
        warm=pd.DataFrame(columns=["timestamp","open","high","low","close","volume"])
    state={"bars":warm, "news":[], "quote":None, "latest_bar":None}
    state_lock=asyncio.Lock()
    paths={"bars":out/"bars.jsonl","news":out/"news.jsonl","quotes":out/"minute_quotes.jsonl","signals":out/"paper_signals.jsonl"}

    async def process_bar(event):
        d={"timestamp":event["t"],"open":event["o"],"high":event["h"],"low":event["l"],"close":event["c"],"volume":event["v"]}
        stamp=pd.Timestamp(d["timestamp"])
        # Websocket bar timestamp is bar START; wait until closed bar has actually arrived.
        if stamp + pd.Timedelta(minutes=1) > pd.Timestamp.now(tz="UTC"):
            return
        async with state_lock:
            if state["latest_bar"] is not None and stamp <= state["latest_bar"]:
                return
            state["latest_bar"] = stamp
            if state["quote"]:
                q=state["quote"]
                if q["ask"]>q["bid"]>0:
                    d["spread_bps"]=(q["ask"]-q["bid"])/((q["ask"]+q["bid"])/2)*1e4
                    if q["ask_size"]+q["bid_size"]>0:
                        d["quote_imbalance"]=(q["bid_size"]-q["ask_size"])/(q["bid_size"]+q["ask_size"])
                append_jsonl(paths["quotes"],dict(q, bar_timestamp=str(stamp)))
            append_jsonl(paths["bars"],dict(d,received_at=utcnow()))
            state["bars"] = pd.concat([state["bars"],pd.DataFrame([d])],ignore_index=True).drop_duplicates("timestamp",keep="last").tail(2500)
            bars=state["bars"].copy()
            ns=pd.DataFrame(state["news"])
        # Historical news that was NOT retrieved during warmup is absent; account for this limitation.
        scored=score_news(ns,assumed_latency_s=0) if len(ns) else None
        feat=make_features(bars, scored)
        if feat.empty:
            return
        newest=feat.iloc[-1]
        # Avoid inventing indicators from missing bar intervals.
        if pd.isna(newest["vol_30"]) or any(pd.isna(newest[c]) for c in FEATURE_COLUMNS):
            print(f"{utcnow()} {symbol} warming up/insufficient contiguous bars")
            return
        latest_x=feat.iloc[[-1]][FEATURE_COLUMNS].copy()
        for column, enabled in artifact.get("feature_enabled", {}).items():
            if not enabled: latest_x.loc[:,column]=0.0
        p={side:float(artifact["models"][side].predict_proba(latest_x)[0,1]) for side in ("long","short")}
        threshold=float(artifact["threshold"])
        side=max(p,key=p.get)
        # If the previous bar is stale by 90+ seconds, no signal is issued.
        age=pd.Timestamp.now(tz="UTC")-pd.Timestamp(newest["decision_time"])
        fresh=pd.Timedelta(0)<=age<pd.Timedelta(seconds=90)
        signal = side.upper() if fresh and p[side]>=threshold and threshold<=1 else "NO_SIGNAL"
        item={"created_at":utcnow(),"symbol":symbol,"decision_time":str(newest["decision_time"]),"signal":"PAPER_"+signal if signal!="NO_SIGNAL" else signal,"long_probability_uncalibrated":round(p["long"],4),"short_probability_uncalibrated":round(p["short"],4),"threshold":threshold,"feed":feed,"news_count_15m":int(newest["news_count_15m"]),"warning":"Research only; stream not verified in this sandbox; probability not calibrated; no orders."}
        item["reference_price"]=float(newest["close"])
        item["horizon_minutes"]=report.get("horizon_minutes")
        item["settings"]=settings
        item["levels"]=paper_levels(item["reference_price"], item["signal"], settings["tp_bps"], settings["sl_bps"])
        append_jsonl(paths["signals"],item)
        print(json.dumps(item))

    async def listen(kind, url, subscription):
        delay=1
        while True:
            try:
                async with connect(url,ping_interval=15,ping_timeout=15,max_size=8_000_000) as ws:
                    greeting=json.loads(await ws.recv())
                    if any(x.get("T")=="error" for x in greeting):
                        raise RuntimeError(f"{kind} connection error: {greeting}")
                    await ws.send(json.dumps({"action":"auth","key":os.environ["ALPACA_API_KEY"],"secret":os.environ["ALPACA_API_SECRET"]}))
                    auth=json.loads(await ws.recv())
                    if not any(x.get("msg")=="authenticated" for x in auth):
                        raise RuntimeError(f"{kind} authorization failed: {auth}")
                    await ws.send(json.dumps(subscription))
                    delay=1
                    async for msg in ws:
                        for e in json.loads(msg):
                            if e.get("T")=="error":
                                print(kind,"stream error",e)
                            elif kind=="market" and e.get("T")=="q":
                                async with state_lock:
                                    state["quote"]={"timestamp":e["t"],"bid":e.get("bp",0),"ask":e.get("ap",0),"bid_size":e.get("bs",0),"ask_size":e.get("as",0)}
                            elif kind=="market" and e.get("T")=="b":
                                await process_bar(e)
                            elif kind=="news" and e.get("T")=="n":
                                item={"id":e.get("id"),"headline":e.get("headline",""),"created_at":e.get("created_at"),"received_at":utcnow()}
                                append_jsonl(paths["news"],item)
                                async with state_lock:
                                    state["news"].append(item)
                                    state["news"]=state["news"][-300:]
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"{kind} disconnected ({exc}); retrying shortly")
                await asyncio.sleep(delay)
                delay=min(delay*2,30)

    print("READ-ONLY paper monitor. Connects to Alpaca market/news streams; Ctrl+C stops. No live brokerage order functionality.")
    await asyncio.gather(
        listen("market", f"{DATA_WS}/v2/{feed}", {"action":"subscribe","bars":[symbol],"quotes":[symbol]}),
        listen("news", f"{DATA_WS}/v1beta1/news", {"action":"subscribe","news":[symbol]})
    )

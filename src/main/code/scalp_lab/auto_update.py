"""Shared read-only watchlist updater, independent of browser sessions."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_SYMBOLS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA")
from .paths import LIB_DIR, PROJECT_ROOT, ENV_FILE
ROOT = LIB_DIR


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, default=str), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def add_symbol(root, symbol):
    if symbol == "DEMO":
        return
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", symbol):
        raise ValueError("Invalid ticker")
    # One file per custom symbol avoids lost edits from concurrent browser tabs.
    path = Path(root)/"auto_live"/"watchlist"/f"{symbol}.json"
    if not path.exists():
        atomic_json(path, {"symbol": symbol})


def symbols_for(root):
    symbols = set(DEFAULT_SYMBOLS)
    for path in (Path(root)/"auto_live"/"watchlist").glob("*.json"):
        symbol = path.stem
        if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", symbol) and symbol != "DEMO":
            symbols.add(symbol)
    return sorted(symbols)


def acquire_lock(root):
    path = Path(root)/"auto_live"/"updater.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def ensure_running(root=ROOT):
    """Start once; the OS lock prevents duplicate workers across tabs/processes."""
    root = Path(root)
    handle = acquire_lock(root)
    if handle is None:
        return
    handle.close()
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    with open(root/"auto_live"/"updater.log", "a", encoding="utf-8") as log:
        subprocess.Popen(
            [sys.executable, "-u", "-m", "scalp_lab.auto_update", "--root", str(root)],
            cwd=PROJECT_ROOT, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt", env=env,
        )


def error_message(exc):
    response = getattr(exc, "response", None)
    if response is not None:
        return f"Market-data request failed (HTTP {response.status_code})"
    return f"Data unavailable ({type(exc).__name__}); retrying automatically"


def snapshot_price(snapshot):
    """Use the most recent timestamp, not the most recent polling time."""
    candidates = []
    for key, field in (("latestTrade", "p"), ("minuteBar", "c"), ("dailyBar", "c")):
        value = snapshot.get(key) or {}
        if value.get(field) and value.get("t"):
            candidates.append((value["t"], float(value[field])))
    return max(candidates, default=(None, None))


def fetch_snapshots(symbols, feed):
    import requests
    from .feeds import BASE, headers
    response = requests.get(BASE+"/v2/stocks/snapshots", headers=headers(),
                            params={"symbols": ",".join(symbols), "feed": feed}, timeout=10)
    if response.status_code in (400, 422) and len(symbols) > 1:
        # An invalid custom ticker must not interrupt every other asset.
        midpoint = len(symbols)//2
        return {**fetch_snapshots(symbols[:midpoint], feed), **fetch_snapshots(symbols[midpoint:], feed)}
    if response.status_code in (400, 404, 422) and len(symbols) == 1:
        return {symbols[0]: {}}
    response.raise_for_status()
    return response.json()


def update_history(root, symbol, feed):
    import joblib
    import numpy as np
    import pandas as pd
    from .feeds import fetch_bars, fetch_news
    from .features import FEATURE_COLUMNS, make_features
    from .news import score_news
    from .signals import paper_levels

    folder = Path(root)/"auto_live"/symbol
    folder.mkdir(parents=True, exist_ok=True)
    bars_path = folder/"bars.csv"
    seed = bars_path if bars_path.exists() else Path(root)/"data"/f"{symbol}_bars.csv"
    bars = pd.read_csv(seed).tail(2500) if seed.exists() else pd.DataFrame()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=10)
    if not bars.empty:
        last = pd.to_datetime(bars["timestamp"], utc=True).max().to_pydatetime()
        start = max(start, last - timedelta(minutes=5))
    try:
        incoming = fetch_bars(symbol, start.isoformat(), end.isoformat(), feed=feed)
    except ValueError as exc:
        if "No bars returned" not in str(exc) or bars.empty:
            raise
        incoming = pd.DataFrame()
    bars = pd.concat([bars, incoming], ignore_index=True)
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    bars = bars[bars.timestamp + pd.Timedelta(minutes=1) <= pd.Timestamp(end)]
    bars = bars.sort_values("timestamp").drop_duplicates("timestamp", keep="last").tail(2500)
    temporary = bars_path.with_suffix(".tmp")
    bars.to_csv(temporary, index=False)
    os.replace(temporary, bars_path)
    if bars.empty:
        return {"state": "Waiting for completed minute bars", "updated_at": utcnow()}

    news_error = None
    try:
        news = fetch_news(symbol, (end-timedelta(hours=2)).isoformat(), end.isoformat())
        # Only news observed by this collector may influence subsequent decisions.
        previous = read_json(folder/"news.json", [])
        first_seen = {str(n.get("id", n.get("headline"))): n.get("received_at") for n in previous}
        records = news.to_dict("records")
        for record in records:
            record["received_at"] = first_seen.get(str(record.get("id", record.get("headline")))) or utcnow()
        atomic_json(folder/"news.json", records)
    except Exception as exc:
        news_error = error_message(exc)
        records = read_json(folder/"news.json", [])

    report_path = Path(root)/f"results_{symbol}"/"report.json"
    report = read_json(report_path)
    model_path = report_path.parent/"paper_models.joblib"
    item = {"symbol": symbol, "created_at": utcnow(), "decision_time": str(bars.iloc[-1].timestamp+pd.Timedelta(minutes=1)),
            "reference_price": float(bars.iloc[-1].close), "signal": "NO_SIGNAL", "feed": feed, "levels": None}
    state = "Data updating; model not trained"
    if report.get("symbol") == symbol and model_path.exists():
        artifact = joblib.load(model_path)
        if artifact.get("features") != FEATURE_COLUMNS:
            raise ValueError("Model feature schema mismatch")
        scored = score_news(pd.DataFrame(records), assumed_latency_s=0) if records else None
        feat = make_features(bars, scored)
        state = "Warming up: needs 31 contiguous market minutes"
        settings = report["settings"]
        item.update(settings=settings, horizon_minutes=report["horizon_minutes"], threshold=float(artifact["threshold"]))
        if not feat.empty and np.isfinite(feat.iloc[-1][FEATURE_COLUMNS].astype(float)).all():
            newest = feat.iloc[-1]
            x = feat.iloc[[-1]][FEATURE_COLUMNS].copy()
            for column, enabled in artifact.get("feature_enabled", {}).items():
                if not enabled:
                    x.loc[:, column] = 0.0
            probabilities = {side: float(artifact["models"][side].predict_proba(x)[0, 1]) for side in ("long", "short")}
            side = max(probabilities, key=probabilities.get)
            age = (pd.Timestamp.now(tz="UTC")-newest.decision_time).total_seconds()
            item.update(decision_time=str(newest.decision_time), reference_price=float(newest.close),
                        long_probability_uncalibrated=probabilities["long"], short_probability_uncalibrated=probabilities["short"])
            state = "Waiting for a qualifying signal"
            if item["threshold"] > 1:
                state = "Model paused: insufficient validation support"
            elif not 0 <= age < 90:
                state = "Waiting for fresh market bars"
            elif news_error:
                state = "News unavailable; signals paused"
            elif probabilities[side] >= item["threshold"]:
                item["signal"] = "PAPER_" + side.upper()
                item["levels"] = paper_levels(item["reference_price"], item["signal"], settings["tp_bps"], settings["sl_bps"])
                state = item["signal"]
    item["reason"] = state
    atomic_json(folder/"signal.json", item)
    return {"state": state, "updated_at": utcnow(), "bar_time": str(bars.iloc[-1].timestamp), "news_error": news_error}


def run(root=ROOT, once=False):
    from dotenv import load_dotenv

    root = Path(root)
    handle = acquire_lock(root)
    if handle is None:
        return
    load_dotenv(ENV_FILE, override=True)
    feed = os.getenv("ALPACA_DATA_FEED", "iex")
    state = {"started_at": utcnow(), "pid": os.getpid(), "feed": feed, "assets": {}}
    futures, next_history = {}, {}
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            while True:
                began = time.monotonic()
                symbols = symbols_for(root)
                for symbol, future in list(futures.items()):
                    if future.done():
                        try:
                            state["assets"][symbol] = future.result()
                        except Exception as exc:
                            state["assets"][symbol] = {"state": error_message(exc), "updated_at": utcnow()}
                        del futures[symbol]
                        next_history[symbol] = time.monotonic()+60
                try:
                    snapshots = fetch_snapshots(symbols, feed)
                    for symbol in symbols:
                        stamp, price = snapshot_price(snapshots.get(symbol) or {})
                        atomic_json(root/"auto_live"/symbol/"snapshot.json",
                                    {"symbol": symbol, "price": price, "market_time": stamp, "checked_at": utcnow(), "feed": feed})
                    state["price_error"] = None
                    state["last_price_check"] = utcnow()
                except Exception as exc:
                    state["price_error"] = error_message(exc)
                for symbol in symbols:
                    if symbol not in futures and time.monotonic() >= next_history.get(symbol, 0):
                        futures[symbol] = pool.submit(update_history, root, symbol, feed)
                        state["assets"].setdefault(symbol, {"state": "Loading minute bars and news"})
                state.update(heartbeat=utcnow(), symbols=symbols)
                atomic_json(root/"auto_live"/"status.json", state)
                if once:
                    for symbol, future in futures.items():
                        try:
                            state["assets"][symbol] = future.result()
                        except Exception as exc:
                            state["assets"][symbol] = {"state": error_message(exc)}
                    state["heartbeat"] = utcnow()
                    atomic_json(root/"auto_live"/"status.json", state)
                    return
                time.sleep(max(1, 15-(time.monotonic()-began)))
    finally:
        handle.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    run(args.root, args.once)

from __future__ import annotations
import numpy as np
import pandas as pd
from .news import add_news_features


def make_features(bars: pd.DataFrame, news=None, symbol="SPY") -> pd.DataFrame:
    d = bars.copy()
    if "timestamp" not in d.columns:
        raise ValueError("Bars CSV must include timestamp,open,high,low,close,volume")
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["timestamp","open","high","low","close","volume"]).sort_values("timestamp")
    d = d.drop_duplicates("timestamp")
    # Regular US trading hours only, using exchange-local time with DST awareness.
    ny = d["timestamp"].dt.tz_convert("America/New_York")
    minute = ny.dt.hour*60+ny.dt.minute
    mask = (minute >= 570) & (minute < 960) & (ny.dt.dayofweek < 5)
    d = d.loc[mask].copy()
    ny = d["timestamp"].dt.tz_convert("America/New_York")
    d["session"] = ny.dt.strftime("%Y-%m-%d")
    d["minute_in_session"] = (ny.dt.hour*60 + ny.dt.minute - 570).astype(float)
    d["decision_time"] = d["timestamp"] + pd.Timedelta(minutes=1)
    d["segment"] = ((d["session"] != d["session"].shift()) | (d["timestamp"].diff() != pd.Timedelta(minutes=1))).cumsum()
    group = d.groupby("segment", sort=False)
    close = d["close"]
    for n in [1, 3, 5, 10, 20]:
        d[f"ret_{n}"] = group["close"].pct_change(n).replace([np.inf,-np.inf],np.nan) * 1e4
    d["range_bps"] = (d["high"]-d["low"]) / close * 1e4
    d["body_bps"] = (d["close"]-d["open"]) / d["open"] * 1e4
    ret1 = group["close"].pct_change() * 1e4
    d["vol_10"] = ret1.groupby(d["segment"]).transform(lambda s: s.rolling(10, min_periods=10).std())
    d["vol_30"] = ret1.groupby(d["segment"]).transform(lambda s: s.rolling(30, min_periods=30).std())
    d["volume_ratio_20"] = d["volume"] / group["volume"].transform(lambda s: s.rolling(20, min_periods=20).mean()).replace(0, np.nan)
    d["turnover"] = d["volume"]*d["close"]
    d["turnover_ratio_20"] = d["turnover"] / d.groupby("session")["turnover"].transform(lambda s: s.rolling(20, min_periods=20).mean()).replace(0,np.nan)
    d["vwap_session"] = (d["close"]*d["volume"]).groupby(d["session"]).cumsum()/d["volume"].groupby(d["session"]).cumsum().replace(0,np.nan)
    d["vwap_distance_bps"] = (d["close"] / d["vwap_session"] - 1) * 1e4
    d["minute_sin"] = np.sin(2*np.pi*d["minute_in_session"]/390)
    d["minute_cos"] = np.cos(2*np.pi*d["minute_in_session"]/390)
    d["spread_bps"] = pd.to_numeric(d.get("spread_bps", pd.Series(0.0,index=d.index)), errors="coerce")
    d["quote_imbalance"] = pd.to_numeric(d.get("quote_imbalance",pd.Series(0.0,index=d.index)), errors="coerce")
    d = add_news_features(d, news)
    return d.reset_index(drop=True)

FEATURE_COLUMNS = ["ret_1","ret_3","ret_5","ret_10","ret_20","range_bps", "body_bps", "vol_10", "vol_30", "volume_ratio_20", "turnover_ratio_20", "vwap_distance_bps", "minute_sin", "minute_cos", "spread_bps", "quote_imbalance", "news_score_15m", "news_count_15m", "news_flag_5m"]

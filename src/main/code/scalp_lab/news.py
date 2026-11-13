"""Time-aware news. Historical feed timestamps are only proxies for delivery times."""
from __future__ import annotations
import numpy as np
import pandas as pd

POSITIVE = {"beats", "beat", "upgrade", "upgraded", "surge", "surges", "growth", "record", "profit", "profits", "raises", "strong", "approval", "wins", "breakthrough", "outperform"}
NEGATIVE = {"misses", "miss", "downgrade", "downgraded", "lawsuit", "probe", "investigation", "falls", "plunges", "loss", "losses", "warning", "cuts", "weak", "recall", "fraud"}


def lexicon_score(text):
    import re
    words = set(re.findall(r"[a-z]+", str(text).lower()))
    pos, neg = len(words & POSITIVE), len(words & NEGATIVE)
    return float((pos-neg)/(pos+neg)) if pos+neg else 0.0


def score_news(news, use_finbert=False, assumed_latency_s=60):
    """FinBERT optional; do not claim lexicon is sophisticated NLP."""
    if news is None or len(news)==0:
        return pd.DataFrame(columns=["available_at", "score", "headline"])
    d = news.copy()
    if "headline" not in d.columns:
        raise ValueError("News CSV needs headline and created_at (or received_at).")
    d["headline"] = d["headline"].fillna("").astype(str)
    if "received_at" in d.columns:
        # Actual observed receipt beats publisher timestamp for live historical replay.
        available = pd.to_datetime(d["received_at"], utc=True, errors="coerce")
        created = pd.to_datetime(d.get("created_at"), utc=True, errors="coerce")
        d["available_at"] = available.fillna(created + pd.Timedelta(seconds=assumed_latency_s))
    else:
        d["available_at"] = pd.to_datetime(d["created_at"], utc=True, errors="coerce") + pd.Timedelta(seconds=assumed_latency_s)
    d = d.dropna(subset=["available_at"])
    if use_finbert:
        try:
            from transformers import pipeline
        except ImportError as exc:
            raise RuntimeError("FinBERT needs: pip install transformers torch") from exc
        classifier = pipeline("text-classification", model="ProsusAI/finbert", truncation=True)
        raw = classifier(d["headline"].tolist(), batch_size=16)
        d["score"] = [float(item["score"]) * {"positive":1,"negative":-1,"neutral":0}.get(item["label"].lower(),0) for item in raw]
    else:
        d["score"] = d["headline"].map(lexicon_score)
    return d[["available_at", "score", "headline"]].sort_values("available_at").reset_index(drop=True)


def add_news_features(features, scored_news, window_minutes=15):
    """Only events available as-of each decision time are counted."""
    result = features.copy()
    result["news_score_15m"] = 0.0
    result["news_count_15m"] = 0.0
    result["news_flag_5m"] = 0.0
    if scored_news is None or scored_news.empty:
        return result
    ns = scored_news.sort_values("available_at")
    times = ns["available_at"].values.astype("datetime64[ns]")
    scores = ns["score"].to_numpy(float)
    cumul = np.concatenate([[0.0], np.cumsum(scores)])
    decision_times = result["decision_time"].values.astype("datetime64[ns]")
    right = np.searchsorted(times, decision_times, side="right")
    left = np.searchsorted(times, decision_times - np.timedelta64(window_minutes, 'm'), side="right")
    recent = np.searchsorted(times, decision_times - np.timedelta64(5, 'm'), side="right")
    result["news_score_15m"] = (cumul[right]-cumul[left])/np.maximum(1, right-left)
    result["news_count_15m"] = (right-left).astype(float)
    result["news_flag_5m"] = ((right-recent)>0).astype(float)
    return result

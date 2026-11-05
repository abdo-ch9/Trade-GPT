"""Price levels for experimental paper signals, never order instructions."""
import math


def decision_summary(signal, now=None):
    """Explain the recorded model decision without promoting a score to a trade."""
    import pandas as pd
    signal = signal or {}
    current = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    stamp = pd.to_datetime(signal.get("decision_time"), utc=True, errors="coerce")
    fresh = stamp is not None and not pd.isna(stamp) and 0 <= (current-stamp).total_seconds() < 90
    pl, ps = signal.get("long_probability_uncalibrated"), signal.get("short_probability_uncalibrated")
    scores_valid = all(isinstance(p,(int,float)) and math.isfinite(p) and 0<=p<=1 for p in (pl,ps))
    lean = ("LONG" if pl>ps else "SHORT" if ps>pl else "NEUTRAL") if scores_valid else "Unavailable"
    threshold = signal.get("threshold")
    supported = isinstance(threshold,(int,float)) and math.isfinite(threshold) and 0<=threshold<=1
    reasons=[]
    if threshold is not None and not supported:
        reasons.append("Model disabled: validation did not support a trading threshold. Waiting for new prices alone will not enable this model.")
    if not fresh:
        reasons.append("No fresh regular-session model reading is available.")
    if not scores_valid or threshold is None:
        reasons.append("A trained model with complete scores is not available for this asset.")
    action="NO TRADE"
    side=signal.get("signal")
    qualified = fresh and supported and scores_valid
    if qualified and side=="PAPER_LONG" and pl>=threshold:
        action="BUY / LONG"
    elif qualified and side=="PAPER_SHORT" and ps>=threshold:
        action="SELL / SHORT"
    elif qualified:
        reasons.append(signal.get("reason") or "No model-qualified signal at this time.")
    if threshold is None:
        status = "MODEL NOT READY"
    elif not supported:
        status = "MODEL DISABLED"
    elif not fresh:
        status = "WAITING FOR FRESH DATA"
    elif not scores_valid:
        status = "MODEL WARMING UP"
    else:
        status = action
    return {"action":action,"status":status,"reason":" ".join(reasons) if reasons else "Fresh signal meets the model's configured threshold.",
            "lean":lean,"fresh":bool(fresh),"scores_valid":scores_valid}


def adaptive_distances(bars, horizon=5, cost_bps=0.0, now=None):
    """Transparent volatility-based scenario heuristic, not a fitted strategy.

    Uses only completed, contiguous regular-session bars. No forward prices,
    cross-session returns, or silently substituted fixed distances.
    """
    import numpy as np
    import pandas as pd

    if horizon < 1 or not math.isfinite(float(horizon)) or cost_bps < 0 or not math.isfinite(float(cost_bps)):
        raise ValueError("Invalid horizon or cost")
    if bars is None or len(bars) == 0:
        return {"available": False, "reason": "Waiting for minute bars"}
    d = bars.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        d[column] = pd.to_numeric(d[column], errors="coerce")
    d = d.replace([np.inf, -np.inf], np.nan).dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    current = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    d = d[(d.timestamp+pd.Timedelta(minutes=1)<=current) & (d.low>0) & (d.high>=d.low) & (d.close>0) & (d.volume>=0)]
    d = d.sort_values("timestamp").drop_duplicates("timestamp",keep="last")
    ny = d.timestamp.dt.tz_convert("America/New_York")
    minute = ny.dt.hour*60+ny.dt.minute
    d = d[(minute>=570)&(minute<960)&(ny.dt.dayofweek<5)].copy()
    if d.empty:
        return {"available": False, "reason": "Waiting for regular-session minute bars"}
    segments = (d.timestamp.diff()!=pd.Timedelta(minutes=1)).cumsum()
    d = d[segments==segments.iloc[-1]].tail(31)
    if len(d)<31:
        return {"available": False, "reason": f"Need 31 consecutive regular-session bars; have {len(d)}"}
    price = float(d.close.iloc[-1])
    previous = d.close.shift()
    true_range = pd.concat([d.high-d.low,(d.high-previous).abs(),(d.low-previous).abs()],axis=1).max(axis=1)
    atr_bps = float(true_range.tail(14).mean()/price*10000)
    returns = np.log(d.close/d.close.shift())*10000
    volatility = float(returns.dropna().std(ddof=1))
    velocity = float(np.log(d.close.iloc[-1]/d.close.iloc[-6])*10000/5)
    baseline_volume = float(d.volume.iloc[-21:-1].mean())
    volume_ratio = float(d.volume.tail(5).mean()/baseline_volume) if baseline_volume>0 else 1.0
    spread = None
    if "spread_bps" in d:
        observed = pd.to_numeric(d.spread_bps.tail(5),errors="coerce")
        observed = observed[np.isfinite(observed)&(observed>0)]
        if len(observed):
            spread = float(observed.median())
    volume_factor = float(np.clip(math.sqrt(volume_ratio),0.9,1.2))
    # Constants define a research heuristic, not empirically optimized parameters.
    stop = max(1.2*atr_bps, volatility*math.sqrt(horizon))*volume_factor
    stop = max(stop, 2*(spread or 0), 1.2*cost_bps, 0.01/price*10000)
    target = 1.5*stop+min(abs(velocity)*horizon,0.5*stop)
    decision = d.timestamp.iloc[-1]+pd.Timedelta(minutes=1)
    return {"available": True, "tp_bps": max(0.001,round(target,3)), "sl_bps": max(0.001,round(stop,3)),
            "atr_bps": round(atr_bps,3), "volatility_bps": round(volatility,3),
            "velocity_bps_per_minute": round(velocity,3), "volume_ratio": round(volume_ratio,3),
            "spread_bps": spread, "cost_bps": cost_bps, "horizon_minutes": horizon,
            "as_of": str(decision), "stale": (current-decision).total_seconds()>=90}


def paper_levels(reference, side, tp_bps, stop_bps):
    values = (reference, tp_bps, stop_bps)
    if not all(math.isfinite(float(v)) and float(v) > 0 for v in values):
        raise ValueError("Reference price, target and stop must be positive finite numbers")
    if side not in ("PAPER_LONG", "PAPER_SHORT"):
        return None
    direction = 1 if side == "PAPER_LONG" else -1
    return {
        "reference_price": float(reference),
        "take_profit": reference * (1 + direction * tp_bps / 10000),
        "stop_loss": reference * (1 - direction * stop_bps / 10000),
        "reward_risk": tp_bps / stop_bps,
    }

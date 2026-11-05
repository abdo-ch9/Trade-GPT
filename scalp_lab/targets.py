"""Fast, conservative minute-path paper outcomes.

At completed bar i: next bar open is earliest hypothetical entry.
Same-bar take-profit AND stop hit => stop occurs first (pessimistic).
Incomplete horizons and missing calendar minutes => excluded.
"""
import numpy as np
import pandas as pd


def label_outcomes(frame, horizon=5, tp_bps=18, sl_bps=12, cost_bps=6):
    if tp_bps <= 0 or sl_bps <= 0 or horizon < 1 or cost_bps < 0:
        raise ValueError("Horizon/stop/target/cost parameters must be valid")
    d = frame.copy().reset_index(drop=True)
    d["pnl_long"] = np.nan
    d["pnl_short"] = np.nan
    # Segments defined using exact 1-minute bars; no horizon crosses gaps or overnight.
    for _, group in d.groupby("segment", sort=False):
        n=len(group)
        m=n-horizon
        if m<=0:
            continue
        arr={col: group[col].to_numpy(dtype=float) for col in ("open","high","low","close")}
        entry=arr["open"][1:m+1]
        if np.any(entry<=0):
            continue
        for direction in ("long","short"):
            pnl=np.full(m,np.nan)
            active=np.ones(m,dtype=bool)
            for step in range(1,horizon+1):
                high=(arr["high"][step:step+m]/entry-1)*1e4* (1 if direction=="long" else -1)
                low=(arr["low"][step:step+m]/entry-1)*1e4* (1 if direction=="long" else -1)
                favorable=np.maximum(high,low)
                adverse=np.minimum(high,low)
                stop=active & (adverse<=-sl_bps)
                pnl[stop]=-sl_bps-cost_bps
                active[stop]=False
                win=active & (favorable>=tp_bps)
                pnl[win]=tp_bps-cost_bps
                active[win]=False
            expiry=(arr["close"][horizon:horizon+m]/entry-1)*1e4*(1 if direction=="long" else -1)
            pnl[active]=expiry[active]-cost_bps
            d.loc[group.index[:m],f"pnl_{direction}"]=pnl
    for direction in ("long","short"):
        d[f"y_{direction}"] = (d[f"pnl_{direction}"] > 0).astype(int)
    return d

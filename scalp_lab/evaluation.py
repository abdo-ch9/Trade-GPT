"""Chronological training, separate validation tuning and untouched test period."""
from __future__ import annotations
import json
from pathlib import Path
from math import sqrt
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, roc_auc_score
from .features import FEATURE_COLUMNS


def wilson_lower_bound(wins, n, z=1.96):
    if not n:
        return 0.0
    p = wins/n
    return (p + z*z/(2*n) - z*sqrt((p*(1-p)+z*z/(4*n))/n))/(1+z*z/n)


def choose_one_trade_at_a_time(frame, probs_long, probs_short, threshold, horizon=5):
    """Simulation uses fixed next-open entry and prevents overlapping positions."""
    records=[]
    last_exit_ix = -1
    for ix in range(len(frame)):
        row=frame.iloc[ix]
        if ix <= last_exit_ix:
            continue
        pl, ps = float(probs_long[ix]),float(probs_short[ix])
        if max(pl,ps) < threshold:
            continue
        direction = "long" if pl >= ps else "short"
        pnl = row[f"pnl_{direction}"]
        if not np.isfinite(pnl):
            continue
        records.append({"time":str(row["decision_time"]),"session":row["session"],"side":direction.upper(),"predicted_probability":round(max(pl,ps),4),"paper_pnl_bps":round(float(pnl),3),"win":int(pnl>0)})
        last_exit_ix = ix + horizon
    return pd.DataFrame(records, columns=["time","session","side","predicted_probability","paper_pnl_bps","win"])


def report_metrics(trades):
    n=len(trades)
    if not n:
        return dict(trades=0, win_rate=None, wilson_95pct_lower=None, mean_net_bps=None, cumulative_net_bps=0.0, max_drawdown_bps=0.0, profit_factor=None)
    pnl=trades["paper_pnl_bps"].to_numpy(float)
    wins=int((pnl>0).sum())
    equity=np.insert(np.cumsum(pnl),0,0.0)
    dd=equity-np.maximum.accumulate(equity)
    return dict(trades=n, win_rate=round(wins/n,4), wilson_95pct_lower=round(wilson_lower_bound(wins,n),4), mean_net_bps=round(float(pnl.mean()),3), cumulative_net_bps=round(float(pnl.sum()),3), max_drawdown_bps=round(float(dd.min()),3), profit_factor=round(float(pnl[pnl>0].sum()/abs(pnl[pnl<0].sum())),3) if (pnl<0).any() else None)


def _prob(model, data):
    # Classifier can be constant if data regime is extremely one-sided.
    if hasattr(model,"classes_") and len(model.classes_)==1:
        return np.full(len(data), float(model.classes_[0]))
    return model.predict_proba(data)[:,1]


def _fit(train, side):
    x = train[FEATURE_COLUMNS].replace([np.inf,-np.inf],np.nan).fillna(0.0)
    y = train[f"y_{side}"].astype(int)
    if y.nunique() < 2:
        raise ValueError(f"Training data for {side} has only one outcome; expand sample/change label settings")
    m=HistGradientBoostingClassifier(max_iter=130, max_leaf_nodes=12, learning_rate=0.045, l2_regularization=10, min_samples_leaf=40, random_state=41)
    m.fit(x,y)
    return m


def backtest(frame, horizon=5, output="results", min_validation_trades=25, target_winrate=0.80):
    d=frame.dropna(subset=FEATURE_COLUMNS+["pnl_long","pnl_short"]).sort_values("timestamp").reset_index(drop=True)
    days=d["session"].unique()
    if len(days)<15:
        raise ValueError(f"Only {len(days)} sessions with complete features; need >=15 sessions for a demonstration and preferably 90+ for research.")
    a=max(1,int(len(days)*0.60)); b=max(a+1,int(len(days)*0.80))
    train=d[d.session.isin(days[:a])].copy()
    val=d[d.session.isin(days[a:b])].copy()
    test=d[d.session.isin(days[b:])].copy()
    feature_enabled={col: bool((train[col].abs()>1e-12).any()) for col in FEATURE_COLUMNS}
    models={side:_fit(train,side) for side in ["long","short"]}
    val_x=val[FEATURE_COLUMNS];test_x=test[FEATURE_COLUMNS]
    pv={side:_prob(models[side],val_x) for side in models}
    pt={side:_prob(models[side],test_x) for side in models}
    # Threshold selection is only based on validation (never on test).
    candidates=[]
    for threshold in np.round(np.arange(0.50,0.96,0.01),3):
        trades=choose_one_trade_at_a_time(val,pv["long"],pv["short"],threshold,horizon)
        metrics=report_metrics(trades)
        if metrics["trades"]>=min_validation_trades:
            candidates.append((threshold,metrics))
    if candidates:
        # Optimize validation mean P&L after costs, rather than win-rate alone.
        threshold, _ = max(candidates,key=lambda x:(x[1]["mean_net_bps"],x[1]["win_rate"]))
    else:
        threshold=1.01  # Prevent claims on tiny validation sets; NO SIGNAL.
    validation_trades=choose_one_trade_at_a_time(val,pv["long"],pv["short"],threshold,horizon)
    test_trades=choose_one_trade_at_a_time(test,pt["long"],pt["short"],threshold,horizon)
    metrics=report_metrics(test_trades)
    validation=report_metrics(validation_trades)
    metrics["sessions_tested"]=len(days[b:]);metrics["first_test_session"]=str(days[b]); metrics["last_test_session"]=str(days[-1]);
    metrics["target_winrate_met"]=(metrics["win_rate"] is not None and metrics["win_rate"]>=target_winrate)
    metrics["statistically_supported_80pct"]=(metrics["trades"]>=100 and metrics["wilson_95pct_lower"]>=target_winrate and (metrics["mean_net_bps"] or 0)>0)
    quality={}
    for side in ("long","short"):
        actual=test[f"y_{side}"].astype(int)
        prob=pt[side]
        quality[side]={"brier":round(float(brier_score_loss(actual,prob)),4),"roc_auc":round(float(roc_auc_score(actual,prob)),4) if actual.nunique()>1 else None, "base_win_frequency":round(float(actual.mean()),4)}
    results=dict(test=metrics, validation=validation, quality=quality, threshold=float(threshold), train_sessions=len(days[:a]), val_sessions=len(days[a:b]), model_type="HistGradientBoostingClassifier", features=FEATURE_COLUMNS, horizon_minutes=horizon, notes="Paper simulation; historical news publisher timestamps may precede actual availability; IEX incomplete; labels assume pessimistic same-bar stop; costs are assumed, not measured. No live orders.")
    dest=Path(output);dest.mkdir(parents=True,exist_ok=True)
    test_trades.to_csv(dest/"test_paper_trades.csv",index=False)
    validation_trades.to_csv(dest/"validation_paper_trades.csv",index=False)
    with open(dest/"report.json","w",encoding="utf-8") as f:json.dump(results,f,indent=2)
    joblib.dump({"models":models,"features":FEATURE_COLUMNS,"feature_enabled":feature_enabled,"threshold":float(threshold),"horizon":horizon},dest/"paper_models.joblib")
    return results

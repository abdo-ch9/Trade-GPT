"""Explain validation abstention without changing models or thresholds."""
import numpy as np
import pandas as pd
import joblib
from .auto_update import ROOT, atomic_json, read_json, symbols_for
from .features import FEATURE_COLUMNS, make_features
from .news import score_news
from .targets import label_outcomes
from .evaluation import choose_one_trade_at_a_time, report_metrics


def run():
    diagnostics={}
    for symbol in symbols_for(ROOT):
        folder=ROOT/f"results_{symbol}"
        report=read_json(folder/"report.json")
        if not report:
            continue
        settings=report["settings"]
        bars=pd.read_csv(ROOT/"data"/f"{symbol}_bars.csv")
        news=pd.read_csv(ROOT/"data"/f"{symbol}_news.csv")
        frame=make_features(bars,score_news(news,assumed_latency_s=settings["news_delay_seconds"]))
        frame=label_outcomes(frame,horizon=report["horizon_minutes"],tp_bps=settings["tp_bps"],sl_bps=settings["sl_bps"],cost_bps=settings["roundtrip_cost_bps"])
        frame=frame.dropna(subset=FEATURE_COLUMNS+["pnl_long","pnl_short"]).sort_values("timestamp").reset_index(drop=True)
        days=frame.session.unique()
        a=report["train_sessions"]
        b=a+report["val_sessions"]
        validation=frame[frame.session.isin(days[a:b])]
        artifact=joblib.load(folder/"paper_models.joblib")
        probabilities={side:artifact["models"][side].predict_proba(validation[FEATURE_COLUMNS])[:,1] for side in ("long","short")}
        candidates=[]
        for threshold in np.round(np.arange(0.50,0.96,0.025),3):
            trades=choose_one_trade_at_a_time(validation,probabilities["long"],probabilities["short"],threshold,report["horizon_minutes"])
            candidates.append({"threshold":float(threshold),**report_metrics(trades)})
        diagnostics[symbol]={"maximum_validation_trades":max(c["trades"] for c in candidates),
                             "required_validation_trades":25,"validation_sessions":len(validation.session.unique()),
                             "peak_long_score":float(probabilities["long"].max()),
                             "peak_short_score":float(probabilities["short"].max()),
                             "thresholds_checked":candidates,
                             "settings":settings,"active_threshold":report["threshold"]}
        atomic_json(ROOT/"auto_live"/"model_diagnostics.json",diagnostics)
        print(f"{symbol}: best supported trade count {diagnostics[symbol]['maximum_validation_trades']} / 25; peak long {diagnostics[symbol]['peak_long_score']:.3f}, short {diagnostics[symbol]['peak_short_score']:.3f}",flush=True)


if __name__=="__main__":
    run()

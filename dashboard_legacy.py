"""Optional Streamlit display. Run: streamlit run dashboard.py"""
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from scalp_lab.auto_update import add_symbol, ensure_running, read_json, symbols_for

st.set_page_config(page_title="ScalpLab — research only", layout="wide")
st.markdown("""<style>
.block-container {max-width:1320px;padding-top:2rem;}
h1,h2,h3 {letter-spacing:-.03em;text-wrap:balance;}
[data-testid="stMetricValue"] {font-variant-numeric:tabular-nums;}
[data-testid="stMetric"] {background:rgba(128,128,128,.07);padding:1rem;border-radius:8px;}
button {transition:background .2s,transform .2s;}
button:active {transform:translateY(1px);}
</style>""",unsafe_allow_html=True)
st.title("Asset signal desk")
st.warning("Research and optional automatic IC Markets demo trading. Model scores are uncalibrated. Real-money accounts are blocked.")
base_dir=Path(__file__).resolve().parent
def render_planner(bars, reference, reference_time, symbol, settings, report):
    st.subheader("Paper trade planner")
    st.caption("Scenario preview only. These levels do not turn WAIT into a trade recommendation.")
    from scalp_lab.signals import paper_levels, adaptive_distances
    horizon=int(report.get("horizon_minutes",5))
    dynamic=adaptive_distances(bars,horizon=horizon,cost_bps=float(settings.get("roundtrip_cost_bps",0)))
    mode=st.radio("Target and stop calculation",["Automatic - adapts to market data","Manual override"],horizontal=True,key=f"distance_mode_{symbol}")
    automatic=mode.startswith("Automatic")
    if automatic and not dynamic["available"]:
        st.info(dynamic["reason"]+". Automatic levels appear once enough data is available.")
        return
    if automatic:
        tp,sl=dynamic["tp_bps"],dynamic["sl_bps"]
        st.caption(f"Calculated from bars through {dynamic['as_of']}. Recalculates when new completed bars arrive.")
        if dynamic["stale"]:
            st.warning("Historical preview: recent regular-session bars are unavailable. These distances describe the last recorded session, not current market volatility.")
        with st.expander("Why these distances?"):
            st.write({"Average true range, 14 bars (bps)":dynamic["atr_bps"],"Return volatility, 30 bars (bps/minute)":dynamic["volatility_bps"],"Price velocity, last 5 minutes (bps/minute)":dynamic["velocity_bps_per_minute"],"Recent volume / baseline":dynamic["volume_ratio"],"Measured spread (bps)":dynamic["spread_bps"],"Assumed round-trip cost floor (bps)":dynamic["cost_bps"],"Horizon (minutes)":horizon})
            st.caption("Stop = the greater of 1.2 x average true range and volatility x square root of horizon, adjusted for volume. Floors: twice a measured spread, 1.2 x assumed costs, and a one-cent price move. Target = 1.5 x stop plus a capped velocity allowance. These are research assumptions, not optimized parameters. News and order-book depth are not included.")
    c1,c2,c3=st.columns(3)
    with c1:
        st.metric("Latest observed price", "Unavailable" if reference is None else f"${reference:,.4f}")
        st.caption(f"Source time: {reference_time or 'No data'}")
    with c2:
        if automatic:
            st.metric("Dynamic take-profit distance",f"{tp:.3f} bps")
        else:
            key=f"manual_tp_{symbol}"
            if key not in st.session_state:
                st.session_state[key]=float(dynamic.get("tp_bps",settings.get("tp_bps",18)))
            tp=st.number_input("Take-profit distance (bps)", min_value=0.001, key=key)
    with c3:
        if automatic:
            st.metric("Dynamic stop-loss distance",f"{sl:.3f} bps")
        else:
            key=f"manual_sl_{symbol}"
            if key not in st.session_state:
                st.session_state[key]=float(dynamic.get("sl_bps",settings.get("sl_bps",12)))
            sl=st.number_input("Stop-loss distance (bps)", min_value=0.001, key=key)
    follow_price=st.checkbox("Keep planner entry synced to latest price", value=True, key=f"follow_{symbol}")
    entry_key=f"entry_{symbol}"
    if follow_price or entry_key not in st.session_state:
        st.session_state[entry_key]=max(reference or 1.0,0.0001)
    entry=st.number_input("Hypothetical entry price ($)",min_value=0.0001,format="%.4f",key=entry_key,disabled=follow_price)
    if reference is None:
        st.caption("No asset price is loaded. Enter your own reference price; the default is only a placeholder.")
    plans=[]
    for side,label in [("PAPER_LONG","BUY / LONG scenario"),("PAPER_SHORT","SELL / SHORT scenario")]:
        level=paper_levels(entry,side,tp,sl)
        plans.append({"Direction":label,"Entry ($)":entry,"Take profit ($)":level["take_profit"],"Stop loss ($)":level["stop_loss"],"Reward / risk":level["reward_risk"]})
    st.dataframe(pd.DataFrame(plans),hide_index=True,width="stretch")
    st.caption(f"1 bp = 0.01%. Model horizon: {report.get('horizon_minutes','—')} minutes. Model assumed round-trip costs: {settings.get('roundtrip_cost_bps','—')} bps. Dynamic planner levels have not been backtested. The model scores and live signal levels still use the fixed distances from training.")
    qty=st.number_input("Hypothetical quantity (shares)", min_value=1, value=1, step=1)
    a,b,c=st.columns(3)
    a.metric("Position value",f"${entry*qty:,.2f}")
    b.metric("Loss at stop, before costs",f"${entry*qty*sl/10000:,.2f}")
    c.metric("Profit at target, before costs",f"${entry*qty*tp/10000:,.2f}")
    st.caption("Actual fills, gaps, spreads and fees can change outcomes. Short availability depends on the broker instrument. This stock planner places no orders; IC Markets demo trades have separate manual and automatic controls.")


@st.fragment(run_every="5s")
def asset_workspace():
    st.subheader("Asset and paper signal")
    assets={"DEMO": "Synthetic demo", "SPY": "SPDR S&P 500 ETF", "QQQ": "Invesco QQQ ETF", "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "TSLA": "Tesla"}
    available=[key for key in assets if key!="DEMO" and (base_dir/f"results_{key}"/"report.json").exists()]
    choice=st.selectbox("Choose an asset", list(assets)+["Other ticker"], index=list(assets).index(available[0]) if available else 0, format_func=lambda x: f"{x} — {assets[x]}" if x in assets else x)
    symbol=st.text_input("Asset ticker", "AMD").strip().upper() if choice=="Other ticker" else choice
    import re
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", symbol):
        st.error("Enter a valid stock or ETF ticker.")
        st.stop()
    st.header(f"{symbol} · {assets.get(symbol, 'Custom asset')}")
    st.caption("US stocks and ETFs · Paper research · Prices in USD")
    add_symbol(base_dir, symbol)
    ensure_running(base_dir)
    status=read_json(base_dir/"auto_live"/"status.json")
    training=read_json(base_dir/"auto_live"/"training.json")
    diagnostics=read_json(base_dir/"auto_live"/"model_diagnostics.json")
    training_state=training.get(symbol,{}).get("state", "")
    if training_state in ("Fetching historical bars and news", "Training and evaluating chronological holdout"):
        st.info(f"{symbol}: {training_state}. This page will pick up the completed model automatically.")
    st.caption("Automatic updates: screen every 5 seconds; all watched prices every 15 seconds; minute bars and news about every minute.")
    if status.get("price_error"):
        st.warning(status["price_error"])
    heartbeat=pd.to_datetime(status.get("heartbeat"),utc=True,errors="coerce")
    if heartbeat is None or pd.isna(heartbeat) or (pd.Timestamp.now(tz="UTC")-heartbeat).total_seconds()>60:
        st.info("The background updater is starting or reconnecting. Last-known values stay visible with their original timestamps.")
    with st.expander("All watched assets"):
        watch_rows=[]
        for ticker in symbols_for(base_dir):
            snap=read_json(base_dir/"auto_live"/ticker/"snapshot.json")
            market_time=pd.to_datetime(snap.get("market_time"),utc=True,errors="coerce")
            age=(pd.Timestamp.now(tz="UTC")-market_time).total_seconds() if market_time is not None and not pd.isna(market_time) else None
            watch_rows.append({"Asset":ticker,"Price ($)":snap.get("price"),"Market timestamp":snap.get("market_time"),"Data":("Current" if 0<=age<90 else "No recent trade / market inactive") if age is not None else "Loading / unavailable","Model":status.get("assets",{}).get(ticker,{}).get("state","Loading")})
        st.dataframe(pd.DataFrame(watch_rows),hide_index=True,width="stretch")
    st.button("Refresh now")
    default_results="results_demo" if symbol=="DEMO" else f"results_{symbol}"
    with st.expander("Data folders"):
        path=Path(st.text_input("Results directory", default_results, key=f"results_{symbol}"))
        live_dir=Path(st.text_input("Live paper monitor folder", f"auto_live/{symbol}", key=f"live_{symbol}"))
    if not path.is_absolute():
        path=base_dir/path
    if not live_dir.is_absolute():
        live_dir=base_dir/live_dir
    report_file=path/"report.json"
    report=json.loads(report_file.read_text()) if report_file.exists() else {}
    report_matches=report.get("symbol")==symbol or (symbol=="DEMO" and path.name=="results_demo")
    settings=report.get("settings",{}) if report_matches else {}
    reference=None
    reference_time=None
    bars_file=base_dir/("demo_data/DEMO_bars.csv" if symbol=="DEMO" else f"data/{symbol}_bars.csv")
    if symbol!="DEMO" and (live_dir/"bars.csv").exists():
        bars_file=live_dir/"bars.csv"
    if bars_file.exists():
        bars=pd.read_csv(bars_file)
        if not bars.empty:
            reference=float(bars.iloc[-1]["close"])
            reference_time=str(bars.iloc[-1]["timestamp"])
    from scalp_lab.charting import render_chart
    render_chart(bars if bars_file.exists() else None,symbol,settings,report)
    rows=[]
    auto_signal=read_json(live_dir/"signal.json")
    if auto_signal.get("symbol")==symbol:
        rows.append(auto_signal)
    for candidate in [live_dir/"paper_signals.jsonl", base_dir/"live"/"paper_signals.jsonl"]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines()[-1000:]:
                try:
                    item=json.loads(line)
                    if item.get("symbol")==symbol:
                        rows.append(item)
                except (json.JSONDecodeError, AttributeError):
                    pass
    valid=[]
    for item in rows:
        try:
            stamp=pd.to_datetime(item["decision_time"], utc=True)
            if not pd.isna(stamp):
                valid.append((stamp,item))
        except (KeyError, ValueError, TypeError):
            pass
    if valid:
        stamp,latest=max(valid,key=lambda pair:pair[0])
        age=(pd.Timestamp.now(tz="UTC")-stamp).total_seconds()
        fresh=0<=age<90
        signal=latest.get("signal", "NO_SIGNAL")
        from scalp_lab.signals import decision_summary
        decision=decision_summary(latest)
        st.metric("Current model status - paper only", decision["status"])
        st.write(decision["reason"])
        if decision["scores_valid"]:
            label="Current model leaning" if decision["fresh"] else "Historical model leaning (not current)"
            st.caption(f"{label}: {decision['lean']}. A higher score alone is not a qualified trade.")
            buy_score,sell_score=st.columns(2)
            buy_score.metric("Long model score (uncalibrated)",f"{latest['long_probability_uncalibrated']:.1%}")
            sell_score.metric("Short model score (uncalibrated)",f"{latest['short_probability_uncalibrated']:.1%}")
            st.caption("These estimate separate after-cost outcomes under the original fixed exits. They are not complementary probabilities or probabilities for the dynamic planner.")
        if latest.get("reference_price") is not None:
            reference=float(latest["reference_price"])
            reference_time=str(stamp)
        st.caption(f"Bar closed: {stamp} · Feed: {latest.get('feed','unknown')} · Horizon: {latest.get('horizon_minutes','unknown')} minutes")
        a,b,c=st.columns(3)
        def price(value):
            return "Unavailable" if value is None else f"${value:,.4f}"
        levels=latest.get("levels") or {}
        a.metric("Last closed price (reference)",price(latest.get("reference_price")))
        b.metric("Take profit",price(levels.get("take_profit")) if fresh else "Unavailable — stale")
        c.metric("Stop loss",price(levels.get("stop_loss")) if fresh else "Unavailable — stale")
        st.caption("Levels use the last closed price, not a confirmed entry fill. Short means a hypothetical short position, not closing an existing holding.")
        with st.expander("Model threshold and assumptions"):
            st.write({"Required threshold":latest.get("threshold"), "Reward / risk before costs":levels.get("reward_risk"), "Assumptions":latest.get("settings",{})})
        with st.expander("Recent signals for this asset"):
            st.dataframe(pd.DataFrame([item for _,item in sorted(valid,key=lambda pair:pair[0],reverse=True)]),hide_index=True)
    else:
        st.metric("Current model status - paper only", "WAITING FOR DATA" if report_matches else "MODEL NOT READY")
        st.write("No current buy or sell signal is available. The last saved price and the planner below are historical references.")
    snapshot=read_json(base_dir/"auto_live"/symbol/"snapshot.json")
    if snapshot.get("price") is not None:
        reference=float(snapshot["price"])
        reference_time=snapshot.get("market_time")
        st.caption(f"Latest observed market price: ${reference:,.4f} | Market time: {reference_time} | Feed: {snapshot.get('feed')} | Last checked: {snapshot.get('checked_at')}")
    if report_matches and report.get("threshold",0)>1:
        diagnostic=diagnostics.get(symbol,{})
        if diagnostic:
            st.info(f"Validation produced at most {diagnostic['maximum_validation_trades']} qualifying trades across {diagnostic['validation_sessions']} sessions; this strategy requires {diagnostic['required_validation_trades']}. The current model is disabled. New market prices alone will not fix this.")
            with st.expander("Validation threshold audit"):
                st.dataframe(pd.DataFrame(diagnostic["thresholds_checked"]),hide_index=True,width="stretch")
        else:
            st.info("Model paused: validation did not find enough qualifying trades. Buy and sell signals are disabled for this model.")
    render_planner(bars if bars_file.exists() else None,reference,reference_time,symbol,settings,report)
    from scalp_lab.mt5_demo import render_panel
    render_panel(symbol)
    with st.expander("Model training and data connection", expanded=False):
        if symbol=="DEMO":
            st.write("Select a real ticker to set up its data feed and paper monitor.")
        else:
            st.write("Prices, minute bars and news update automatically for every watched ticker using your saved credentials. A separate trained model is needed for each asset to produce paper signals. These commands train that model; the background updater discovers it automatically.")
            from datetime import date, timedelta
            end=date.today()
            start=end-timedelta(days=180)
            st.code(f"python -m scalp_lab fetch --ticker {symbol} --start {start} --end {end} --feed iex --dir data\npython -m scalp_lab backtest --symbol {symbol} --bars data/{symbol}_bars.csv --news data/{symbol}_news.csv --out results_{symbol}",language="powershell")
            st.caption("Selecting a custom ticker adds it to automatic background updates. Data updates continue while the computer and updater are running, even after closing the browser tab. DEMO stays synthetic.")
    with st.expander("Historical model results and validation", expanded=False):
        st.subheader("Historical model results")
        report_file=path/"report.json"
        if not report_file.exists():
            st.info(f"No trained report yet for {symbol}. Market data still updates automatically. Open Model training and data connection to train this asset.")
            st.stop()
        if path.resolve()==(base_dir/"results_demo").resolve():
            st.info("Showing synthetic demo results. These verify the pipeline only; they do not measure stock prediction accuracy.")
        report=json.loads(report_file.read_text())
        if symbol!="DEMO" and report.get("symbol")!=symbol:
            st.error("This report is not labeled for the selected asset. Re-run its backtest with --symbol as shown above.")
            st.stop()
        st.caption(f"Model: {report['model_type']} · decision horizon: {report['horizon_minutes']} minutes · threshold: {report['threshold']:.3f}")
        summary=report["test"]
        a,b,c,d=st.columns(4)
        a.metric("Untouched test trades",summary["trades"])
        b.metric("Historical win rate", "Not available" if summary["win_rate"] is None else f"{summary['win_rate']*100:.1f}%")
        c.metric("Avg net P&L per trade", "Not available" if summary["mean_net_bps"] is None else f"{summary['mean_net_bps']:.1f} bps")
        d.metric("95% Wilson lower bound", "Not available" if summary["trades"]==0 else f"{summary['wilson_95pct_lower']*100:.1f}%")
        st.json({"validation":report["validation"],"test_period": [summary["first_test_session"],summary["last_test_session"]],"out_of_sample_target_supported":summary["statistically_supported_80pct"]})
        trades_file=path/"test_paper_trades.csv"
        if trades_file.exists():
            trades=pd.read_csv(trades_file)
            if not trades.empty:
                trades["accumulated_bps"]=trades["paper_pnl_bps"].cumsum()
                st.line_chart(trades.set_index("time")["accumulated_bps"])
                st.dataframe(trades,hide_index=True,width="stretch")
        st.caption(report.get("notes",""))

asset_workspace()

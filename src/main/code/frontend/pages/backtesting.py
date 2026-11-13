"""Historical evaluation and research output, away from the live chart."""
from concurrent.futures import ThreadPoolExecutor
import json

import pandas as pd
import streamlit as st

from frontend import components, services
from .common import page_state


_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gold-evaluation")


def render():
    components.heading("Research / historical", "Strategy & backtesting",
                       "Evaluate broker candles without blocking navigation or changing trading rules.")
    state = page_state()
    if state is None:
        return
    broker, identity, account, instruments, instrument, offset = state
    symbol = instrument.name
    key = "gold_evaluation_future"
    context_key = "gold_evaluation_context"
    future = st.session_state.get(key)
    if future is not None and not future.done():
        st.info("Historical evaluation is running in the background. You can visit other pages and return here.")
        if st.button("Check evaluation progress"):
            st.rerun()
    elif future is not None and future.done():
        try:
            future.result()
            st.success("Historical evaluation completed. The saved report is shown below.")
        except Exception as exc:
            st.error("Evaluation failed: " + str(exc))
        st.session_state.pop(key, None)
    if st.button("Fetch gold history and evaluate", disabled=future is not None and not future.done(),
                 key="evaluate_gold_history"):
        st.session_state[context_key] = (broker.name, broker.environment, tuple(identity), symbol)
        st.session_state[key] = _EXECUTOR.submit(
            services.evaluate_history, broker.name, broker.environment, tuple(identity), symbol,
            instrument.point, offset)
        st.rerun()

    st.caption("Fixed rules · chronological 60/40 development/holdout split · four holdout blocks · 15-minute simulated hold · doubled-cost stress test.")
    report = services.validation_report(broker, symbol)
    if report is None:
        components.empty("No evaluation for this symbol", "Use the button above after loading M1 history in MT5.")
        return
    values = report.get("holdout") or {}
    components.section("Holdout performance")
    components.metrics([
        ("Trades", str(values.get("trades", "—"))),
        ("Expectancy (R)", components.number(values.get("expectancy_r"), 3)),
        ("Profit factor", components.number(values.get("profit_factor"), 2)),
        ("Win rate", components.number(values.get("win_rate") * 100, 1, "%")
         if isinstance(values.get("win_rate"), (int, float)) else "—"),
        ("Max drawdown (R)", components.number(values.get("max_drawdown_r"), 2)),
    ])
    (st.success if report.get("eligible") else st.warning)(report.get("reason", "Validation status unavailable."))
    st.caption(report.get("evaluation_note") or "Historical results do not guarantee future performance.")
    left, right = st.columns(2, gap="large")
    with left:
        components.section("Time blocks")
        st.dataframe(report.get("chronological_folds") or [], hide_index=True, width="stretch")
        components.section("Results by setup")
        breakdown = report.get("setup_breakdown") or {}
        if breakdown:
            st.dataframe(pd.DataFrame(breakdown).T, width="stretch")
        else:
            st.caption("No setup breakdown in this report.")
    with right:
        components.section("Exit reasons")
        exits = report.get("exit_breakdown") or {}
        st.dataframe([{"Reason": key, "Trades": count} for key, count in exits.items()],
                     hide_index=True, width="stretch") if exits else st.caption("No exit breakdown available.")
        components.section("Cost assumptions")
        st.caption("Historical bar spread; adverse slippage of max(1 tick, 5% of M1 ATR) per fill; assumed $0.10/oz round-trip commission. Stops win same-candle collisions. Broker fills can differ.")
        st.caption(report.get("limitations") or "")
    components.section("Research files")
    st.download_button("Download evaluation JSON", json.dumps(report, indent=2),
                       f"{broker.name.lower().replace(' ', '_')}_{symbol}_evaluation.json")
    for filename, label in (("gold_research_trades.csv", "Download historical trades"),
                            ("gold_history.csv", "Download evaluated candles")):
        payload = services.saved_csv(broker, filename)
        if payload:
            st.download_button(label, payload, filename, mime="text/csv")
    payload = services.saved_csv(broker, "gold_research_trades.csv")
    if payload:
        with st.expander("Historical trades · latest 200"):
            from io import BytesIO
            st.dataframe(pd.read_csv(BytesIO(payload)).tail(200), hide_index=True, width="stretch")

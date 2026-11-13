"""Read-only view of the backend's risk policy and current headroom."""
import streamlit as st

from frontend import components
from .common import page_state


def render():
    components.heading("Control / exposure", "Risk management",
                       "The backend checks these limits again immediately before every order.")
    state = page_state()
    if state is None:
        return
    broker, identity, account, instruments, instrument, offset = state
    config = broker.auto.settings()
    try:
        risk = broker.module("gold_snapshot").risk_summary(identity, config)
        with broker.bridge.LOCK:
            mt5 = broker.bridge.api()
            broker.account(identity)
            positions = mt5.positions_get()
            if positions is None:
                raise broker.bridge.DemoError("Current positions are unavailable.")
            demo = broker.mode(account) == "demo"
            reserved = broker.auto.portfolio_stop_risk(
                mt5, positions, offset,
                demo and config.get("exclude_tesla_stop_risk") is True)
    except broker.bridge.DemoError as exc:
        st.error("Risk data unavailable: " + str(exc))
        return
    components.metrics([
        ("Daily budget", components.number(risk["budget"], unit=risk["currency"])),
        ("Remaining", components.number(risk["remaining"], unit=risk["currency"])),
        ("Reserved stop risk", components.number(reserved, unit=risk["currency"])),
        ("Entry attempts", f"{risk['attempts']} / {config.get('max_entries', 5)}"),
    ])
    if risk["remaining"] <= 0:
        st.warning("No daily risk headroom remains. New orders are blocked by backend checks.")
    budget_rule = (f"{config['daily_loss_eur']:.2f} EUR fixed" if config.get("daily_loss_eur") is not None
                   else f"{config['daily_loss_usd']:.2f} USD fixed" if config.get("daily_loss_usd") is not None
                   else f"{config.get('daily_loss_fraction', .01) * 100:g}% of baseline equity")
    left, right = st.columns(2, gap="large")
    with left:
        components.section("Read-only execution rules")
        components.value_table([
            {"Rule": "Position size", "Value": f"{config.get('lots', .01):g} lot"},
            {"Rule": "Daily entry attempts", "Value": f"{config.get('max_entries', 5)} maximum"},
            {"Rule": "Daily budget", "Value": budget_rule},
            {"Rule": "New trade cost reserve", "Value": "20% of estimated stop loss"},
            {"Rule": "Duplicate protection", "Value": "Account, candle, and order journal"},
            {"Rule": "Stop / target", "Value": "Attached to broker order"},
        ])
        st.caption("This page shows current values. Edit fixed trade settings in Automation center; calculated amounts remain read-only.")
    with right:
        components.section("Broker constraints · " + instrument.name)
        components.value_table([
            {"Constraint": "Minimum volume", "Value": getattr(instrument, "volume_min", None)},
            {"Constraint": "Maximum volume", "Value": getattr(instrument, "volume_max", None)},
            {"Constraint": "Volume step", "Value": getattr(instrument, "volume_step", None)},
            {"Constraint": "Contract size", "Value": getattr(instrument, "trade_contract_size", None)},
            {"Constraint": "Minimum stop level", "Value": getattr(instrument, "trade_stops_level", None)},
        ])
        if broker.is_exness:
            passed, reason = broker.gold.execution_validation(
                instrument.name, demo=broker.mode(account) == "demo")
        else:
            passed, reason = broker.gold.execution_validation(instrument.name)
        (st.success if passed else st.warning)("Validation: " + reason)
    if config.get("exclude_tesla_stop_risk"):
        st.warning("Tesla positions are excluded from reserved stop-risk estimates in demo mode. Their equity gains and losses still affect the daily budget.")
    components.section("Recent risk rejections")
    from frontend import services
    recent = services.latest_decisions(broker, identity, [instrument.name], limit=50)
    rejected = [row for row in recent if row.get("Decision") == "BLOCKED"][:10]
    if rejected:
        st.dataframe([{"Time": row.get("Saved at (UTC)"),
                       "Reason": row.get("Reason") or row.get("Execution status")}
                      for row in rejected], hide_index=True, width="stretch")
    else:
        st.caption("No blocked directional decisions are saved for this instrument.")

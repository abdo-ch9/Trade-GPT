"""Read-only data adapters and explicit research actions for frontend pages."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from .context import BROKERS


@st.cache_data(ttl=10, show_spinner=False)
def _research_snapshot(name, identity, symbol, offset):
    broker = BROKERS[name]
    if broker.is_exness:
        result, _ = broker.gold.snapshot(identity, symbol, offset, read_only=True)
    else:
        result, _ = broker.gold.snapshot(identity, symbol, offset)
    return result


def analysis(broker, identity, symbol, offset, *, refresh=False):
    """Use the worker's fresh display snapshot while entries run."""
    if refresh:
        _research_snapshot.clear()
    if broker.auto.settings().get("enabled"):
        result = broker.module("gold_snapshot").read(identity, symbol, offset)
        if result is None:
            return None, "Waiting for a fresh worker snapshot. Previous signals are not actionable."
    else:
        result = _research_snapshot(broker.name, tuple(identity), symbol, offset)
        broker.module("gold_decisions").save(identity, symbol, result)
    return result, None


def current_orders(broker, identity):
    """Read MT5 positions and pending orders without changing the account."""
    bridge = broker.bridge
    with bridge.LOCK:
        mt5 = bridge.api()
        broker.account(identity)
        positions = mt5.positions_get()
        orders = mt5.orders_get()
    if positions is None or orders is None:
        raise bridge.DemoError("MT5 could not read current positions or pending orders.")
    return [item._asdict() for item in positions], [item._asdict() for item in orders]


@st.cache_data(ttl=15, show_spinner=False)
def daily_trading_pnl(name, identity):
    """Account trade deals since UTC midnight, including broker fees; no deposits."""
    broker = BROKERS[name]
    bridge = broker.bridge
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with bridge.LOCK:
        mt5 = bridge.api()
        broker.account(identity)
        deals = mt5.history_deals_get(start, now)
    if deals is None:
        raise bridge.DemoError("MT5 trade history for today is unavailable.")
    trade_types = {mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL}
    return sum(sum(float(getattr(deal, field, 0) or 0)
                   for field in ("profit", "commission", "swap", "fee"))
               for deal in deals if getattr(deal, "symbol", "") and deal.type in trade_types)


def latest_decisions(broker, identity, symbols, limit=200):
    return broker.module("gold_decisions").recent(identity, symbols, limit=limit)


def events(broker, limit=50):
    return broker.module("gold_events").recent(limit=limit)


def performance(broker, identity):
    return broker.module("forward_report").summarize(identity, broker.auto.JOURNAL)


def validation_report(broker, symbol):
    try:
        report = json.loads(broker.gold.REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if report.get("symbol") != symbol or report.get("broker") != broker.bridge.BROKER_NAME:
        return None
    return report


def evaluate_history(broker_name, identity, symbol, point, offset):
    """Read and evaluate history in a background thread; never submit an order."""
    broker = BROKERS[broker_name]
    bridge = broker.bridge
    with bridge.LOCK:
        mt5 = bridge.api()
        broker.account(identity)
        mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 60000)
        broker.account(identity)
    if rates is None or len(rates) < 1000:
        raise bridge.DemoError(f"Need more {symbol} M1 history in MT5 before evaluating.")
    bars = pd.DataFrame(rates)
    bars = bars[bars.time + 60 <= time.time() + offset * 3600]
    report, trades = broker.gold.evaluate(bars, symbol, point)
    from scalp_lab.gold_storage import write_json
    write_json(broker.gold.REPORT, report)
    bars.to_csv(broker.gold.ROOT / "gold_history.csv", index=False)
    trades.to_csv(broker.gold.ROOT / "gold_research_trades.csv", index=False)
    return report


def csv_output(rows):
    return pd.DataFrame(rows).to_csv(index=False)


def saved_csv(broker, filename):
    path = Path(broker.gold.ROOT) / filename
    return path.read_bytes() if path.exists() else None

"""Explicit MT5 position actions with account checks and a one-shot audit trail."""
import json
import math
import sqlite3
import time
import uuid
from contextlib import closing

from . import mt5_demo as bridge
from . import auto_demo as auto
from .gold_events import record
from .paths import LIB_DIR


AUDIT = LIB_DIR / "trade_actions.sqlite3"


def _authorize(identity, confirm_live):
    if __package__.endswith("_live") and confirm_live is not True:
        raise bridge.DemoError("Confirm the real account before this LIVE action.")
    mt5 = bridge.api()
    bridge.checked_account(mt5, identity)
    return mt5


def _position(mt5, ticket):
    positions = mt5.positions_get(ticket=int(ticket))
    if positions is None:
        raise bridge.DemoError("Could not verify the position at MT5.")
    if len(positions) != 1 or positions[0].ticket != int(ticket):
        raise bridge.DemoError("Position changed or is no longer open. Refresh the page.")
    return positions[0]


def _order(mt5, ticket):
    orders = mt5.orders_get(ticket=int(ticket))
    if orders is None:
        raise bridge.DemoError("Could not verify the pending order at MT5.")
    if len(orders) != 1 or orders[0].ticket != int(ticket):
        raise bridge.DemoError("Pending order changed or is no longer active. Refresh the page.")
    return orders[0]


def _send(identity, kind, ticket, request, verify, *, confirm_live=False, offset=None):
    """Persist intent before one send; never retry an unknown outcome."""
    with auto.process_guard(), bridge.LOCK:
        mt5 = _authorize(identity, confirm_live)
        verify(mt5)
        check = mt5.order_check(request)
        if check is None or check.retcode != 0:
            raise bridge.DemoError("MT5 pre-trade check failed: " +
                                   (str(check.comment) if check else "no response"))
        bridge.checked_account(mt5, identity)
        verify(mt5)
        token = uuid.uuid4().hex
        account_key = json.dumps(list(identity))
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(AUDIT, timeout=10)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS actions "
                       "(id TEXT PRIMARY KEY, time REAL, account TEXT, kind TEXT, ticket INTEGER, state TEXT, detail TEXT)")
            unresolved = db.execute(
                "SELECT id FROM actions WHERE account=? AND ticket=? "
                "AND state IN ('sending','unknown','partial','accepted') LIMIT 1",
                (account_key, int(ticket))).fetchone()
            if unresolved:
                raise bridge.DemoError(
                    "A prior action on this ticket has an unresolved outcome. Verify it in MT5 before another action.")
            db.execute("INSERT INTO actions VALUES (?,?,?,?,?,?,?)",
                       (token, time.time(), account_key, kind, int(ticket),
                        "sending", json.dumps({"symbol": request.get("symbol"),
                                               "volume": request.get("volume")})))
            db.commit()
            try:
                bridge.checked_account(mt5, identity)
                verify(mt5)
                if kind == "close":
                    quote = bridge.quote(mt5, request["symbol"], offset)
                    current = quote.ask if request["type"] == mt5.ORDER_TYPE_BUY else quote.bid
                    info = mt5.symbol_info(request["symbol"])
                    if info is None or abs(current - request["price"]) > request["deviation"] * info.point:
                        raise bridge.DemoError("Close quote moved during validation. Review the position again.")
            except bridge.DemoError as exc:
                db.execute("UPDATE actions SET state=?, detail=? WHERE id=?",
                           ("blocked", json.dumps({"message": str(exc)}), token))
                db.commit()
                raise
            try:
                response = mt5.order_send(request)
                if response is None:
                    outcome = {"state": "unknown", "message": "No MT5 response. Check the terminal before another action."}
                else:
                    done = response.retcode == mt5.TRADE_RETCODE_DONE
                    partial = response.retcode == getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", -1)
                    accepted = response.retcode == getattr(mt5, "TRADE_RETCODE_PLACED", -1)
                    outcome = {"state": "filled" if done else "partial" if partial else
                               "accepted" if accepted else "rejected",
                               "retcode": response.retcode,
                               "order": getattr(response, "order", None),
                               "deal": getattr(response, "deal", None),
                               "message": str(getattr(response, "comment", ""))}
            except Exception:
                outcome = {"state": "unknown", "message": "Send outcome unknown. Inspect MT5; this action was not retried."}
            db.execute("UPDATE actions SET state=?, detail=? WHERE id=?",
                       (outcome["state"], json.dumps(outcome), token))
            db.commit()
        record("manual_" + kind, f"{kind} {ticket}: {outcome['state']}",
               {"ticket": int(ticket), "state": outcome["state"], "audit_id": token})
        return outcome


def update_stops(identity, ticket, symbol, stop_loss, take_profit, *, confirm_live=False):
    """Change both protective levels for one exact open position."""
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0
               for v in (stop_loss, take_profit)):
        raise bridge.DemoError("Stop loss and take profit must be positive finite prices.")
    with bridge.LOCK:
        mt5 = _authorize(identity, confirm_live)
        position = _position(mt5, ticket)
        if position.symbol != symbol:
            raise bridge.DemoError("Position symbol changed. Refresh the page.")
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info is None or tick is None:
            raise bridge.DemoError("Current broker symbol or quote is unavailable.")
        distance = info.trade_stops_level * info.point
        buy = position.type == mt5.ORDER_TYPE_BUY
        if buy and not (stop_loss < tick.bid - distance and take_profit > tick.bid + distance):
            raise bridge.DemoError("BUY stops must be below bid and targets above bid, respecting broker distance.")
        if not buy and not (stop_loss > tick.ask + distance and take_profit < tick.ask - distance):
            raise bridge.DemoError("SELL stops must be above ask and targets below ask, respecting broker distance.")
        if position.sl and ((buy and stop_loss < position.sl)
                            or (not buy and stop_loss > position.sl)):
            raise bridge.DemoError("This action cannot widen the existing stop-loss risk.")
        request = {"action": mt5.TRADE_ACTION_SLTP, "position": int(ticket), "symbol": symbol,
                   "sl": round(float(stop_loss), info.digits),
                   "tp": round(float(take_profit), info.digits)}
        def verify(api):
            current = _position(api, ticket)
            if current.symbol != symbol or current.identifier != position.identifier:
                raise bridge.DemoError("Position changed during review.")
        return _send(identity, "stops", ticket, request, verify, confirm_live=confirm_live)


def cancel_pending(identity, ticket, symbol, *, confirm_live=False):
    """Cancel one exact pending order, never a market position."""
    with bridge.LOCK:
        mt5 = _authorize(identity, confirm_live)
        order = _order(mt5, ticket)
        if order.symbol != symbol:
            raise bridge.DemoError("Pending order symbol changed. Refresh the page.")
        request = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)}
        def verify(api):
            current = _order(api, ticket)
            if current.symbol != symbol or current.type != order.type:
                raise bridge.DemoError("Pending order changed during review.")
        return _send(identity, "cancel", ticket, request, verify, confirm_live=confirm_live)


def update_pending_stops(identity, ticket, symbol, stop_loss, take_profit, *, confirm_live=False):
    """Modify protective levels on one pending order without changing its size or entry."""
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0
               for v in (stop_loss, take_profit)):
        raise bridge.DemoError("Stop loss and take profit must be positive finite prices.")
    with bridge.LOCK:
        mt5 = _authorize(identity, confirm_live)
        order = _order(mt5, ticket)
        if order.symbol != symbol:
            raise bridge.DemoError("Pending order symbol changed. Refresh the page.")
        info = mt5.symbol_info(symbol)
        if info is None:
            raise bridge.DemoError("Broker symbol details are unavailable.")
        buy_types = {getattr(mt5, name) for name in
                     ("ORDER_TYPE_BUY_LIMIT", "ORDER_TYPE_BUY_STOP", "ORDER_TYPE_BUY_STOP_LIMIT")
                     if hasattr(mt5, name)}
        sell_types = {getattr(mt5, name) for name in
                      ("ORDER_TYPE_SELL_LIMIT", "ORDER_TYPE_SELL_STOP", "ORDER_TYPE_SELL_STOP_LIMIT")
                      if hasattr(mt5, name)}
        buy = order.type in buy_types
        if not buy and order.type not in sell_types:
            raise bridge.DemoError("Only supported pending BUY/SELL orders can be modified.")
        distance = info.trade_stops_level * info.point
        if buy and not (stop_loss < order.price_open - distance
                        and take_profit > order.price_open + distance):
            raise bridge.DemoError("Pending BUY stop and target must straddle the entry price.")
        if not buy and not (stop_loss > order.price_open + distance
                            and take_profit < order.price_open - distance):
            raise bridge.DemoError("Pending SELL stop and target must straddle the entry price.")
        if order.sl and ((buy and stop_loss < order.sl)
                         or (not buy and stop_loss > order.sl)):
            raise bridge.DemoError("This action cannot widen the existing stop-loss risk.")
        request = {"action": mt5.TRADE_ACTION_MODIFY, "order": int(ticket),
                   "price": float(order.price_open),
                   "sl": round(float(stop_loss), info.digits),
                   "tp": round(float(take_profit), info.digits)}
        if getattr(order, "price_stoplimit", 0):
            request["stoplimit"] = float(order.price_stoplimit)
        if getattr(order, "type_time", None) is not None:
            request["type_time"] = order.type_time
        if getattr(order, "time_expiration", 0):
            request["expiration"] = int(order.time_expiration)
        def verify(api):
            current = _order(api, ticket)
            if (current.symbol != symbol or current.type != order.type
                    or current.volume_initial != order.volume_initial
                    or current.price_open != order.price_open):
                raise bridge.DemoError("Pending order changed during review.")
        return _send(identity, "pending_stops", ticket, request, verify,
                     confirm_live=confirm_live)


def close_position(identity, ticket, symbol, offset, *, confirm_live=False):
    """Send one opposite-side deal for the currently open position volume."""
    with bridge.LOCK:
        mt5 = _authorize(identity, confirm_live)
        position = _position(mt5, ticket)
        if position.symbol != symbol:
            raise bridge.DemoError("Position symbol changed. Refresh the page.")
        side = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = bridge.quote(mt5, symbol, offset)
        info = mt5.symbol_info(symbol)
        if info is None:
            raise bridge.DemoError("Broker symbol details are unavailable.")
        filling = (mt5.ORDER_FILLING_IOC if info.filling_mode & bridge.SYMBOL_FILLING_IOC
                   else mt5.ORDER_FILLING_FOK if info.filling_mode & bridge.SYMBOL_FILLING_FOK
                   else None)
        if filling is None:
            raise bridge.DemoError("Broker does not permit a supported fill policy for this position.")
        request = {"action": mt5.TRADE_ACTION_DEAL, "position": int(ticket), "symbol": symbol,
                   "volume": float(position.volume), "type": side,
                   "price": tick.bid if side == mt5.ORDER_TYPE_SELL else tick.ask,
                   "deviation": 20, "magic": 641106, "comment": "terminal-close",
                   "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling}
        def verify(api):
            current = _position(api, ticket)
            if (current.symbol != symbol or current.identifier != position.identifier
                    or current.volume != position.volume or current.type != position.type):
                raise bridge.DemoError("Position changed during review.")
        return _send(identity, "close", ticket, request, verify,
                     confirm_live=confirm_live, offset=offset)

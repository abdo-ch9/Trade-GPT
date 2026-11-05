"""IC Markets MT5 demo orders. Never accepts a real account."""
import math
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

LOCK=threading.RLock()
LEDGER=Path(__file__).resolve().parents[1]/"demo_orders.sqlite3"
BROKER_NAME="IC Markets"
# MQL5 symbol bit flags (not exported by the Python extension).
SYMBOL_ORDER_MARKET, SYMBOL_ORDER_SL, SYMBOL_ORDER_TP = 1, 16, 32
SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2


class DemoError(RuntimeError):
    pass


def api():
    try:
        import MetaTrader5 as mt5
        return mt5
    except ImportError as exc:
        raise DemoError("Install the optional connector: python -m pip install MetaTrader5") from exc


def checked_account(mt5,expected=None):
    terminal=mt5.terminal_info()
    account=mt5.account_info()
    if terminal is None or account is None or not terminal.connected:
        raise DemoError("Open IC Markets MT5 and sign in to your demo account.")
    if account.trade_mode!=mt5.ACCOUNT_TRADE_MODE_DEMO:
        raise DemoError("Blocked: this is not a DEMO account. Real accounts are never accepted.")
    broker=(str(account.company or "")+" "+str(account.server or "")).lower()
    compact="".join(character for character in broker if character.isalnum())
    if "icmarkets" not in compact and "internationalcapitalmarkets" not in compact:
        raise DemoError("The connected demo account is not identified as IC Markets.")
    identity=(account.login,account.server)
    if expected is not None and tuple(expected)!=identity:
        raise DemoError("The MT5 account changed. Reconnect and review a new ticket.")
    if not account.trade_allowed or not account.trade_expert or not terminal.trade_allowed or terminal.tradeapi_disabled:
        raise DemoError("Trading through Python is disabled in the MT5 terminal or account. Review MT5's trading permissions locally.")
    return account


def connect(path=""):
    with LOCK:
        mt5=api()
        ok=mt5.initialize(path,timeout=10000) if path else mt5.initialize(timeout=10000)
        if not ok:
            raise DemoError("Cannot connect to MT5. Install the IC Markets MT5 terminal, open it, and sign in to demo.")
        account=checked_account(mt5)
        return (account.login,account.server)


def inspect(identity):
    with LOCK:
        mt5=api()
        account=checked_account(mt5,identity)
        symbols=mt5.symbols_get()
        if symbols is None:
            raise DemoError("MT5 could not read available instruments.")
        return account,[s for s in symbols if s.trade_mode in (mt5.SYMBOL_TRADE_MODE_FULL,mt5.SYMBOL_TRADE_MODE_LONGONLY,mt5.SYMBOL_TRADE_MODE_SHORTONLY)]


def quote(mt5,symbol,utc_offset_hours=2):
    # MT5 timestamps may use server wall time. Keep the offset explicit rather than
    # inferring it from a stale tick; IC Markets server conventions can vary.
    if utc_offset_hours not in (0,2,3):
        raise DemoError("Unsupported MT5 server time offset.")
    tick=mt5.symbol_info_tick(symbol)
    if tick is None or not all(math.isfinite(x) and x>0 for x in (tick.bid,tick.ask)) or tick.ask<tick.bid:
        raise DemoError("No valid bid/ask quote for this IC Markets instrument.")
    utc_stamp=(tick.time_msc/1000 if tick.time_msc else tick.time)-utc_offset_hours*3600
    age=time.time()-utc_stamp
    if not -2<=age<=30:
        stamp=datetime.fromtimestamp(utc_stamp,timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        reason=(f"The last quote is {age:,.0f} seconds old." if age>30 else "The quote is ahead of this computer's clock; check Windows date/time synchronization.")
        raise DemoError(f"No fresh IC Markets quote for {symbol}. Last quote: {stamp}. {reason} "
                        "Open this exact instrument in MT5 Market Watch and check whether its bid/ask updates. "
                        "If it does not, check the terminal connection and the instrument's trading session. "
                        "A closed session is one possible cause. Orders require a quote no older than 30 seconds.")
    return tick


def no_existing_exposure(mt5,symbol):
    positions=mt5.positions_get(symbol=symbol)
    orders=mt5.orders_get(symbol=symbol)
    if positions is None or orders is None:
        raise DemoError("Cannot verify existing IC Markets positions and pending orders.")
    if positions or orders:
        raise DemoError("This symbol already has a position or pending order. Manage it in MT5 before opening another here.")


def preview(identity,symbol,side,lots,tp_bps,sl_bps,deviation=20,utc_offset_hours=2):
    with LOCK:
        mt5=api()
        account=checked_account(mt5,identity)
        if side not in ("BUY","SELL"):
            raise DemoError("Choose BUY or SELL explicitly.")
        if not all(math.isfinite(float(v)) and float(v)>0 for v in (lots,tp_bps,sl_bps)):
            raise DemoError("Lots, target and stop must be finite positive values.")
        if not mt5.symbol_select(symbol,True):
            raise DemoError("The exact IC Markets symbol is unavailable in Market Watch.")
        info=mt5.symbol_info(symbol)
        if info is None:
            raise DemoError("IC Markets symbol details are unavailable.")
        allowed=(mt5.SYMBOL_TRADE_MODE_FULL,mt5.SYMBOL_TRADE_MODE_LONGONLY if side=="BUY" else mt5.SYMBOL_TRADE_MODE_SHORTONLY)
        if info.trade_mode not in allowed:
            raise DemoError("This trade direction is not permitted for the instrument.")
        if not info.volume_min<=lots<=info.volume_max or info.volume_step<=0:
            raise DemoError("Lot size is outside the broker's permitted range.")
        steps=Decimal(str(lots))/Decimal(str(info.volume_step))
        if abs(steps-steps.to_integral_value())>Decimal("0.00000001"):
            raise DemoError(f"Lots must be a multiple of {info.volume_step}.")
        no_existing_exposure(mt5,symbol)
        tick=quote(mt5,symbol,utc_offset_hours)
        entry=tick.ask if side=="BUY" else tick.bid
        direction=1 if side=="BUY" else -1
        size=info.trade_tick_size or info.point
        if size<=0:
            raise DemoError("Broker tick size is invalid.")
        quantize=lambda value:round(round(value/size)*size,info.digits)
        tp=quantize(entry*(1+direction*tp_bps/10000))
        sl=quantize(entry*(1-direction*sl_bps/10000))
        stop_base=tick.bid if side=="BUY" else tick.ask
        distance=info.trade_stops_level*info.point
        if min(tp,sl)<=0 or (side=="BUY" and not sl<entry<tp) or (side=="SELL" and not tp<entry<sl):
            raise DemoError("Target or stop collapses at this instrument's tick size. Increase the distance.")
        if direction*(tp-stop_base)<distance or direction*(stop_base-sl)<distance:
            raise DemoError("Target/stop is inside the broker's minimum distance or spread. Increase the distance.")
        if not info.order_mode & SYMBOL_ORDER_MARKET or not info.order_mode & SYMBOL_ORDER_SL or not info.order_mode & SYMBOL_ORDER_TP:
            raise DemoError("This instrument does not support market orders with both attached stop and target.")
        if info.filling_mode & SYMBOL_FILLING_FOK:
            filling=mt5.ORDER_FILLING_FOK
        elif info.filling_mode & SYMBOL_FILLING_IOC:
            filling=mt5.ORDER_FILLING_IOC
        elif info.trade_exemode!=mt5.SYMBOL_TRADE_EXECUTION_MARKET:
            filling=mt5.ORDER_FILLING_RETURN
        else:
            raise DemoError("No supported market-order filling policy.")
        token=uuid.uuid4().hex
        request={"action":mt5.TRADE_ACTION_DEAL,"symbol":symbol,"volume":float(lots),
                 "type":mt5.ORDER_TYPE_BUY if side=="BUY" else mt5.ORDER_TYPE_SELL,
                 "price":entry,"sl":sl,"tp":tp,"deviation":int(deviation),"magic":641104,
                 "comment":"demo-"+token[:12],"type_time":mt5.ORDER_TIME_GTC,"type_filling":filling}
        check=mt5.order_check(request)
        if check is None or check.retcode!=0:
            raise DemoError("IC Markets order check failed: "+(str(check.comment) if check else "no response"))
        margin=mt5.order_calc_margin(request["type"],symbol,float(lots),entry)
        loss=mt5.order_calc_profit(request["type"],symbol,float(lots),entry,sl)
        gain=mt5.order_calc_profit(request["type"],symbol,float(lots),entry,tp)
        return {"id":token,"identity":identity,"created":time.time(),"request":request,"point":info.point,
                "currency":account.currency,"margin":margin,"loss":loss,"gain":gain,"side":side,"utc_offset_hours":utc_offset_hours}


def submit(ticket,ledger=LEDGER):
    """One send attempt per ticket; ambiguous outcomes are never retried."""
    with LOCK:
        from .auto_demo import settings, MAGIC
        if settings().get('enabled') and ticket['request'].get('magic')!=MAGIC:
            raise DemoError('Stop automatic demo trading before placing manual orders here.')
        mt5=api()
        checked_account(mt5,ticket["identity"])
        if not 0<=time.time()-ticket["created"]<=30:
            raise DemoError("Ticket expired. Refresh its quote before placing a demo trade.")
        request=ticket["request"]
        no_existing_exposure(mt5,request["symbol"])
        if "utc_offset_hours" not in ticket:
            raise DemoError("Refresh the ticket to apply the MT5 server time setting.")
        tick=quote(mt5,request["symbol"],ticket["utc_offset_hours"])
        current=tick.ask if request["type"]==mt5.ORDER_TYPE_BUY else tick.bid
        if abs(current-request["price"])>request["deviation"]*ticket["point"]:
            raise DemoError("Price moved beyond the ticket tolerance. Review a new quote.")
        check=mt5.order_check(request)
        if check is None or check.retcode!=0:
            raise DemoError("IC Markets rejected the final order check. Review a new ticket.")
        checked_account(mt5,ticket["identity"])
        tick=quote(mt5,request["symbol"],ticket["utc_offset_hours"])
        current=tick.ask if request["type"]==mt5.ORDER_TYPE_BUY else tick.bid
        if time.time()-ticket["created"]>30 or abs(current-request["price"])>request["deviation"]*ticket["point"]:
            raise DemoError("Quote changed or expired during validation. Review a new ticket.")
        with closing(sqlite3.connect(ledger,timeout=10)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, state TEXT, result TEXT)")
            try:
                db.execute("INSERT INTO attempts VALUES (?, 'sending', '')",(ticket["id"],))
                db.commit()
            except sqlite3.IntegrityError as exc:
                raise DemoError("This ticket was already attempted. Check MT5; it will not be resent.") from exc
            try:
                result=mt5.order_send(request)
                if result is None:
                    message="No broker response. Check MT5 Trade/History before doing anything else. This ticket will not retry."
                    outcome={"state":"unknown","message":message}
                else:
                    state="filled" if result.retcode==mt5.TRADE_RETCODE_DONE else "partial" if result.retcode==mt5.TRADE_RETCODE_DONE_PARTIAL else "accepted" if result.retcode==mt5.TRADE_RETCODE_PLACED else "rejected"
                    outcome={"state":state,"retcode":result.retcode,"order":result.order,"deal":result.deal,
                             "volume":result.volume,"price":result.price,"message":result.comment}
            except Exception:
                outcome={"state":"unknown","message":"Send outcome unknown. Inspect MT5 Trade/History; this ticket will not retry."}
            import json
            db.execute("UPDATE attempts SET state=?, result=? WHERE id=?",(outcome["state"],json.dumps(outcome),ticket["id"]))
            db.commit()
            return outcome


def render_panel(chart_symbol):
    import streamlit as st
    st.subheader("IC Markets demo trade")
    st.caption("IC Markets demo trading only. This panel uses broker quotes and lots, not Alpaca share quantities. Automatic mode must be started explicitly.")
    with st.expander("Connect IC Markets MetaTrader 5",expanded="mt5_identity" not in st.session_state):
        st.write("Install the IC Markets MT5 Windows desktop terminal and sign in to your DEMO account locally. Keep it open. No password is stored by this dashboard.")
        path=st.text_input("MT5 terminal64.exe path (optional)",key="mt5_path")
        offset=st.selectbox("MT5 server time offset",[2,3,0],format_func=lambda h:{2:"GMT+2",3:"GMT+3",0:"UTC timestamps"}[h],key="mt5_utc_offset")
        st.caption("Select the offset shown by your IC Markets MT5 server. The setting converts quote timestamps to UTC before checking freshness.")
        if st.button("Connect to MT5 demo",key="connect_mt5"):
            try:
                st.session_state.mt5_identity=connect(path.strip())
                st.session_state.pop("mt5_ticket",None)
                st.session_state.pop("mt5_result",None)
            except DemoError as exc:
                st.session_state.pop("mt5_identity",None)
                st.error(str(exc))
    identity=st.session_state.get("mt5_identity")
    if identity is None:
        st.info("Demo trading is unavailable until the installed MT5 terminal is connected.")
        st.button("Place demo trade",disabled=True,key="mt5_unconnected")
        return
    try:
        account,instruments=inspect(identity)
        st.caption(f"DEMO account {account.login} | {account.server} | {account.company} | Account currency: {account.currency}")
        from .auto_demo import render as render_auto_demo
        auto_running=render_auto_demo(identity,instruments,offset)
        names={s.name:s for s in instruments}
        selected=st.selectbox("Exact IC Markets instrument",list(names),index=None,format_func=lambda s:f"{s} - {names[s].description}",key="ic_markets_instrument")
        scenarios={}
        if selected:
            from .xm_chart import render as render_chart_analysis
            scenarios=render_chart_analysis(identity,selected,offset)
        if auto_running:
            st.info('Automatic mode chooses BUY/SELL and submits qualifying demo setups. Stop it to use manual order controls.')
            return
        side=st.selectbox("Manual trade direction",["BUY","SELL"],index=None,key="ic_markets_direction")
        if not selected or not side:
            st.info("Choose the broker instrument and your direction. No symbol mapping is guessed.")
            return
        info=names[selected]
        st.caption(f"Chart asset: {chart_symbol}; IC Markets instrument: {selected}. Verify these represent the asset you intend to trade. Contract size: {info.trade_contract_size}; lots: {info.volume_min} to {info.volume_max}, step {info.volume_step}.")
        lots=st.number_input("IC Markets volume (lots)",min_value=float(info.volume_min),max_value=float(info.volume_max),value=float(info.volume_min),step=float(info.volume_step),format="%.4f",key=f"ic_markets_lots_{selected}")
        automatic=st.checkbox("Use dynamic broker stop and target distances",value=True,key="ic_markets_dynamic")
        if automatic and side not in scenarios:
            st.info("Dynamic distances need current broker candles and quotes. Wait for analysis, or turn off dynamic distances to enter your own manual demo scenario.")
            return
        if automatic:
            st.session_state.ic_markets_tp=max(.1,scenarios[side]['tp_bps'])
            st.session_state.ic_markets_sl=max(.1,scenarios[side]['sl_bps'])
        st.session_state.setdefault('ic_markets_tp',18.0)
        st.session_state.setdefault('ic_markets_sl',12.0)
        tp=st.number_input("Target distance (bps)",min_value=0.1,value=None,key="ic_markets_tp",disabled=automatic)
        sl=st.number_input("Stop distance (bps)",min_value=0.1,value=None,key="ic_markets_sl",disabled=automatic)
        if tp is None or sl is None:
            st.info("Enter both target and stop distances to review a ticket.")
            return
        st.caption("Dynamic distances update from this contract’s candles and spread. BUY/SELL remains your explicit choice; a WAIT result is not an AI trade recommendation.")
        signature=(tuple(identity),selected,side,lots,tp,sl,chart_symbol,offset)
        if st.session_state.get("mt5_signature")!=signature:
            st.session_state.pop("mt5_ticket",None)
            st.session_state.pop("mt5_result",None)
            st.session_state.mt5_signature=signature
        ticket=st.session_state.get("mt5_ticket")
        if ticket is None:
            ticket=preview(identity,selected,side,lots,tp,sl,utc_offset_hours=offset)
            st.session_state.mt5_ticket=ticket
        req=ticket["request"]
        st.write({"Direction":side,"IC Markets symbol":selected,"Lots":lots,"Quoted entry":req["price"],"Stop loss":req["sl"],"Take profit":req["tp"],
                  "Estimated margin":ticket["margin"],"P&L at stop before fees":ticket["loss"],"P&L at target before fees":ticket["gain"],"Currency":ticket["currency"]})
        st.caption("Market execution: actual fill and loss can differ. Quotes expire after 30 seconds; the app never retries a send automatically. Existing positions or pending orders on this instrument block new orders here.")
        def send_clicked():
            try:
                current=(tuple(st.session_state.mt5_identity),st.session_state.ic_markets_instrument,st.session_state.ic_markets_direction,
                         st.session_state[f"ic_markets_lots_{selected}"],st.session_state.ic_markets_tp,st.session_state.ic_markets_sl,chart_symbol,st.session_state.mt5_utc_offset)
                if current!=signature:
                    raise DemoError("Ticket inputs changed. Review the refreshed ticket before submitting.")
                st.session_state.mt5_result=submit(st.session_state.mt5_ticket)
            except DemoError as exc:
                st.session_state.mt5_result={"state":"blocked","message":str(exc)}
        expired=time.time()-ticket["created"]>30
        st.button(f"Place DEMO {side} - {lots:g} lots {selected}",type="primary",on_click=send_clicked,
                  disabled=expired or "mt5_result" in st.session_state,key="place_mt5_demo")
        if expired:
            st.info("The reviewed quote expired. Refresh it to enable the trade button.")
        if "mt5_result" in st.session_state:
            st.write(st.session_state.mt5_result)
        if st.button("New / refreshed ticket",key="refresh_mt5_ticket"):
            st.session_state.pop("mt5_ticket",None)
            st.session_state.pop("mt5_result",None)
            st.rerun(scope="fragment")
    except DemoError as exc:
        st.error(str(exc))
        if st.button("Retry IC Markets quote / connection check",key="retry_mt5_quote"):
            st.session_state.pop("mt5_ticket",None)
            st.rerun(scope="fragment")

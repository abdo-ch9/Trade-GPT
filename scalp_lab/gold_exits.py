"""Timed exits for journaled bot positions. Never closes trades outside the recorded policy."""
import json
import math
import sqlite3
import time
from contextlib import closing
from . import mt5_demo as bridge
from .gold_events import record

HOLD_BARS=15
EXIT_POLICY='signal-close-plus-15m-v1'
# Positions already journaled under the retired clock still close at their stored deadline.
MANAGED_POLICIES={EXIT_POLICY,'signal-close-plus-5m-v1'}


def deadline(signal_open,offset):
    return float(signal_open)+60*(HOLD_BARS+1)-offset*3600


def find_position_id(mt5, order, context):
    def matches(deal):
        return (deal.order == order and deal.symbol == context['symbol']
                and deal.magic == context['magic'] and deal.entry == mt5.DEAL_ENTRY_IN)

    deals = mt5.history_deals_get(ticket=order) or ()
    ids = {deal.position_id for deal in deals if matches(deal) and deal.position_id}
    if not ids:
        orders = mt5.history_orders_get(ticket=order) or ()
        for entry in orders:
            if entry.ticket != order or not entry.position_id:
                continue
            history = mt5.history_deals_get(position=entry.position_id) or ()
            if any(matches(deal) and deal.position_id == entry.position_id for deal in history):
                ids.add(entry.position_id)
    return next(iter(ids)) if len(ids) == 1 else None


def close_request(mt5,position,context,identity):
    from .auto_demo import MAGIC
    from .gold import SYMBOLS
    bridge.checked_account(mt5,identity)
    if (position.symbol not in SYMBOLS or position.symbol!=context['symbol']
        or position.magic!=MAGIC or position.type!=context['type']
        or not math.isclose(position.volume,context['volume'],abs_tol=1e-8)):
        raise bridge.DemoError('Position changed or is not an owned gold position; timed exit needs review.')
    tick=bridge.quote(mt5,position.symbol,context['offset'])
    kind=mt5.ORDER_TYPE_SELL if position.type==mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    request={'action':mt5.TRADE_ACTION_DEAL,'position':position.ticket,'symbol':position.symbol,
             'volume':position.volume,'type':kind,'price':tick.bid if kind==mt5.ORDER_TYPE_SELL else tick.ask,
             'deviation':20,'magic':MAGIC,'comment':'gold-time-exit',
             'type_time':mt5.ORDER_TIME_GTC,'type_filling':context['filling']}
    check=mt5.order_check(request)
    if check is None or check.retcode!=0:
        raise bridge.DemoError('Timed exit broker check failed: '+(check.comment if check else 'no response'))
    bridge.checked_account(mt5,identity)
    # Refresh immediately before creating the one-shot close attempt.
    current=mt5.positions_get(ticket=position.ticket)
    if current is None or len(current)!=1 or current[0].identifier!=position.identifier:
        raise bridge.DemoError('Position no longer matches the timed exit; recheck next cycle.')
    if not math.isclose(current[0].volume,position.volume,abs_tol=1e-8) or current[0].type!=position.type:
        raise bridge.DemoError('Position changed during timed-exit validation.')
    tick=bridge.quote(mt5,position.symbol,context['offset'])
    request['price']=tick.bid if kind==mt5.ORDER_TYPE_SELL else tick.ask
    return request


def manage(identity,db_path,now=None):
    """Caller owns process_guard and bridge.LOCK. Exits continue after entry stop/expiry."""
    now=time.time() if now is None else now
    if not db_path.exists():
        return
    mt5=bridge.api()
    bridge.checked_account(mt5,identity)
    with closing(sqlite3.connect(db_path,timeout=10)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='entries'").fetchone():
            return
        db.execute('CREATE TABLE IF NOT EXISTS exits (token TEXT PRIMARY KEY, state TEXT, detail TEXT)')
        rows=db.execute("SELECT token,detail FROM entries WHERE account=? AND state='filled'",
                        (json.dumps(list(identity)),)).fetchall()
        issues = []
        for token,detail in rows:
            data=json.loads(detail)
            context=data.get('execution_context',{})
            if context.get('exit_policy') not in MANAGED_POLICIES:
                continue
            previous=db.execute('SELECT state,detail FROM exits WHERE token=?',(token,)).fetchone()
            if previous and previous[0]=='closed':
                continue
            order=data.get('order')
            position_id = data.get('position_id')
            if not position_id and order:
                position_id = find_position_id(mt5, order, context)
                if position_id:
                    data['position_id'] = position_id
                    db.execute('UPDATE entries SET detail=? WHERE token=?', (json.dumps(data), token))
                    db.commit()
            if not position_id:
                if now >= context['deadline_utc']:
                    issues.append(f"{context['symbol']} order {order or 'unknown'}: MT5 could not verify the position for its timed exit.")
                continue
            positions=mt5.positions_get(symbol=context['symbol'])
            if positions is None:
                issues.append(f"{context['symbol']} order {order}: MT5 position lookup unavailable.")
                continue
            owned=[p for p in positions if p.identifier==position_id]
            if not owned:
                deals=mt5.history_deals_get(position=position_id)
                if not deals or not any(d.entry in (mt5.DEAL_ENTRY_OUT,mt5.DEAL_ENTRY_OUT_BY) for d in deals):
                    issues.append(f"{context['symbol']} order {order}: MT5 close history is unavailable.")
                    continue
                summary={field:sum(float(getattr(d,field,0)) for d in deals)
                         for field in ('profit','commission','swap','fee')}
                summary['net_pnl']=sum(summary.values())
                summary.update(symbol=context['symbol'],position_id=position_id,
                               close_reason='Timed exit' if previous else 'Broker stop/target or external close')
                db.execute('INSERT OR REPLACE INTO exits VALUES (?,?,?)',(token,'closed',json.dumps(summary)))
                db.commit()
                record('closed',f"{context['symbol']} position closed; net P&L {summary['net_pnl']:.2f} in account currency",summary,key=token+':closed')
                continue
            if previous:
                # sending/unknown/partial/rejected outcomes require review, never a blind retry.
                previous_detail=json.loads(previous[1])
                if previous[0]=='sent' and now-previous_detail.get('sent_at',now)>30:
                    db.execute('UPDATE exits SET state=? WHERE token=?',('review_required',token))
                    db.commit()
                    record('error','Timed exit reported success but position still exists; inspect MT5.',key=token+':still-open')
                    from .auto_demo import stop
                    stop('Timed exit position still open; manual review required.')
                continue
            if now<context['deadline_utc']:
                continue
            try:
                position_history=mt5.history_deals_get(position=position_id)
                if position_history is None or any(d.entry in (mt5.DEAL_ENTRY_IN,mt5.DEAL_ENTRY_INOUT)
                                                  and d.order!=order for d in position_history):
                    raise bridge.DemoError('Position contains another entry; timed exit requires manual review.')
                request=close_request(mt5,owned[0],context,identity)
            except bridge.DemoError as exc:
                record('exit_delayed',str(exc),{'symbol':context['symbol']},key=token+':preflight:'+str(exc))
                continue
            db.execute('INSERT INTO exits VALUES (?,?,?)',(token,'sending',json.dumps(request)))
            db.commit()
            try:
                response=mt5.order_send(request)
                state=('sent' if response and response.retcode==mt5.TRADE_RETCODE_DONE else 'review_required')
                outcome={'state':state,'retcode':response.retcode if response else None,
                         'sent_at':time.time(),
                         'message':response.comment if response else 'No broker response; inspect MT5. No retry.',
                         'requested_price':request['price'],'fill_price':response.price if response else None,
                         'late_seconds':max(0,time.time()-context['deadline_utc'])}
            except Exception as exc:
                state='review_required'
                outcome={'state':state,'message':str(exc)}
            db.execute('UPDATE exits SET state=?,detail=? WHERE token=?',(state,json.dumps(outcome),token))
            db.commit()
            record('exit_sent' if state=='sent' else 'error',f"{context['symbol']} timed exit: {outcome['message']}",outcome,key=token+':exit')
            if state!='sent':
                from .auto_demo import stop
                stop('Timed exit needs review in MT5; no automatic retry.')
        if issues:
            raise bridge.DemoError(' '.join(issues))


def unresolved(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='exits'").fetchone():
        return False
    return bool(db.execute("SELECT 1 FROM exits WHERE state IN ('sending','review_required') LIMIT 1").fetchone())

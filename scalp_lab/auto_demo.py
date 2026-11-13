"""Bounded Exness demo automation, evaluated by dashboard refreshes; no live accounts."""
import json
import math
import sqlite3
import threading
import time
import traceback
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from . import mt5_demo as bridge
from .gold import ENGINE, eligible_symbol
from .xm_chart import news_gate
from .gold_events import record
from .gold_storage import write_json

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'xm_auto_demo.json'
JOURNAL=ROOT/'xm_auto_demo.sqlite3'
STATUS_FILE=ROOT/'xm_auto_demo_status.json'
LOCK_FILE=ROOT/'xm_auto_demo.lock'
_PROCESS_GUARD_LOCK=threading.RLock()


def _ensure_lock_file():
    try:
        if not LOCK_FILE.exists() or LOCK_FILE.stat().st_size == 0:
            with open(LOCK_FILE, 'a+b') as f:
                f.seek(0, 2)
                if f.tell() == 0:
                    f.write(b'0')
                    f.flush()
    except OSError:
        pass


_ensure_lock_file()
MAGIC=641105
try:
    STATUS=json.loads(STATUS_FILE.read_text(encoding='utf-8'))
except (OSError,ValueError):
    STATUS={}
CURSOR=0
LAST_SCAN=0


_settings_cache=(0.0,{})

def settings(ttl=0.0):
    """Permission reads are fresh by default; callers may opt into display caching."""
    global _settings_cache
    now=time.time()
    if now-_settings_cache[0]<ttl:
        return _settings_cache[1]
    try:
        result=json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        result={'enabled':False}
    _settings_cache=(now,result)
    return result


def save(config):
    global _settings_cache
    write_json(CONFIG,config)
    _settings_cache=(0.0,{})  # Invalidate cache so next settings() call reads the new file


def save_status():
    write_json(STATUS_FILE,STATUS)


def stop(reason='Stopped by user'):
    with bridge.LOCK:
        config=settings()
        config.update(enabled=False,stop_reason=reason)
        save(config)


def eligible(instruments):
    return [s.name for s in instruments if eligible_symbol(s)
            and s.volume_min<=.01<=s.volume_max and s.volume_step>0
            and abs(.01/s.volume_step-round(.01/s.volume_step))<1e-8]


def daily_budget(config,baseline,currency):
    euro_amount = config.get('daily_loss_eur')
    if euro_amount is not None:
        if (isinstance(euro_amount, bool) or not isinstance(euro_amount, (int, float))
                or not math.isfinite(euro_amount) or euro_amount <= 0):
            raise bridge.DemoError('Invalid fixed EUR daily loss budget.')
        if currency == 'EUR':
            return float(euro_amount)
        if currency != 'USD':
            raise bridge.DemoError('The EUR daily loss budget supports EUR or USD accounts.')
        with bridge.LOCK:
            mt5 = bridge.api()
            bridge.checked_account(mt5, config.get('identity'))
            gold_symbol = next(iter(config.get('symbols', [])), '')
            suffix = gold_symbol[len('XAUUSD'):] if gold_symbol.startswith('XAUUSD') else ''
            symbols = ('EURUSD' + suffix, 'EURUSD') if suffix in bridge.SYMBOL_SUFFIXES and suffix else ('EURUSD',)
            for symbol in symbols:
                info = mt5.symbol_info(symbol)
                if info is None or info.currency_base != 'EUR' or info.currency_profit != 'USD':
                    continue
                if mt5.symbol_select(symbol, True):
                    tick = bridge.quote(mt5, symbol, config.get('offset', bridge.UTC_OFFSET_HOURS))
                    return float(euro_amount)*tick.bid
            raise bridge.DemoError('A verified EUR/USD quote is required for the EUR daily budget.')

    amount=config.get('daily_loss_usd')
    if amount is not None:
        if currency!='USD':
            raise bridge.DemoError('The fixed USD loss budget requires a USD account.')
        if isinstance(amount,bool) or not isinstance(amount,(int,float)) or not math.isfinite(amount) or amount<=0:
            raise bridge.DemoError('Invalid fixed daily loss budget.')
        return float(amount)
    return baseline*config.get('daily_loss_fraction',.01)


def record_day(identity,equity,db_path=JOURNAL):
    if not math.isfinite(equity) or equity<=0:
        raise bridge.DemoError('Invalid account equity.')
    with closing(sqlite3.connect(db_path,timeout=10)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS days (account TEXT, day TEXT, equity REAL, PRIMARY KEY(account,day))')
        db.execute('INSERT OR IGNORE INTO days VALUES (?,?,?)',
                   (json.dumps(list(identity)),datetime.now(timezone.utc).strftime('%Y-%m-%d'),equity))
        db.commit()


def bind_stopped_session(identity, symbols, offset):
    """Update broker context without arming entries or changing research consent."""
    with process_guard(), bridge.LOCK:
        config = settings()
        if config.get('enabled'):
            raise bridge.DemoError('Stop automation before changing its account or instrument.')
        bridge.checked_account(bridge.api(), identity)
        allowed = eligible(bridge.api().symbols_get() or [])
        if len(symbols) != 1 or symbols[0] not in allowed:
            raise bridge.DemoError('Choose exactly one verified gold instrument.')
        if offset not in (0, 2, 3):
            raise bridge.DemoError('Unsupported MT5 server time offset.')
        config = {**config, 'enabled': False, 'identity': list(identity),
                  'symbols': list(symbols), 'offset': offset, 'engine': ENGINE,
                  'expires': 0, 'run_id': uuid.uuid4().hex,
                  'stop_reason': 'Account connection updated. Press Start to enable entries.'}
        save(config)
        return config


def arm(identity, symbols, offset, *, override_live_validation=False):
    from .xm_news import connection_status
    connected,reason=connection_status()
    if not connected:
        raise bridge.DemoError(reason)
    with bridge.LOCK:
        mt5=bridge.api()
        account=bridge.checked_account(mt5,identity)
        if not symbols:
            raise bridge.DemoError('No gold instruments support 0.01 lot.')
        allowed=eligible(bridge.api().symbols_get() or [])
        if any(s not in allowed for s in symbols) or len(symbols)!=1:
            raise bridge.DemoError('Choose exactly one verified gold instrument.')
        live = account.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL
        if override_live_validation and not live:
            raise bridge.DemoError('The live validation override requires an Exness real account.')
        if live and not override_live_validation:
            from .gold import validation
            valid, reason = validation(symbols[0], broker_exit=True)
            if not valid:
                raise bridge.DemoError(reason)
        from .gold_exits import HOLD_BARS
        config={'enabled':True,'identity':list(identity),'symbols':list(symbols),'offset':offset,
                'engine':ENGINE,
                'allow_unvalidated_live':override_live_validation is True,
                'allow_unvalidated_demo':settings().get('allow_unvalidated_demo') is True,
                'exclude_tesla_stop_risk':settings().get('exclude_tesla_stop_risk') is True,
                'daily_loss_usd':settings().get('daily_loss_usd'),
                'daily_loss_eur':settings().get('daily_loss_eur'),
                'lots':.01,'max_entries':5,'daily_loss_fraction':.01,'horizon':HOLD_BARS,
                'expires':time.time()+8*3600,'run_id':uuid.uuid4().hex}
        record_day(identity,account.equity)
        save(config)
        return config


@contextmanager
def process_guard():
    """Serialize automated execution across tabs and server processes."""
    with _PROCESS_GUARD_LOCK:
        _ensure_lock_file()
        handle = None
        for attempt in range(10):
            try:
                handle = open(LOCK_FILE, 'a+b')
                break
            except OSError:
                time.sleep(0.05 * (attempt + 1))
        else:
            raise bridge.DemoError('Cannot access automation lock file.')

        import msvcrt
        acquired = False
        try:
            for _ in range(40):
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    time.sleep(0.05)
            if not acquired:
                raise bridge.DemoError('Another automation scan is running.')
            yield
        finally:
            if acquired:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            try:
                handle.close()
            except OSError:
                pass


def portfolio_stop_risk(mt5,positions,offset,exclude_tesla=False):
    """Current quote-to-stop loss estimate across open positions in account currency."""
    total=0.0
    for position in positions:
        # Explicit demo-only user preference; never exclude other instruments.
        if exclude_tesla and position.symbol=='Tesla':
            continue
        if not position.sl or not math.isfinite(position.sl):
            raise bridge.DemoError(f"Automatic entries paused: existing {position.symbol} position has no stop-loss.")
        try:
            tick=bridge.quote(mt5,position.symbol,offset)
        except bridge.DemoError as exc:
            raise bridge.DemoError(
                f'Account risk check blocked: an existing {position.symbol} position '
                f'({position.volume:g} lots) has no usable fresh quote. '
                'The GOLD signal is separate; this quote is needed to estimate the remaining '
                'loss to the existing position’s stop within the shared daily budget. '
                'Wait for fresh prices or manage the existing position in MT5. '
                'No position was changed. Quote details: '+str(exc)) from exc
        exit_now=tick.bid if position.type==mt5.ORDER_TYPE_BUY else tick.ask
        pnl=mt5.order_calc_profit(position.type,position.symbol,position.volume,exit_now,position.sl)
        if pnl is None or not math.isfinite(pnl):
            raise bridge.DemoError(f"Cannot estimate stop risk for existing {position.symbol} position.")
        total+=max(0.0,-pnl)
    return total


def execute(config,symbol,result,db_path=JOURNAL,manual=False):
    """Called under process_guard and bridge.LOCK. Persist intent BEFORE sending."""
    mt5=bridge.api()
    account=bridge.checked_account(mt5,config['identity'])
    demo = account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    from .gold import SYMBOLS
    if symbol not in SYMBOLS:
        raise bridge.DemoError('Currency trading is retired. Only gold entries are supported.')
    if config.get('lots')!=.01 or symbol not in config['symbols']:
        raise bridge.DemoError('Unapproved instrument or size.')
    if manual and config.get('enabled'):
        raise bridge.DemoError('Stop automatic trading before using a row trade button.')
    if not manual and (time.time()>config['expires'] or not config['enabled']):
        raise bridge.DemoError('Automation is disabled or its eight-hour session expired.')
    if result.get('action') not in ('BUY setup','SELL setup'):
        return {'state':'waiting','message':result.get('action','No setup')}
    if result.get('engine') != ENGINE:
        raise bridge.DemoError('Only the chart + required AI news engine may submit automatic entries.')
    from .gold import execution_validation
    validated,validation_reason=execution_validation(symbol,config,demo=demo,identity=None if manual else config['identity'])
    if not validated:
        raise bridge.DemoError(validation_reason)
    news_block,news_reason=news_gate(result.get('news',{}),result['action'].split()[0],time.time())
    if news_block:
        raise bridge.DemoError(news_reason)
    if not 0<=time.time()-result.get('observed_at',0)<=15:
        raise bridge.DemoError('Analysis expired; wait for a new scan.')
    positions,orders=mt5.positions_get(),mt5.orders_get()
    if positions is None or orders is None:
        raise bridge.DemoError('Cannot verify account exposure.')
    if any(p.symbol==symbol for p in positions) or any(o.symbol==symbol for o in orders):
        return {'state':'waiting','message':f'An existing {symbol} position or pending order blocks duplicate exposure.'}
    if orders:
        return {'state':'waiting','message':'A pending order exists on the account; resolve it before automatic entry.'}
    side=result['action'].split()[0]
    scenario=result['scenarios'][side]
    bar=float(result['frame'].iloc[-1].time)
    if not 0<=time.time()+config['offset']*3600-(bar+60)<=90:
        raise bridge.DemoError('Signal candle expired.')
    day=datetime.now(timezone.utc).strftime('%Y-%m-%d')
    account_key=json.dumps(config['identity'])
    # One attempt per instrument/candle, even if direction changes or a scan restarts.
    token=f'{account_key}:{symbol}:{bar}'
    with closing(sqlite3.connect(db_path,timeout=10)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS days (account TEXT, day TEXT, equity REAL, PRIMARY KEY(account,day))')
        db.execute('CREATE TABLE IF NOT EXISTS entries (token TEXT PRIMARY KEY, account TEXT, day TEXT, time REAL, state TEXT, detail TEXT)')
        if not math.isfinite(account.equity) or account.equity<=0:
            raise bridge.DemoError('Invalid account equity.')
        db.execute('INSERT OR IGNORE INTO days VALUES (?,?,?)',(account_key,day,account.equity))
        db.commit()
        baseline=db.execute('SELECT equity FROM days WHERE account=? AND day=?',(account_key,day)).fetchone()[0]
        used=db.execute('SELECT COUNT(*) FROM entries WHERE account=? AND day=?',(account_key,day)).fetchone()[0]
        unresolved=db.execute("SELECT COUNT(*) FROM entries WHERE account=? AND state IN ('sending','unknown','partial','accepted')",(account_key,)).fetchone()[0]
        if unresolved:
            raise bridge.DemoError('Unresolved automatic order. Inspect MT5 and the journal before resuming; no retry is allowed.')
        if used>=config['max_entries']:
            raise bridge.DemoError('Five automatic entry attempts reached today (UTC).')
        drawdown=max(0.0,baseline-account.equity)
        reserved=portfolio_stop_risk(mt5,positions,config['offset'],demo and config.get('exclude_tesla_stop_risk') is True)
        remaining=daily_budget(config,baseline,account.currency)-drawdown-reserved
        if remaining<=0:
            raise bridge.DemoError('Daily equity loss limit reached. New entries are stopped.')
        if db.execute('SELECT 1 FROM entries WHERE token=?',(token,)).fetchone():
            return {'state':'waiting','message':'This signal candle was already attempted.'}
        ticket=bridge.preview(config['identity'],symbol,side,.01,scenario['tp_bps'],scenario['sl_bps'],utc_offset_hours=config['offset'])
        # Reserve 20% above estimated stop loss for fees; gaps can still exceed it.
        if ticket['loss'] is None or not math.isfinite(ticket['loss']) or ticket['loss']>=0 or abs(ticket['loss'])*1.2>remaining:
            raise bridge.DemoError('Estimated stop loss exceeds the remaining daily budget.')
        ticket['request']['magic']=MAGIC
        current=settings()
        if bool(current.get('enabled')) != (not manual) or current.get('run_id')!=config['run_id']:
            raise bridge.DemoError('Automation was stopped or reconfigured.')
        permitted,reason=execution_validation(symbol,current,demo=demo,identity=None if manual else config['identity'])
        if not permitted:
            raise bridge.DemoError(reason)
        from .gold_worker import healthy as worker_healthy
        if not worker_healthy():
            raise bridge.DemoError('Background exit watchdog is not healthy; new entries are blocked.')
        # Recheck account-wide exposure directly before reserving the order.
        account=bridge.checked_account(mt5,config['identity'])
        if not math.isfinite(account.equity) or account.equity<=0:
            raise bridge.DemoError('Invalid current account equity before submission.')
        current_positions,current_orders=mt5.positions_get(),mt5.orders_get()
        if current_positions is None or current_orders is None:
            raise bridge.DemoError('Cannot verify portfolio exposure immediately before submission.')
        if any(p.symbol==symbol for p in current_positions) or any(o.symbol==symbol for o in current_orders) or current_orders:
            raise bridge.DemoError('Exposure changed before submission.')
        additional_reserved=portfolio_stop_risk(mt5,current_positions,config['offset'],demo and current.get('exclude_tesla_stop_risk') is True)
        if daily_budget(current,baseline,account.currency)-max(0.0,baseline-account.equity)-additional_reserved-abs(ticket['loss'])*1.2<0:
            raise bridge.DemoError('Combined account stop risk exceeds the remaining daily loss budget.')
        news_block,news_reason=news_gate(result.get('news',{}),side,time.time())
        if news_block:
            raise bridge.DemoError(news_reason)
        from .gold_exits import BROKER_EXIT_POLICY,unresolved
        if unresolved(db):
            raise bridge.DemoError('An unresolved timed exit requires review before new entries.')
        request=ticket['request']
        context={'exit_policy':BROKER_EXIT_POLICY,
                 'symbol':symbol,'type':request.get('type'),'volume':.01,'magic':MAGIC,
                 'offset':config['offset'],'filling':request.get('type_filling'),
                 'entry_request':request,'setup':result.get('setup'),
                 'signal_time':bar,'equity_at_send':account.equity,'estimated_loss':ticket['loss'],
                 'spread_price':result.get('spread_price'),'point':ticket.get('point')}
        db.execute('INSERT INTO entries VALUES (?,?,?,?,?,?)',(token,account_key,day,time.time(),'sending',json.dumps({'execution_context':context})))
        db.commit()
        started=time.time()
        try:
            outcome=bridge.submit(ticket)
        except bridge.EntryQuoteMoved as exc:
            outcome={'state':'skipped','message':str(exc)}
        except Exception as exc:
            # Conservatively ambiguous: never automatically retry this attempt.
            outcome={'state':'unknown','message':str(exc)}
        outcome={**outcome,'execution_context':context,'latency_seconds':time.time()-started}
        if outcome.get('price') and request.get('price'):
            outcome['adverse_slippage_price']=(outcome['price']-request['price'])*(1 if side=='BUY' else -1)
        db.execute('UPDATE entries SET state=?,detail=? WHERE token=?',(outcome['state'],json.dumps(outcome),token))
        db.commit()
        record('entry_'+outcome['state'],f"{symbol} {side}: {outcome.get('message',outcome['state'])}",outcome,key=token+':entry')
        if outcome['state'] not in ('filled','skipped'):
            stop('Automatic order needs review: '+outcome.get('message',outcome['state']))
        return outcome


def trade_row(identity,symbol,offset,expected_side):
    """User-clicked entry using the same journal, risk limits and broker checks."""
    config=settings()
    if config.get('enabled'):
        raise bridge.DemoError('Stop automatic trading before using a row trade button.')
    if tuple(config.get('identity',[]))!=tuple(identity) or config.get('offset')!=offset:
        raise bridge.DemoError('Account or time setting changed. Start and stop a new session to configure these row buttons.')
    if expected_side not in ('BUY','SELL') or symbol not in config.get('symbols',[]):
        raise bridge.DemoError('No approved directional setup for this row.')
    from .gold import snapshot
    with process_guard():
        result,_=snapshot(identity,symbol,offset)
        if result.get('action')!=expected_side+' setup':
            raise bridge.DemoError('Setup changed; no order sent. Current decision: '+result.get('action','Unavailable'))
        with bridge.LOCK:
            return execute(config,symbol,result,manual=True)


def render_trade_rows(identity,offset,current_status,enabled,*,mode):
    import streamlit as st
    import pandas as pd
    from .gold_decisions import recent
    history=recent(identity,list(current_status))
    st.write('**Saved BUY / SELL decisions**')
    st.caption('Saved decisions remain here after “No setup”, page refreshes and restarts. These are historical proposals, not confirmed trades. Repeated scans of the same candle and decision keep the first recorded levels. Showing the latest 200; older records remain stored.')
    if history:
        st.dataframe(history,hide_index=True,width='stretch',
                     column_config={name:st.column_config.NumberColumn(name,format='%.5f')
                                    for name in ('Indicative entry','Take profit','Stop loss')})
        st.download_button('Download saved decisions',pd.DataFrame(history).to_csv(index=False),
                           'gold_saved_decisions.csv',mime='text/csv',key='saved_gold_decisions')
    else:
        st.caption('The next directional setup will be saved here automatically.')
    st.write(f'**Trade a table setup · Exness {mode} · 0.01 lot**')
    st.caption(f'Each button submits one {mode} market order after refreshing the chart, news and quote. Entry and dynamic levels may change. The same daily budget, five-attempt limit and duplicate-order protection apply.')
    if enabled:
        st.info('Stop automatic trading to enable these manual trade buttons.')
    headers=st.columns([2,1,1.4,1.4,1.4,1,2])
    for col,label in zip(headers,['Pair / direction','Lots','Entry','Take profit','Stop loss','Risk %','Exness action']):
        col.write('**'+label+'**')
    for symbol,row in current_status.items():
        cols=st.columns([2,1,1.4,1.4,1.4,1,2])
        side=row.get('chart_signal')
        cols[0].write(f"{symbol} · {side or '—'}")
        for col,key in zip(cols[1:6],['position_lots','entry','take_profit','stop_loss','risk_pct']):
            value=row.get(key)
            col.write('—' if value is None else f'{value:.5f}' if key in ('entry','take_profit','stop_loss') else f'{value:.2f}')
        qualifies=row.get('decision') in ('BUY setup','SELL setup') and side in ('BUY','SELL')
        if cols[6].button(f'{side} 0.01 {mode}' if qualifies else 'No setup',
                          key='row_trade_'+symbol,disabled=enabled or not qualifies,
                          help=f'Refreshes and rechecks this setup before submitting to your Exness {mode} account.'):
            try:
                with st.spinner(f'Rechecking {symbol} before submission…'):
                    outcome=trade_row(identity,symbol,offset,side)
                st.session_state['xm_row_trade_result']={'symbol':symbol,**outcome}
            except bridge.DemoError as exc:
                st.session_state['xm_row_trade_result']={'symbol':symbol,'state':'blocked','message':str(exc)}
    outcome=st.session_state.get('xm_row_trade_result')
    if outcome:
        message=f"{outcome['symbol']} · {outcome['state']}: {outcome.get('message','')}"
        (st.success if outcome['state']=='filled' else st.warning)(message)


def scan(identity,offset):
    global CURSOR,LAST_SCAN
    config=settings()
    if not config.get('enabled') or time.time()-LAST_SCAN<5:
        return
    if config.get('engine')!=ENGINE:
        config['engine']=ENGINE
        save(config)
    if tuple(config['identity'])!=tuple(identity) or config['offset']!=offset:
        stop('Account or server-time setting changed. Start a new session.')
        return
    if time.time()>config['expires']:
        stop('Eight-hour automation session expired.')
        return
    # The worker is the sole scanner. Do not hold the execution lock during slow AI news.
    LAST_SCAN=time.time()
    with bridge.LOCK:
        mt5=bridge.api()
        account=bridge.checked_account(mt5,identity)
        record_day(identity,account.equity)
        positions,orders=mt5.positions_get(),mt5.orders_get()
        if positions is None or orders is None:
            raise bridge.DemoError('Cannot read current account exposure.')
        if orders:
            pending=', '.join(sorted({o.symbol for o in orders}))
            STATUS['Account']={'state':'waiting','message':f'Pending order on {pending}: new automatic entries are blocked. Chart and news scanning continues. Manage pending orders in MT5.'}
            STATUS['Account']['time']=datetime.now(timezone.utc).isoformat()
        else:
            STATUS.pop('Account',None)
    symbol=config['symbols'][CURSOR%len(config['symbols'])]
    CURSOR+=1
    try:
        from .gold import snapshot
        result,fitted=snapshot(identity,symbol,offset,config['horizon'])
        from .gold_snapshot import publish
        publish(identity, symbol, offset, result)
        from .gold_decisions import save as save_decision
        save_decision(identity,symbol,result)
        with process_guard(), bridge.LOCK:
            try:
                outcome=execute(config,symbol,result)
            except bridge.DemoError as exc:
                outcome={'state':'blocked','message':str(exc)}
        save_decision(identity,symbol,result,outcome=outcome)
        scenario=result.get('scenarios',{}).get(result.get('chart_signal'),{})
        STATUS[symbol]={'time':datetime.now(timezone.utc).isoformat(),**outcome,
                        'position_lots':scenario.get('lots'),
                        'entry':scenario.get('entry'),
                        'take_profit':scenario.get('tp'),
                        'stop_loss':scenario.get('sl'),
                        'risk_pct':scenario.get('risk_pct'),
                        'risk_amount':scenario.get('risk_amount'),
                        'account_currency':scenario.get('currency'),
                        'engine':ENGINE,
                        'decision':result.get('action'),'bias':result.get('bias'),
                        'chart_signal':result.get('chart_signal'),
                        'chart_score':result.get('chart_score'),
                        'news_status':result.get('news',{}).get('status'),
                        'news_direction':result.get('news',{}).get('direction'),
                        'news_reason':result.get('news',{}).get('reason'),
                        'news_checked_at':result.get('news',{}).get('checked_at'),
                        'news_sources':[a['url'] for a in result.get('news',{}).get('articles',[])],
                        'reasons':' '.join(result.get('reasons',[]))}
        save_status()
        signature=f"{symbol}:{outcome['state']}:{outcome.get('message','')}:{int(time.time()//300)}"
        record('decision',f"{symbol}: {outcome.get('message',result.get('action'))}",
               {'symbol':symbol,'action':result.get('action'),'direction':result.get('chart_signal'),
                'entry':scenario.get('entry'),'sl':scenario.get('sl'),'tp':scenario.get('tp'),
                'setup':result.get('setup'),'checks':result.get('checks',[]),'reasons':result.get('reasons',[])},key=signature)
    except bridge.DemoError as exc:
        STATUS[symbol]={'state':'blocked','message':str(exc),'engine':ENGINE,
                        'time':datetime.now(timezone.utc).isoformat()}
        save_status()
        record('blocked',f'{symbol}: {exc}',key=f'{symbol}:blocked:{exc}:{int(time.time()//300)}')
    except Exception as exc:
        stop('Unexpected automation failure; inspect before restarting.')
        STATUS[symbol]={'state':'error','message':str(exc),'engine':ENGINE,
                        'time':datetime.now(timezone.utc).isoformat(),
                        'traceback':traceback.format_exc(limit=8)}
        save_status()
        record('error',str(exc),{'traceback':traceback.format_exc(limit=8)})


def render(identity,instruments,offset,*,mode='demo'):
    global STATUS
    import streamlit as st
    st.markdown(f'### Automatic Exness {mode} trading')
    from .xm_news import connection_status
    news_connected,news_connection_reason=connection_status()
    st.caption('Gold M1/M5/M15 structure rules, cost-aware holdout evaluation and required AI news.')
    if not news_connected:
        st.info('AI NEWS NOT CONNECTED: '+news_connection_reason+' AI news is required for every entry.')
    else:
        st.caption('News service: '+news_connection_reason)
    symbols=eligible(instruments)
    config = settings()
    context_changed = (tuple(config.get('identity', [])) != tuple(identity)
                       or config.get('symbols') != symbols or config.get('offset') != offset)
    if context_changed and not config.get('enabled'):
        st.info('Saved automation belongs to a different account, instrument or timestamp convention. Update the stopped session before starting.')
        if st.button(f'Use connected {mode} account and gold instrument', key='bind_gold_demo', disabled=len(symbols) != 1):
            bind_stopped_session(identity, symbols, offset)
            st.rerun()
    from .gold import execution_validation
    trade_validated=bool(symbols) and all(execution_validation(s,demo=mode=='demo')[0] for s in symbols)
    if mode=='demo' and settings().get('allow_unvalidated_demo') is True:
        st.warning('User-approved demo research: historical tests are advisory. New bot positions use broker SL/TP with no timed close. News and account risk limits still apply.')
    if mode=='demo' and settings().get('exclude_tesla_stop_risk') is True:
        st.warning('Tesla is excluded from open-position stop-risk estimates at your request. Its account-equity gains/losses still count. The daily budget does not cover Tesla’s additional loss to its stop.')
    if mode=='real' and config.get('allow_unvalidated_live') is True and config.get('enabled'):
        st.warning('Historical validation is overridden for the active real-money automation session.')
    elif not trade_validated:
        st.info('Research mode: gold analysis continues below the chart. Automatic trading is unavailable until historical evidence and matching live exit management are validated.')
    budget_label=(f"${settings()['daily_loss_usd']:.2f} daily loss budget" if settings().get('daily_loss_usd') is not None else '1% daily equity budget')
    if settings().get('daily_loss_eur') is not None:
        budget_label = f"€{settings()['daily_loss_eur']:.2f} daily loss budget (converted using fresh EURUSD bid for USD accounts)"
    st.caption(f'{len(symbols)} Exness gold instruments eligible for exactly 0.01 lot. Daily equity loss plus reserved open-stop risk and a 20% cost reserve for the new trade must fit the {budget_label}. Five entry attempts per UTC day. Stops/targets attached to every entry.')
    st.caption('Background worker runs with the browser closed, for up to eight hours of entries per start. Stop blocks new entries; broker stops and targets remain active. Keep this computer and MT5 running. Broker stops remain in place if the worker is offline; timed exits can be delayed by downtime or unavailable quotes.')
    config=settings()
    left,right=st.columns(2)
    if left.button(f'Start automatic {mode.upper()} trading',disabled=config.get('enabled',False) or not news_connected or not trade_validated,key='start_auto_demo'):
        arm(identity,symbols,offset)
    if right.button('Stop automatic trading',key='stop_auto_demo'):
        stop()
    config=settings()
    st.write('**Automation: '+('RUNNING**' if config.get('enabled') else 'STOPPED**'))
    if config.get('stop_reason'):
        st.info(config['stop_reason'])
    remaining=config.get('expires',0)-time.time()
    if config.get('enabled') and remaining>0:
        st.caption(f'Session expires in {remaining/3600:.1f}h ({datetime.fromtimestamp(config["expires"], timezone.utc).strftime("%H:%M UTC")})')
    with st.expander('Approved gold instrument'):
        st.write(', '.join(config.get('symbols',symbols)))
    from .gold_worker import ensure_running,status as worker_status,healthy as worker_healthy
    ensure_running()
    heartbeat=worker_status()
    healthy=worker_healthy(heartbeat)
    st.caption('Background worker: '+('connected' if healthy else 'starting / unavailable'))
    st.caption('Scanner: '+heartbeat.get('scanner','not started'))
    if config.get('enabled') and not heartbeat.get('scanner_alive',False):
        st.error('The scanning thread is not running. New signals are unavailable; check persistent events.')
    if heartbeat.get('exit_error'):
        st.warning('Exit watchdog: '+heartbeat['exit_error'])
    try:
        persisted=json.loads(STATUS_FILE.read_text())
        if config.get('enabled'):
            STATUS=persisted
    except (OSError,ValueError):
        pass
    from .gold_events import recent
    events=recent()
    from .gold_events import latest_trade_notice
    latest = latest_trade_notice(events)
    if latest:
        if st.session_state.get('gold_last_notice') != latest['id']:
            st.toast(latest['message'])
            st.session_state.gold_last_notice = latest['id']
        event_time = datetime.fromtimestamp(latest['time'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        st.info(f"Recent trade activity ({event_time}): {latest['message']}")
    else:
        st.caption('No recent trade activity. Current connection and watchdog status is shown above; previous messages are in event history.')
    with st.expander('Persistent events and execution measurements'):
        if events:
            st.dataframe(events,hide_index=True,width='stretch')
            st.download_button('Download event log',json.dumps(events,indent=2),'gold_events.json')
        else:
            st.caption('No recorded events yet.')
    if config.get('enabled') and STATUS.get('Account',{}).get('message'):
        st.warning(STATUS['Account']['message'])
    approved=config.get('symbols',symbols)
    current_status={s:v for s,v in STATUS.items() if v.get('engine')==ENGINE and s in approved}
    if current_status:
        rows=[v for v in current_status.values() if v.get('decision')]
        if rows:
            ready=sum(v.get('decision') in ('BUY setup','SELL setup') for v in rows)
            cols=st.columns(3)
            cols[0].metric('Gold instruments analyzed',f'{len(rows)} / {len(approved)}')
            cols[1].metric('Qualified setups',ready)
            cols[2].metric('Most recent scan',max(current_status.values(),key=lambda r:r.get('time','')).get('time','—'))
            st.caption('This counts distinct pairs with a chart decision, not scan cycles. The count can stay constant while rows update. Pairs with data or connection errors appear as blocked in the table.')
        trade_columns={'position_lots':'Position (lots)','entry':'Indicative entry',
                       'take_profit':'Take profit','stop_loss':'Stop loss',
                       'risk_pct':'Risk (% equity)','risk_amount':'Estimated loss at stop',
                       'account_currency':'Account currency'}
        st.dataframe([{'Instrument':s,'Decision':v.get('decision'),'Direction':v.get('chart_signal'),
                       **{label:v.get(key) for key,label in trade_columns.items()},
                       **{k:value for k,value in v.items() if k not in trade_columns
                          and k not in ('decision','chart_signal')}}
                      for s,v in current_status.items()],hide_index=True,width='stretch',
                     column_config={name:st.column_config.NumberColumn(name,format='%.5f')
                                    for name in ('Indicative entry','Take profit','Stop loss')})
        st.caption('Proposed 0.01-lot scenarios, not confirmed fills. Risk is estimated loss at stop / equity × 100, before fees and slippage. Levels can appear for a directional bias even when the decision blocks trading. Older rows populate on their next scan; blanks mean unavailable.')
        render_trade_rows(identity,offset,current_status,settings().get('enabled',False),mode=mode)
        errors=[(s,v) for s,v in current_status.items() if v.get('state')=='error' and v.get('traceback')]
        if errors:
            with st.expander('Automation error details'):
                for symbol,error in errors:
                    st.markdown(f'**{symbol} · {error.get("time","unknown time")}**')
                    st.code(error['traceback'],language='text')
    return settings().get('enabled',False)

"""Streamlit controls and status views for IC Markets demo automation."""
import json
import time
from datetime import datetime, timezone

from . import auto_demo as auto, mt5_demo as bridge


def render_trade_rows(identity,offset,current_status,enabled):
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
    st.write('**Trade a table setup · IC Markets demo · 0.01 lot**')
    st.caption('Each button submits one demo market order after refreshing the chart, news and quote. Entry and dynamic levels may change. The same daily budget, five-attempt limit and duplicate-order protection apply.')
    if enabled:
        st.info('Stop automatic trading to enable these manual trade buttons.')
    headers=st.columns([2,1,1.4,1.4,1.4,1,2])
    for col,label in zip(headers,['Pair / direction','Lots','Entry','Take profit','Stop loss','Risk %','IC Markets action']):
        col.write('**'+label+'**')
    for symbol,row in current_status.items():
        cols=st.columns([2,1,1.4,1.4,1.4,1,2])
        side=row.get('chart_signal')
        cols[0].write(f"{symbol} · {side or '—'}")
        for col,key in zip(cols[1:6],['position_lots','entry','take_profit','stop_loss','risk_pct']):
            value=row.get(key)
            col.write('—' if value is None else f'{value:.5f}' if key in ('entry','take_profit','stop_loss') else f'{value:.2f}')
        qualifies=row.get('decision') in ('BUY setup','SELL setup') and side in ('BUY','SELL')
        if cols[6].button(f'{side} 0.01 demo' if qualifies else 'No setup',
                          key='row_trade_'+symbol,disabled=enabled or not qualifies,
                          help='Refreshes and rechecks this setup before submitting to your IC Markets demo account.'):
            try:
                with st.spinner(f'Rechecking {symbol} before submission…'):
                    outcome=auto.trade_row(identity,symbol,offset,side)
                st.session_state['xm_row_trade_result']={'symbol':symbol,**outcome}
            except bridge.DemoError as exc:
                st.session_state['xm_row_trade_result']={'symbol':symbol,'state':'blocked','message':str(exc)}
    outcome=st.session_state.get('xm_row_trade_result')
    if outcome:
        message=f"{outcome['symbol']} · {outcome['state']}: {outcome.get('message','')}"
        (st.success if outcome['state']=='filled' else st.warning)(message)


def render(identity,instruments,offset):
    import streamlit as st
    st.markdown('### Automatic IC Markets demo trading')
    from .xm_news import connection_status
    news_connected,news_connection_reason=connection_status()
    st.caption('Gold M1/M5/M15 structure rules, cost-aware holdout evaluation and required AI news.')
    if not news_connected:
        st.info('AI NEWS NOT CONNECTED: '+news_connection_reason+' AI news is required for every entry.')
    else:
        st.caption('News service: '+news_connection_reason)
    symbols=auto.eligible(instruments)
    config = auto.settings()
    context_changed = (tuple(config.get('identity', [])) != tuple(identity)
                       or config.get('symbols') != symbols or config.get('offset') != offset)
    if context_changed and not config.get('enabled'):
        if config.get('identity'):
            st.info('Saved automation belongs to a different account, instrument or timestamp convention. Update the stopped session before starting.')
        else:
            st.info('No automation session is saved. Bind this demo account and gold instrument before starting entries.')
        if st.button('Use connected demo account and gold instrument', key='bind_gold_demo', disabled=len(symbols) != 1):
            auto.bind_stopped_session(identity, symbols, offset)
            st.rerun()
    from .gold import execution_validation
    validation_results=[execution_validation(s) for s in symbols]
    trade_validated=bool(validation_results) and all(result[0] for result in validation_results)
    if auto.settings().get('allow_unvalidated_demo') is True:
        st.warning('User-approved demo research: historical tests are advisory. New bot positions use broker SL/TP and a 15-minute candle-based exit deadline. News and account risk limits still apply.')
    if auto.settings().get('exclude_tesla_stop_risk') is True:
        st.warning('Tesla is excluded from open-position stop-risk estimates at your request. Its account-equity gains/losses still count. The daily budget does not cover Tesla’s additional loss to its stop.')
    if not trade_validated:
        reason=next((message for passed,message in validation_results if not passed),
                    'No eligible gold instrument is available for automation.')
        st.info('Automatic entries are blocked: '+reason)
    budget_label=(f"${auto.settings()['daily_loss_usd']:.2f} daily loss budget" if auto.settings().get('daily_loss_usd') is not None else '1% daily equity budget')
    if auto.settings().get('daily_loss_eur') is not None:
        budget_label = f"€{auto.settings()['daily_loss_eur']:.2f} daily loss budget (converted using fresh EURUSD bid for USD accounts)"
    st.caption(f'{len(symbols)} IC Markets gold instruments eligible for exactly 0.01 lot. Daily equity loss plus reserved open-stop risk and a 20% cost reserve for the new trade must fit the {budget_label}. Five entry attempts per UTC day. Stops/targets attached to every entry.')
    st.caption('Background worker runs with the browser closed, for up to eight hours of entries per start. Stop blocks new entries; timed exits for new bot positions remain active. Keep this computer and MT5 running. Broker stops remain in place if the worker is offline; timed exits can be delayed by downtime or unavailable quotes.')
    config=auto.settings()
    left,right=st.columns(2)
    if left.button('Start automatic DEMO trading',disabled=config.get('enabled',False) or not news_connected or not trade_validated,key='start_auto_demo'):
        auto.arm(identity,symbols,offset)
    if right.button('Stop automatic trading',key='stop_auto_demo'):
        auto.stop()
    config=auto.settings()
    st.write('**Automation: '+('RUNNING**' if config.get('enabled') else 'STOPPED**'))
    if config.get('stop_reason'):
        st.info(config['stop_reason'])
    remaining=config.get('expires',0)-time.time()
    if config.get('enabled') and remaining>0:
        st.caption(f'Session expires in {remaining/3600:.1f}h ({datetime.fromtimestamp(config["expires"], timezone.utc).strftime("%H:%M UTC")})')
    with st.expander('Approved gold instrument' if config.get('identity') else 'Eligible gold instrument (not bound)'):
        st.write(', '.join(config.get('symbols',symbols)))
    from .gold_worker import ensure_running,status as worker_status,healthy as worker_healthy
    ensure_running()
    heartbeat=worker_status()
    healthy=worker_healthy(heartbeat)
    worker_label=('connected' if healthy else
                  'connected; waiting for an account session'
                  if not config.get('identity') and heartbeat.get('scanner_alive')
                  and not heartbeat.get('exit_error')
                  and 0 <= time.time()-heartbeat.get('heartbeat',0) < 15 else
                  'starting / unavailable')
    st.caption('Background worker: '+worker_label)
    st.caption('Scanner: '+heartbeat.get('scanner','not started'))
    if config.get('enabled') and not heartbeat.get('scanner_alive',False):
        st.error('The scanning thread is not running. New signals are unavailable; check persistent events.')
    if heartbeat.get('exit_error'):
        st.warning('Exit watchdog: '+heartbeat['exit_error'])
    try:
        persisted=json.loads(auto.STATUS_FILE.read_text())
        if config.get('enabled'):
            auto.STATUS=persisted
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
    if config.get('enabled') and auto.STATUS.get('Account',{}).get('message'):
        st.warning(auto.STATUS['Account']['message'])
    approved=config.get('symbols',symbols)
    current_status={s:v for s,v in auto.STATUS.items() if v.get('engine')==auto.ENGINE and s in approved}
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
        render_trade_rows(identity,offset,current_status,auto.settings().get('enabled',False))
        errors=[(s,v) for s,v in current_status.items() if v.get('state')=='error' and v.get('traceback')]
        if errors:
            with st.expander('Automation error details'):
                for symbol,error in errors:
                    st.markdown(f'**{symbol} · {error.get("time","unknown time")}**')
                    st.code(error['traceback'],language='text')
    return auto.settings().get('enabled',False)

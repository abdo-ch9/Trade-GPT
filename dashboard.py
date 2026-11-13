"""Exness gold research desk. Legacy dashboard archived separately."""
import json
import time
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from scalp_lab import gold, mt5_demo as bridge, auto_demo

st.set_page_config(page_title='Gold research desk',layout='wide')
st.title('Gold research desk')
st.caption('XAU/USD · Exness MT5 · M1 / M5 / M15')
st.info('Entries require a named chart setup, current sourced AI news and broker risk checks. In user-approved demo research mode, historical validation is advisory. No win-rate guarantee.')


@st.fragment(run_every='10s')
def workspace():
    offset=bridge.UTC_OFFSET_HOURS
    st.caption('Exness MT5 timestamps use UTC.')
    if st.button('Connect Exness MT5',key='gold_connect'):
        try:
            st.session_state.gold_identity=bridge.connect(read_only=True)
        except bridge.DemoError as exc:
            st.error(str(exc))
    identity=st.session_state.get('gold_identity')
    if not identity:
        st.info('Connect the installed Exness MT5 terminal to load gold prices and analysis.')
        return
    try:
        account,instruments=bridge.inspect(identity, read_only=True)
        live_account = account.trade_mode == bridge.api().ACCOUNT_TRADE_MODE_REAL
        mode = "real" if live_account else "demo"
        if live_account:
            st.warning("Exness real account connected. Order controls use real funds.")
        choices=[s for s in instruments if gold.eligible_symbol(s)]
        if not choices:
            st.warning('No supported Exness XAUUSD instrument is available on this account.')
            return
        symbol=st.selectbox('Exact gold instrument',[s.name for s in choices])
        info=next(s for s in choices if s.name==symbol)
        st.caption(f'{symbol} · contract size {info.trade_contract_size:g} · equity {account.equity:,.2f} {account.currency}')
        with st.expander(f'Forward {mode} performance and execution review'):
            from scalp_lab.forward_report import summarize
            forward = summarize(identity, auto_demo.JOURNAL)
            metrics = st.columns(4)
            metrics[0].metric(f'Closed {mode} trades', forward['closed_trades'])
            metrics[1].metric('Net realized P&L', f"{forward['net_pnl']:.2f} {account.currency}")
            metrics[2].metric('Unresolved entries', forward['unresolved_entries'])
            metrics[3].metric('Unresolved exits', forward['unresolved_exits'])
            st.caption(forward['note'])
            st.caption('Drawdown below follows entry order and closed results; it is not an intraday equity drawdown. R uses estimated entry stop risk, including realized costs in the numerator.')
            st.write({k: forward[k] for k in ('states', 'win_rate', 'profit_factor', 'mean_r', 'max_closed_drawdown', 'commission', 'swap', 'fee', 'mean_latency_seconds')})
            if forward['unresolved_entries'] or forward['unresolved_exits']:
                st.warning('Broker/journal outcomes need review. Do not retry ambiguous orders blindly.')
            if forward['trades']:
                st.dataframe(forward['trades'], hide_index=True, width='stretch')
            else:
                st.info('No reconciled closed bot trades for this account yet. Signals and blocked decisions are not counted as executed trades.')
            st.download_button(f'Download forward {mode} report', json.dumps(forward, indent=2), f'forward_{mode}_report.json')
        with st.expander('Historical evaluation',expanded=True):
            st.write('Fixed rules; chronological 60/40 development/holdout split, four holdout time blocks, 15-minute simulated hold, daily bootstrap uncertainty and doubled-cost stress test.')
            if st.button('Fetch gold history and evaluate',key='gold_evaluate'):
                with st.spinner('Evaluating historical gold candles…'):
                    with bridge.LOCK:
                        mt5=bridge.api()
                        bridge.checked_account(mt5, identity)
                        mt5.symbol_select(symbol,True)
                        rates=mt5.copy_rates_from_pos(symbol,mt5.TIMEFRAME_M1,0,60000)
                        bridge.checked_account(mt5, identity)
                    if rates is None or len(rates)<1000:
                        raise bridge.DemoError(f'Need more gold M1 history. Open {symbol} M1 in MT5 and load history.')
                    bars=pd.DataFrame(rates)
                    bars=bars[bars.time+60<=time.time()+offset*3600]
                    report,trades=gold.evaluate(bars,symbol,info.point)
                    from scalp_lab.gold_storage import write_json
                    write_json(gold.REPORT, report)
                    bars.to_csv(gold.ROOT/'gold_history.csv',index=False)
                    trades.to_csv(gold.ROOT/'gold_research_trades.csv',index=False)
            try:
                report=json.loads(gold.REPORT.read_text())
                if report.get('symbol')==symbol and report.get('broker')==bridge.BROKER_NAME:
                    cols=st.columns(4)
                    values=report['holdout']
                    cols[0].metric('Holdout trades',values['trades'])
                    cols[1].metric('Expectancy (R)',f"{values['expectancy_r']:.3f}" if values['expectancy_r'] is not None else 'Unavailable')
                    cols[2].metric('Profit factor',f"{values['profit_factor']:.2f}" if values['profit_factor'] is not None else 'Unavailable')
                    cols[3].metric('Max drawdown (R)',f"{values['max_drawdown_r']:.2f}" if values['max_drawdown_r'] is not None else 'Unavailable')
                    (st.success if report['eligible'] else st.warning)(report['reason'])
                    st.dataframe(report['chronological_folds'],hide_index=True)
                    if report.get('setup_breakdown'):
                        st.write('**Setup-by-setup evaluation**')
                        st.dataframe(pd.DataFrame(report['setup_breakdown']).T)
                        st.write('Exit reasons:',report.get('exit_breakdown',{}))
                    st.caption(report.get('evaluation_note','Previously viewed historical sample; not fresh validation.'))
                    st.caption(report['limitations'])
                    st.caption('Costs: bar spread, adverse slippage of max(1 tick, 5% of M1 ATR) per fill, assumed $0.10/oz round-trip commission. Stops win same-bar collisions. Actual broker costs may differ.')
                    st.download_button('Download evaluation',json.dumps(report,indent=2),'gold_validation.json')
                else:
                    st.info('No current Exness evaluation for this instrument. Run a fresh evaluation using this account’s gold history.')
            except (OSError,ValueError,KeyError):
                st.info('No gold evaluation yet.')
        from scalp_lab.gold_worker import status as worker_status, healthy as worker_healthy, ensure_running
        from scalp_lab.gold_snapshot import read as read_snapshot
        config = auto_demo.settings()
        worker = worker_status()
        st.subheader('Current automation status')
        from scalp_lab.telegram_notifications import configuration as telegram_configuration, STATE as telegram_state
        with st.expander('Telegram decision notifications'):
            if all(telegram_configuration().values()):
                st.caption('Telegram configured. New decision changes are sent by the background worker.')
                try:
                    delivery = json.loads(telegram_state.read_text(encoding='utf-8'))
                    st.write('Delivery status: '+delivery.get('status', 'Waiting'))
                except (OSError, ValueError):
                    st.caption('Waiting for notification worker initialization.')
            else:
                st.info('Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to your local .env file to activate decision notifications. See README for setup.')

        state_cols = st.columns(3)
        state_cols[0].metric('Entries', 'Enabled' if config.get('enabled') else 'Stopped')
        state_cols[1].metric('Exit watchdog', 'Healthy' if worker_healthy(worker) else 'Unavailable')
        scan_age = time.time()-worker.get('last_scan', 0)
        state_cols[2].metric('Last completed scan', f'{scan_age:.0f}s ago' if worker.get('last_scan') else 'Waiting')
        st.caption('MT5 connection verified for the displayed account. Scanner: '+worker.get('scanner', 'Not started'))
        if worker.get('exit_error'):
            st.warning('Current exit-watchdog issue: '+worker['exit_error'])
        if config.get('enabled'):
            ensure_running()
            result = read_snapshot(identity, symbol, offset)
            if result is None or not worker_healthy(worker):
                st.warning('Waiting for a fresh worker snapshot. Previous signals are not actionable.')
                auto_demo.render(identity, [info], offset, mode=mode)
                return
            st.caption(f"Shared worker snapshot · {result['snapshot_age_seconds']:.0f}s old")
        else:
            result,_=gold.snapshot(identity,symbol,offset)
            from scalp_lab.gold_decisions import save as save_decision
            save_decision(identity,symbol,result)
        try:
            from scalp_lab.gold_snapshot import risk_summary
            risk = risk_summary(identity, config)
            risk_cols = st.columns(3)
            risk_cols[0].metric('Daily risk budget', f"{risk['budget']:.2f} {risk['currency']}")
            risk_cols[1].metric('Remaining risk budget', f"{risk['remaining']:.2f} {risk['currency']}")
            risk_cols[2].metric('Entry attempts today', f"{risk['attempts']} / 5")
            st.caption('Remaining budget deducts daily equity loss and reserved position stop risk. Each new entry also requires a 20% cost reserve. Execution rechecks these values.')
        except bridge.DemoError as exc:
            st.warning('Current risk budget unavailable: '+str(exc))
        news = result.get('news', {})
        news_age = time.time()-news.get('checked_at', 0)
        st.caption(f"News: {news.get('status', 'unavailable')} · "+(f'{news_age:.0f}s old' if news.get('checked_at') else 'refreshing'))
        cols=st.columns(4)
        cols[0].metric('Decision',result['action'])
        cols[1].metric('Market regime',result['regime'])
        cols[2].metric('Setup',result['setup'])
        cols[3].metric('Candle age',f"{result['candle_age_seconds']:.0f}s")
        for reason in result['reasons']:
            st.write(reason)
        with st.expander('Why this decision? Live condition checks',expanded=True):
            st.dataframe(result.get('checks',[]),hide_index=True,width='stretch')
            st.caption('Only one BUY/SELL entry pattern needs to qualify. Every applicable risk and execution check must pass. Portfolio risk, pending orders, daily attempts and final quotes are checked again before sending.')
        chart=result['frame'].tail(240)
        x=pd.to_datetime(chart.time,unit='s')
        fig=go.Figure(go.Candlestick(x=x,open=chart.open,high=chart.high,low=chart.low,close=chart.close,name=symbol))
        for field,label in [('ema9','EMA 9'),('ema20','EMA 20'),('vwap_proxy','Tick-volume VWAP proxy')]:
            fig.add_scatter(x=x,y=chart[field],name=label,mode='lines')
        fig.update_layout(height=480,xaxis_rangeslider_visible=False,uirevision=symbol,title='Completed M1 candles · broker time')
        st.plotly_chart(fig,width='stretch')
        if result['scenarios']:
            st.dataframe(pd.DataFrame(result['scenarios']).T, width='stretch')
            st.caption('Indicative levels; risk_pct is estimated stop loss / account equity × 100. Actual fills, fees and gaps can change loss.')
        st.write('**AI news:** '+result['news'].get('reason','Unavailable'))
        with st.expander('News evidence'):
            for article in result['news'].get('articles',[]):
                st.link_button(article['title'],article['url'])
        with st.expander('Inputs and limitations'):
            st.dataframe([
                {'Input':'Exness M1/M5/M15 price, spread, ATR, RSI, structure','Status':'Measured / calculated'},
                {'Input':'VWAP and relative volume','Status':'Tick-volume proxies; not consolidated traded volume'},
                {'Input':'Gold macro headlines','Status':'Ollama assessment of cited recent headlines'},
                {'Input':'DXY, Treasury / real yields, economic calendar','Status':'Not connected; no scheduled-event blackout guarantee'},
                {'Input':'COMEX depth, delta, open interest, real volume profile','Status':'Not connected; never inferred from Exness ticks'},
                {'Input':'ML probabilities / 60% win rate','Status':'No calibrated probability claim'}],hide_index=True)
            st.write('Setups: aligned M5/M15 trend pullback; breakout retest anchored to the original broken level; range sweep. ATR defines stops; target is 1.8R. New bot entries share the backtest deadline: 15 minutes after the signal candle closes, with earlier broker SL/TP exits. Actual timed fills can be delayed by quote/connection availability.')
        if not auto_demo.settings().get('enabled'):
            from datetime import datetime,timezone
            scenario=result['scenarios'].get(result['chart_signal'],{})
            auto_demo.STATUS[symbol]={'engine':gold.ENGINE,'time':datetime.now(timezone.utc).isoformat(),
                'state':'research','decision':result['action'],'chart_signal':result['chart_signal'],
                'setup':result['setup'],'regime':result['regime'],'message':' '.join(result['reasons']),
                'entry':scenario.get('entry'),'stop_loss':scenario.get('sl'),'take_profit':scenario.get('tp'),
                'position_lots':scenario.get('lots'),'risk_pct':scenario.get('risk_pct'),
                'risk_amount':scenario.get('risk_amount'),'account_currency':scenario.get('currency')}
        auto_demo.render(identity,[info],offset,mode=mode)
    except (bridge.DemoError,ValueError) as exc:
        st.warning(str(exc))


workspace()

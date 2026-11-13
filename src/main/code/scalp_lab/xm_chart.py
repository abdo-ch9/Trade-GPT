"""Chart rules plus required AI news. No local training or validation-score gate."""
import math
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from . import mt5_demo as bridge
from .xm_news import get_news

ENGINE = 'chart-news-v1'


def indicators(frame):
    d = frame.copy()
    for period in (9, 21, 50):
        d[f'ema{period}'] = d.close.ewm(span=period, min_periods=period, adjust=False).mean()
    tr = pd.concat([d.high-d.low, (d.high-d.close.shift()).abs(),
                    (d.low-d.close.shift()).abs()], axis=1).max(axis=1)
    d['atr'] = tr.rolling(14).mean()
    d['support'] = d.low.shift().rolling(20).min()
    d['resistance'] = d.high.shift().rolling(20).max()
    delta = d.close.diff()
    gains = delta.clip(lower=0).rolling(14).mean()
    losses = -delta.clip(upper=0).rolling(14).mean()
    d['rsi'] = 100-100/(1+gains/losses.replace(0,np.nan))
    d.loc[(losses==0)&(gains>0),'rsi'] = 100
    d.loc[(losses==0)&(gains==0),'rsi'] = 50
    return d


def chart_frames(bars, server_now):
    columns = ['time','open','high','low','close','tick_volume']
    if bars.empty or not set(columns).issubset(bars.columns):
        return pd.DataFrame(), pd.DataFrame()
    d = bars[columns].apply(pd.to_numeric, errors='coerce')
    d = d.replace([np.inf,-np.inf],np.nan).dropna().sort_values('time').drop_duplicates('time')
    d = d[(d.time+60<=server_now)&(d.low>0)&(d.tick_volume>=0)
          &(d.high>=d[['open','close','low']].max(axis=1))
          &(d.low<=d[['open','close']].min(axis=1))].reset_index(drop=True)
    if d.empty:
        return d, pd.DataFrame()
    # Reset indicators after missing bars; never bridge a closed session or data gap.
    segment = d.time.diff().ne(60).cumsum()
    d = d[segment==segment.iloc[-1]].copy().reset_index(drop=True)
    d['bucket'] = (d.time//300)*300
    higher = d.groupby('bucket').agg(time=('time','min'), open=('open','first'),
        high=('high','max'), low=('low','min'), close=('close','last'),
        tick_volume=('tick_volume','sum'), count=('time','size')).reset_index()
    higher = higher[(higher['count']==5)&(higher.bucket+300<=server_now)].copy()
    higher['time'] = higher.bucket
    return indicators(d), indicators(higher.reset_index(drop=True))


def news_gate(news, side, now):
    if news.get('status') == 'not_connected':
        return 'AI NEWS NOT CONNECTED', news.get('reason','Connect AI news before trading.')
    if (news.get('status') != 'ready' or news.get('relevant') is not True
        or type(news.get('high_risk')) is not bool
        or news.get('direction') not in ('BUY','SELL','NEUTRAL')
        or not 0 <= now-news.get('checked_at',0) < 300
        or now >= news.get('expires_at',0)):
        return 'NEWS UNAVAILABLE', news.get('reason','A current AI news assessment is required.')
    articles = {a.get('id'):a for a in news.get('articles',[])
                if 0 <= now-a.get('published_at',0) <= 86400}
    evidence = news.get('evidence_ids',[])
    if not evidence or any(i not in articles for i in evidence):
        return 'NEWS UNAVAILABLE', 'News evidence is missing or expired.'
    if news['high_risk']:
        return 'NEWS RISK', 'AI flagged a major news risk: '+news.get('reason','')
    if news['direction'] not in ('NEUTRAL',side):
        return 'NEWS CONFLICT', 'AI news disagrees with the chart direction: '+news.get('reason','')
    return None, None


def assess_chart(bars, point, bid, ask, server_now, news, min_stop=0, now=None):
    now = time.time() if now is None else now
    d, higher = chart_frames(bars, server_now)
    result = {'engine':ENGINE,'frame':d,'action':'DATA UNAVAILABLE','bias':'Unavailable',
              'chart_signal':'Unavailable','ready':False,'reasons':[], 'blockers':[],
              'news':news,'observed_at':now,'components':{},'scenarios':{}}
    def block(action, reason):
        result['action'] = action
        result['blockers'].append(reason)
        result['reasons'].append(reason)
        return result
    if d.empty:
        return block('DATA UNAVAILABLE','No usable completed IC Markets candles.')
    age = server_now-(float(d.iloc[-1].time)+60)
    result['candle_age_seconds'] = age
    if not 0 <= age <= 90:
        return block('DATA STALE',f'Latest completed candle is {age:.0f}s old; maximum is 90s.')
    if len(d)<60 or len(higher)<21:
        return block('MORE CHART DATA NEEDED','Need 21 complete five-minute candles in a continuous recent session.')
    row, h = d.iloc[-1], higher.iloc[-1]
    if not all(math.isfinite(x) for x in (point,bid,ask,min_stop,row.atr,h.atr,row.rsi)) or min(point,bid,ask,h.atr)<=0 or ask<bid or min_stop<0:
        return block('DATA UNAVAILABLE','Invalid broker quote, tick size or chart volatility.')
    sign = lambda v: int(v>0)-int(v<0)
    components = {
        'M1 trend':2*sign(float(row.ema9-row.ema21)),
        'M5 trend':2*sign(float(h.ema9-h.ema21)),
        'Momentum':1 if row.rsi>55 else -1 if row.rsi<45 else 0,
        'Price structure':sign(float(row.close-(row.support+row.resistance)/2)),
        'Last candle':sign(float(row.close-row.open))}
    score = sum(components.values())
    side = 'BUY' if score>0 else 'SELL' if score<0 else 'MIXED'
    result.update(ready=True, bias=side+' bias' if side!='MIXED' else 'MIXED',
                  chart_signal=side, chart_score=score, components=components)
    spread = ask-bid
    result['reasons'] += [f'Chart reading: {side}; agreement score {score:+d}/7 (a rule score, not a win probability).',
        f'M1 RSI {row.rsi:.1f}; M5 average true range {h.atr:.6g}; spread {spread:.6g}.']
    for direction, multiplier, entry in [('BUY',1,ask),('SELL',-1,bid)]:
        structure = entry-h.support if multiplier==1 else h.resistance-entry
        risk = max(1.5*h.atr, min(max(structure,0),3*h.atr), spread+min_stop+2*point)
        target = 2*risk
        result['scenarios'][direction] = {'entry':float(entry),'sl':float(entry-multiplier*risk),
            'tp':float(entry+multiplier*target),'sl_bps':float(risk/entry*10000),
            'tp_bps':float(target/entry*10000)}
    blockers = []
    if abs(score)<4:
        blockers.append(('NO CLEAR SETUP','Chart signals conflict: at least 4 signed agreement points out of 7 are required.'))
    if spread>h.atr:
        blockers.append(('SPREAD TOO WIDE','Spread exceeds the average five-minute candle range.'))
    if abs((bid+ask)/2-row.close)>max(h.atr,3*spread):
        blockers.append(('PRICE MOVED','Quote has moved too far from the last completed candle; wait for the next close.'))
    if any(min(v['sl'],v['tp'])<=0 for v in result['scenarios'].values()):
        blockers.append(('INVALID LEVELS','Chart volatility produces an invalid stop or target.'))
    news_action, news_reason = news_gate(news,side,now)
    if news_action:
        blockers.append((news_action,news_reason))
    if blockers:
        # The headline result names the first blocker; every blocker remains visible.
        result['action'] = blockers[0][0]
        result['blockers'] = [reason for _,reason in blockers]
        result['reasons'] += result['blockers']
    else:
        result['action'] = side+' setup'
        result['reasons'].append('Chart setup qualifies and current cited AI news does not oppose it.')
    return result


def snapshot(identity, symbol, offset, horizon=5, include_headlines=False):
    # Selecting a symbol starts asynchronous terminal history synchronization.
    # Warm it before slow news inference, then obtain a new snapshot afterwards.
    with bridge.LOCK:
        mt5 = bridge.api()
        bridge.checked_account(mt5,identity)
        if not mt5.symbol_select(symbol,True):
            raise bridge.DemoError('Cannot subscribe to this IC Markets instrument.')
        mt5.copy_rates_from_pos(symbol,mt5.TIMEFRAME_M1,0,361)
    news = get_news(symbol, include_headlines=include_headlines)
    rates = recent_rates(mt5,symbol,offset)
    with bridge.LOCK:
        bridge.checked_account(mt5,identity)
        info = mt5.symbol_info(symbol)
        if info is None or rates is None or not len(rates):
            raise bridge.DemoError('IC Markets chart data unavailable. Open this instrument’s M1 chart in MT5.')
        tick = bridge.quote(mt5,symbol,offset)
    observed = time.time()
    result = assess_chart(pd.DataFrame(rates),info.point,tick.bid,tick.ask,observed+offset*3600,
                          news,info.trade_stops_level*info.point,observed)
    with bridge.LOCK:
        account = bridge.checked_account(mt5,identity)
        add_scenario_risk(result,mt5,symbol,account)
    if result['action'] == 'DATA STALE':
        result['reasons'].append('The quote is fresh but MT5 candle history has not caught up. Open this instrument’s M1 chart in MT5; the next scan will retry.')
    return result, {'version':ENGINE,'model_name':'Chart rules + required AI news'}


def add_scenario_risk(result, mt5, symbol, account):
    """Read-only broker valuation for the approved 0.01-lot scenarios."""
    for side, scenario in result['scenarios'].items():
        scenario.update(lots=.01,currency=account.currency,risk_amount=None,risk_pct=None)
        order_type = mt5.ORDER_TYPE_BUY if side=='BUY' else mt5.ORDER_TYPE_SELL
        loss = mt5.order_calc_profit(order_type,symbol,.01,scenario['entry'],scenario['sl'])
        if loss is not None and math.isfinite(loss) and loss < 0:
            scenario['risk_amount'] = abs(loss)
            if math.isfinite(account.equity) and account.equity > 0:
                scenario['risk_pct'] = abs(loss)/account.equity*100


def recent_rates(mt5, symbol, offset):
    """Bounded history refresh; never relabel timestamps or relax freshness."""
    for attempt in range(5):
        server_now = time.time()+offset*3600
        with bridge.LOCK:
            if attempt == 0:
                rates = mt5.copy_rates_from_pos(symbol,mt5.TIMEFRAME_M1,0,361)
            else:
                rates = mt5.copy_rates_from(symbol,mt5.TIMEFRAME_M1,
                    datetime.fromtimestamp(server_now,timezone.utc),361)
        completed, _ = chart_frames(pd.DataFrame(rates),server_now)
        if not completed.empty and 0 <= server_now-completed.iloc[-1].time-60 <= 90:
            return rates
        if attempt < 4:
            # Allow terminal synchronization without locking other MT5 consumers.
            time.sleep(.5)
    return rates


def render(identity, symbol, offset):
    import streamlit as st
    import plotly.graph_objects as go
    st.markdown('### IC Markets chart and news decision')
    st.caption('M1 + M5 chart rules; AI interprets recent sourced headlines. No local model training. Experimental demo strategy; no validated win-rate claim.')
    try:
        result, _ = snapshot(identity,symbol,offset,include_headlines=True)
        cols = st.columns(2)
        cols[0].metric('Chart direction',result['chart_signal'])
        news_label = {'not_connected':'Not connected','ready':'Reviewed',
                      'no_relevant_news':'No relevant news','no_news':'No news','unavailable':'Unavailable'}
        cols[1].metric('AI news',news_label.get(result['news']['status'],'Unavailable'))
        if result['action'] in ('BUY setup','SELL setup'):
            st.success('Order decision: '+result['action'])
        else:
            st.info('Order decision: '+result['action'])
        for reason in result['reasons']:
            st.write('• '+reason)
        if result['components']:
            with st.expander('Chart signal details'):
                st.dataframe([{'Signal':name,'Agreement points':points}
                              for name,points in result['components'].items()],hide_index=True)
        chart = result['frame'].tail(180)
        if not chart.empty:
            x = pd.to_datetime(chart.time,unit='s')
            fig = go.Figure(go.Candlestick(x=x,open=chart.open,high=chart.high,low=chart.low,close=chart.close,name=symbol))
            for field in ('ema9','ema21'):
                fig.add_scatter(x=x,y=chart[field],name=field.upper(),mode='lines',connectgaps=False)
            fig.update_layout(height=400,template='plotly_dark',xaxis_rangeslider_visible=False,uirevision=symbol,
                              title=f'{symbol} · IC Markets M1 candles · broker server time')
            st.plotly_chart(fig,width='stretch',key='xm_chart_news_chart')
        if result['scenarios']:
            st.write('**Dynamic entry, stop and target scenarios**')
            st.dataframe(pd.DataFrame(result['scenarios']).T[
                ['lots','entry','sl','tp','risk_amount','risk_pct','currency']].rename(columns={
                    'lots':'Position (lots)','entry':'Indicative entry','sl':'Stop loss',
                    'tp':'Take profit','risk_amount':'Estimated loss at stop',
                    'risk_pct':'Risk (% equity)','currency':'Account currency'}),width='stretch')
            st.caption('Risk is the broker-estimated entry-to-stop loss for 0.01 lot divided by current equity. Excludes fees and slippage; blank means unavailable. These are proposed levels, not an open position or confirmed fill.')
            st.caption('Stop follows M5 volatility, price structure and broker minimum distance. Target is twice the stop distance. A scenario is not permission to submit when the order decision is blocked.')
        news = result['news']
        if news.get('provider'):
            st.caption(f"News AI: {news['provider']} · {news.get('model','')}")
        st.write('**News assessment:** '+news.get('reason','Unavailable'))
        st.caption('Headlines from the last 24 hours; refreshed about every five minutes. Headline coverage is incomplete and is not a full economic calendar. Article text is not fetched.')
        with st.expander('News headlines and sources'):
            for article in news.get('articles',[]):
                st.link_button(article['title'],article['url'])
                st.caption(f"{article['source']} · {pd.to_datetime(article['published_at'],unit='s',utc=True)}")
        if news['status']=='not_connected':
            st.info(news.get('reason','Connect the configured news AI service.')+' AI news is required for automatic orders.')
        return result['scenarios']
    except bridge.DemoError as exc:
        st.warning(str(exc))
        return {}

"""Causal GOLD research engine. Fixed rules; no fitted win-probability claim."""
import json
import math
import time
from pathlib import Path
import numpy as np
import pandas as pd
from . import mt5_demo as bridge
from .xm_chart import indicators, news_gate, add_scenario_risk
from .xm_news import get_news_background as get_news
from .gold_exits import EXIT_POLICY, HOLD_BARS

ENGINE='gold-structure-v2'
# Last completed bar of the five-minute study already inspected. That sample cannot authorize entries.
PUBLISHED_THROUGH=1793887020.0
from .paths import LIB_DIR
ROOT=LIB_DIR
REPORT=ROOT/'gold_validation.json'
SYMBOLS={'GOLD','XAUUSD'}


def eligible_symbol(info):
    return info.name in SYMBOLS and info.currency_profit=='USD'


def features(bars):
    required=['time','open','high','low','close','tick_volume']
    if bars.empty:
        raise ValueError('No completed gold candles available.')
    d=bars.copy().sort_values('time').drop_duplicates('time').reset_index(drop=True)
    if not set(required).issubset(d):
        raise ValueError('Missing OHLC or tick-volume columns.')
    if not np.isfinite(d[required].to_numpy(dtype=float)).all():
        raise ValueError('Non-finite market data.')
    if ((d.low<=0)|(d.tick_volume<0)|(d.high<d[['open','close','low']].max(axis=1))|
        (d.low>d[['open','close']].min(axis=1))).any():
        raise ValueError('Invalid candles.')
    # Indicator warm-up resets across missing minutes and market closures.
    d['segment']=d.time.diff().ne(60).cumsum()
    parts=[]
    for _,part in d.groupby('segment',sort=False):
        part=indicators(part)
        part['ema20']=part.close.ewm(span=20,min_periods=20,adjust=False).mean()
        part['rvol']=part.tick_volume/part.tick_volume.shift().rolling(20).mean().replace(0,np.nan)
        part['prior_close']=part.close.shift()
        part['prior_low']=part.low.shift()
        part['prior_high']=part.high.shift()
        part['close_time']=part.time+60
        for minutes in (5,15):
            buckets=part.groupby((part.time//(minutes*60))*(minutes*60)).agg(
                open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'),
                tick_volume=('tick_volume','sum'),count=('time','size'))
            buckets=buckets[buckets['count']==minutes].copy()
            buckets['close_time']=buckets.index+minutes*60
            buckets['fast']=buckets.close.ewm(span=9,min_periods=9,adjust=False).mean()
            buckets['slow']=buckets.close.ewm(span=20,min_periods=20,adjust=False).mean()
            buckets['atr']=pd.concat([buckets.high-buckets.low,(buckets.high-buckets.close.shift()).abs(),
                                      (buckets.low-buckets.close.shift()).abs()],axis=1).max(axis=1).rolling(14).mean()
            values=buckets[['close_time','fast','slow','atr']].rename(columns={k:f'{k}{minutes}' for k in ('fast','slow','atr')})
            part=pd.merge_asof(part.sort_values('close_time'),values.sort_values('close_time'),on='close_time',direction='backward')
        parts.append(part)
    d=pd.concat(parts,ignore_index=True)
    day=(d.time//86400).astype(int)
    typical=(d.high+d.low+d.close)/3
    d['vwap_proxy']=(typical*d.tick_volume).groupby(day).cumsum()/d.tick_volume.groupby(day).cumsum().replace(0,np.nan)
    daily=d.groupby(day).agg(high=('high','max'),low=('low','min')).shift()
    d['previous_day_high']=day.map(daily.high)
    d['previous_day_low']=day.map(daily.low)
    trend_up=(d.fast5>d.slow5)&(d.fast15>d.slow15)
    trend_down=(d.fast5<d.slow5)&(d.fast15<d.slow15)
    ranging=(d.fast15-d.slow15).abs()<.15*d.atr15
    d['regime']=np.select([ranging,trend_up,trend_down],['Range','Uptrend','Downtrend'],default='Transition')
    # No future-confirmed pivots: all structure levels exclude the signal candle.
    long_pull=trend_up&~ranging&(d.low<=d.ema20)&(d.close>d.ema9)&(d.close>d.open)&(d.rsi.between(50,70))&(d.close>d.vwap_proxy)
    short_pull=trend_down&~ranging&(d.high>=d.ema20)&(d.close<d.ema9)&(d.close<d.open)&(d.rsi.between(30,50))&(d.close<d.vwap_proxy)
    d['breakout_high']=d.groupby('segment').resistance.shift()
    d['breakout_low']=d.groupby('segment').support.shift()
    long_break=trend_up&~ranging&(d.prior_close>d.breakout_high)&(d.low<=d.breakout_high)&(d.close>d.breakout_high)&(d.rvol>=1.2)
    short_break=trend_down&~ranging&(d.prior_close<d.breakout_low)&(d.high>=d.breakout_low)&(d.close<d.breakout_low)&(d.rvol>=1.2)
    long_sweep=ranging&(d.low<d.support)&(d.close>d.support)&(d.close>d.open)&(d.rsi<45)&(d.rvol>=1)
    short_sweep=ranging&(d.high>d.resistance)&(d.close<d.resistance)&(d.close<d.open)&(d.rsi>55)&(d.rvol>=1)
    warm=d[['atr','atr5','atr15','slow15','rvol']].notna().all(axis=1)
    conditions=[warm&long_pull,warm&short_pull,warm&long_break,warm&short_break,warm&long_sweep,warm&short_sweep]
    d['side']=np.select(conditions,[1,-1,1,-1,1,-1],default=0)
    d['setup']=np.select(conditions,['Trend pullback','Trend pullback','Breakout retest','Breakout retest','Range sweep','Range sweep'],default='No setup')
    for name,condition in zip(['BUY pullback','SELL pullback','BUY retest','SELL retest','BUY sweep','SELL sweep'],conditions):
        d['check_'+name]=condition
    d['warm']=warm
    return d


def levels(row,side,entry,spread,min_stop=0,point=.01):
    structure=entry-row.support if side==1 else row.resistance-entry
    risk=max(1.2*row.atr5,min(max(structure,0),2.5*row.atr5),spread+min_stop+2*point)
    return {'entry':float(entry),'sl':float(entry-side*risk),'tp':float(entry+side*1.8*risk),
            'sl_bps':float(risk/entry*10000),'tp_bps':float(1.8*risk/entry*10000)}


def validation(symbol):
    try:
        r=json.loads(REPORT.read_text())
        if (r.get('broker')!=bridge.BROKER_NAME or r.get('engine')!=ENGINE or r.get('symbol')!=symbol
            or r.get('execution_policy')!=EXIT_POLICY or not 0<=time.time()-r['created_at']<7*86400):
            return False,'Run a current IC Markets historical evaluation for this exact gold instrument and the 15-minute hold.'
        if r.get('eligible') and not r.get('live_exit_validated',False):
            return False,'Chart research passed, but matching live exit management and forward paper validation are still required.'
        return r['eligible'],r['reason']
    except (OSError,ValueError,KeyError):
        return False,'Run historical evaluation before enabling gold entries.'


def snapshot(identity,symbol,offset,horizon=5,include_headlines=False,*,read_only=False):
    with bridge.LOCK:
        mt5=bridge.api()
        bridge.checked_account(mt5,identity,read_only=read_only)
        info=mt5.symbol_info(symbol)
        if info is None or not eligible_symbol(info):
            raise bridge.DemoError('Only the verified USD gold instrument is supported.')
        mt5.symbol_select(symbol,True)
        mt5.copy_rates_from_pos(symbol,mt5.TIMEFRAME_M1,0,3000)
    news=get_news(symbol,include_headlines=True)
    with bridge.LOCK:
        rates=mt5.copy_rates_from_pos(symbol,mt5.TIMEFRAME_M1,0,3000)
        tick=bridge.quote(mt5,symbol,offset)
    now=time.time()
    if rates is None or not len(rates):
        raise bridge.DemoError('Gold history is not available in MT5 yet.')
    bars=pd.DataFrame(rates)
    d=features(bars[bars.time+60<=now+offset*3600])
    row=d.iloc[-1]
    result={'engine':ENGINE,'frame':d,'observed_at':now,'news':news,'scenarios':{},
            'action':'NO SETUP','bias':row.regime,'chart_signal':'NONE','reasons':[],
            'setup':row.setup,'regime':row.regime,'ready':False}
    result['checks']=[{'Check':'Indicators warmed up','Passed':bool(row.warm)}]+[
        {'Check':name.removeprefix('check_'),'Passed':bool(row[name])}
        for name in d.columns if name.startswith('check_')]
    result['checks'] += [
        {'Check':'BUY pullback: touches EMA20','Passed':bool(row.low<=row.ema20)},
        {'Check':'BUY pullback: bullish close above EMA9','Passed':bool(row.close>row.open and row.close>row.ema9)},
        {'Check':'BUY pullback: RSI 50–70 and above VWAP proxy','Passed':bool(50<=row.rsi<=70 and row.close>row.vwap_proxy)},
        {'Check':'SELL pullback: touches EMA20','Passed':bool(row.high>=row.ema20)},
        {'Check':'SELL pullback: bearish close below EMA9','Passed':bool(row.close<row.open and row.close<row.ema9)},
        {'Check':'SELL pullback: RSI 30–50 and below VWAP proxy','Passed':bool(30<=row.rsi<=50 and row.close<row.vwap_proxy)}]
    age=now+offset*3600-row.time-60
    result['candle_age_seconds']=float(age)
    result['checks'].append({'Check':'Completed candle is fresh','Passed':bool(0<=age<=90)})
    if not 0<=age<=90:
        result.update(action='DATA STALE',reasons=[f'Completed gold candle age {age:.0f}s exceeds freshness limits.'])
        return result,{}
    if not math.isfinite(row.atr15):
        result.update(action='WARMING UP',reasons=['Need 20 complete M15 bars in a continuous session.'])
        return result,{}
    if not row.side:
        result['reasons']=[f'{row.regime}: none of the three defined entry patterns is confirmed.']
        return result,{}
    side='BUY' if row.side==1 else 'SELL'
    spread=tick.ask-tick.bid
    result['spread_price']=float(spread)
    entry=tick.ask if row.side==1 else tick.bid
    result.update(chart_signal=side,ready=True)
    result['scenarios'][side]=levels(row,row.side,entry,spread,info.trade_stops_level*info.point,info.point)
    blockers=[]
    if spread>.2*row.atr5:
        blockers.append('Spread exceeds 20% of M5 ATR.')
    if abs((tick.ask+tick.bid)/2-row.close)>row.atr:
        blockers.append('Price moved more than one M1 ATR since the signal close.')
    valid,reason=execution_validation(symbol)
    if not valid:
        blockers.append(reason)
    _,news_reason=news_gate(news,side,now)
    if news_reason:
        blockers.append(news_reason)
    with bridge.LOCK:
        account=bridge.checked_account(mt5,identity,read_only=read_only)
        add_scenario_risk(result,mt5,symbol,account)
    scenario=result['scenarios'][side]
    # Necessary affordability check only. Final execution also accounts for daily loss and exposures.
    from .auto_demo import settings,daily_budget
    config=settings()
    lots=config.get('lots',.01)
    budget=daily_budget(config,account.equity,account.currency)
    risk=scenario.get('risk_amount')
    affordable=risk is not None and risk*1.2<=budget
    if not affordable:
        blockers.append(f'Selected size {lots:g} lot exceeds the configured daily budget or its risk is unavailable (budget {budget:.2f} {account.currency}, including a 20% cost reserve).')
    result['checks'] += [{'Check':'Spread ≤ 20% of M5 ATR','Passed':bool(spread<=.2*row.atr5)},
                         {'Check':'Quote within one M1 ATR of signal close','Passed':bool(abs((tick.ask+tick.bid)/2-row.close)<=row.atr)},
                         {'Check':'Current news agrees / neutral','Passed':news_reason is None},
                         {'Check':'Research permission','Passed':bool(valid)},
                         {'Check':f'{lots:g} lot fits configured daily budget before existing losses/exposure','Passed':bool(affordable)}]
    result['action']='BLOCKED' if blockers else side+' setup'
    result['reasons']=[f'{side}: {row.setup}; {row.regime}.']+blockers
    return result,{}


def execution_validation(symbol,config=None):
    """Explicit demo research override; historical results remain unchanged."""
    if __package__.endswith('_live'):
        return validation(symbol)
    if config is None:
        try:
            config=json.loads((ROOT/'xm_auto_demo.json').read_text())
        except (OSError,ValueError):
            config={}
    if (config.get('allow_unvalidated_demo') is True and config.get('engine')==ENGINE
        and symbol in SYMBOLS and symbol in config.get('symbols',[])):
        return True,'User-approved demo research: historical validation is advisory.'
    return validation(symbol)


def simulate(d,point,cost_multiplier=1):
    """Next-bar entry, bid/ask spread, adverse slippage, stop-first collisions, 15-minute cap."""
    trades=[]
    next_free=0
    for i in np.flatnonzero(d.side.to_numpy()):
        if i<next_free or i+HOLD_BARS>=len(d):
            continue
        row=d.iloc[i]
        future=d.iloc[i+1:i+1+HOLD_BARS]
        if not np.all(np.diff(np.r_[row.time,future.time])==60):
            continue
        spread=max(float(row.get('spread',0))*point,point)*cost_multiplier
        if spread>.2*row.atr5:
            continue
        side=int(row.side)
        slip=max(point,.05*row.atr)*cost_multiplier
        entry=float(future.iloc[0].open)+(spread if side==1 else 0)+side*slip
        plan=levels(row,side,entry,spread,point=point)
        risk=abs(entry-plan['sl'])
        exit_price=None
        exit_reason='time'
        for j,bar in enumerate(future.itertuples()):
            exit_spread=max(float(getattr(bar,'spread',0))*point,point)*cost_multiplier
            low=bar.low+(exit_spread if side==-1 else 0)
            high=bar.high+(exit_spread if side==-1 else 0)
            opening=bar.open+(exit_spread if side==-1 else 0)
            stop_hit=low<=plan['sl'] if side==1 else high>=plan['sl']
            target_hit=high>=plan['tp'] if side==1 else low<=plan['tp']
            if stop_hit:
                exit_reason='stop'
                exit_price=min(plan['sl'],opening) if side==1 else max(plan['sl'],opening)
                break
            if target_hit:
                exit_reason='target'
                exit_price=plan['tp']
                break
        if exit_price is None:
            j=HOLD_BARS-1
            exit_price=float(future.iloc[-1].close)+(exit_spread if side==-1 else 0)
        exit_price-=side*slip
        # Conservative explicit commission assumption: $0.10 per ounce round trip.
        pnl=side*(exit_price-entry)-.10*cost_multiplier
        trades.append({'time':float(future.iloc[0].time),'exit_time':float(future.iloc[j].time+60),
                       'setup':row.setup,'side':side,'r':pnl/risk,'price_pnl':pnl,
                       'exit_reason':exit_reason,'entry':entry,'sl':plan['sl'],'tp':plan['tp'],
                       'spread_price':spread,'slippage_per_fill':slip})
        next_free=i+j+2
    return pd.DataFrame(trades)


def stats(trades):
    if trades.empty:
        return {'trades':0,'expectancy_r':None,'win_rate':None,'profit_factor':None,'max_drawdown_r':None}
    r=trades.r
    equity=np.r_[0,r.cumsum()]
    losses=float(-r[r<0].sum())
    return {'trades':len(r),'expectancy_r':float(r.mean()),'win_rate':float((r>0).mean()),
            'profit_factor':float(r[r>0].sum()/losses) if losses else None,
            'max_drawdown_r':float(np.max(np.maximum.accumulate(equity)-equity))}


def evaluate(bars,symbol,point):
    d=features(bars)
    # Fixed rules: first 60% development diagnostics, last 40% evaluation.
    # Purge one full hold so a development trade cannot exit inside the evaluation window.
    purge=HOLD_BARS*60
    cutoff=float(d.time.iloc[int(len(d)*.6)])+purge
    normal=simulate(d,point)
    stressed=simulate(d,point,2)
    holdout=normal[normal.time>=cutoff] if not normal.empty else normal
    stress=stressed[stressed.time>=cutoff] if not stressed.empty else stressed
    summary=stats(holdout)
    folds=[]
    for low,high in zip(np.linspace(cutoff,d.time.iloc[-1]+60,5)[:-1],np.linspace(cutoff,d.time.iloc[-1]+60,5)[1:]):
        folds.append(stats(holdout[(holdout.time>=low)&(holdout.time<high)]) if not holdout.empty else stats(holdout))
    def gate_stats(frame):
        checked=stats(frame)
        sessions=0
        lower=None
        blocks=[]
        if not frame.empty:
            days=frame.assign(day=(frame.time//86400).astype(int)).groupby('day').r.agg(['sum','count'])
            sessions=len(days)
            rng=np.random.default_rng(641105)
            sample=rng.integers(0,len(days),size=(2000,len(days)))
            boot=days['sum'].to_numpy()[sample].sum(axis=1)/days['count'].to_numpy()[sample].sum(axis=1)
            lower=float(np.quantile(boot,.05))
            start,end=float(frame.time.iloc[0]),float(frame.time.iloc[-1])+60
            for low,high in zip(np.linspace(start,end,5)[:-1],np.linspace(start,end,5)[1:]):
                blocks.append(stats(frame[(frame.time>=low)&(frame.time<high)]))
        passed=(checked['trades']>=50 and sessions>=10 and lower is not None and lower>0
                and all((b['expectancy_r'] or -1)>0 for b in blocks))
        return checked,sessions,lower,passed
    last=float(d.time.iloc[-1])
    previously_viewed=float(d.time.iloc[0])<=PUBLISHED_THROUGH
    if not previously_viewed:
        gate,stress_gate=holdout,stress
    elif last<=PUBLISHED_THROUGH:
        gate=holdout.iloc[0:0]
        stress_gate=stress.iloc[0:0]
    else:
        gate=holdout[holdout.time>PUBLISHED_THROUGH] if not holdout.empty else holdout
        stress_gate=stress[stress.time>PUBLISHED_THROUGH] if not stress.empty else stress
    _,sessions,lower,gate_passed=gate_stats(gate)
    stress_passed=(stats(stress_gate)['expectancy_r'] or -1)>0
    eligible=gate_passed and stress_passed and not (previously_viewed and last<=PUBLISHED_THROUGH)
    if previously_viewed and last<=PUBLISHED_THROUGH:
        reason='Research only: the 15-minute hold is active, but this candle history was already inspected. It cannot authorize entries.'
    elif eligible:
        reason='Chart cost tests passed on bars after the previously inspected sample; current news and execution checks still required.'
    else:
        reason='Research only: positive expectancy is not established on unseen bars across holdout periods, daily bootstrap uncertainty and doubled costs (minimum 50 trades / 10 traded sessions).'
    report={'broker':bridge.BROKER_NAME,'engine':ENGINE,'symbol':symbol,'created_at':time.time(),'bars':len(d),
            'first_bar':float(d.time.iloc[0]),'last_bar':last,'holdout_start':cutoff,
            'holdout':summary,'stress':stats(stress),'chronological_folds':folds,
            'traded_sessions':sessions,'expectancy_lower_95':lower,'eligible':eligible,'reason':reason,
            'live_exit_validated':False,
            'execution_policy':EXIT_POLICY,
            'setup_breakdown':{name:stats(group) for name,group in holdout.groupby('setup')} if not holdout.empty else {},
            'development':stats(normal[normal.exit_time<cutoff-purge]) if not normal.empty else stats(normal),
            'purge_seconds':purge,
            'exit_breakdown':holdout.exit_reason.value_counts().to_dict() if not holdout.empty else {},
            'evaluation_note':('Previously viewed history under the 15-minute hold: diagnostic only, not authorization.'
                               if previously_viewed else
                               '15-minute hold evaluated on bars after the archived five-minute study.'),
            'limitations':'Chart-only test. Historical point-in-time news, economic calendar, DXY, yields and futures order flow are not available. Spread is bar-reported; slippage and commissions are assumptions. Rules were fixed before evaluation; repeated research can contaminate holdout.'}
    return report,normal

"""Local learned directional outlook on XM candles. Never submits orders."""
import time
import math
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator

HORIZON = 5
FEATURES = ['return1', 'return5', 'return15', 'return30', 'return60', 'trend', 'trend_long',
            'atr_pct', 'atr_ratio', 'range_position', 'breakout_up', 'breakout_down',
            'rsi14', 'volatility15', 'volatility60', 'momentum_change', 'activity', 'spread_pct']
MODEL_VERSION='conditional-direction-cost-policy-v4'


def features(bars, point, horizon=HORIZON):
    if horizon not in (5,15,30,60):
        raise ValueError('Unsupported forecast horizon')
    d = bars.copy().sort_values('time').drop_duplicates('time').reset_index(drop=True)
    numeric = ['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread']
    d[numeric] = d[numeric].apply(pd.to_numeric, errors='coerce')
    d = d.replace([np.inf, -np.inf], np.nan).dropna(subset=numeric)
    d = d[(d.low > 0) & (d.tick_volume >= 0) & (d.spread >= 0)
          & (d.high >= d[['open', 'close', 'low']].max(axis=1))
          & (d.low <= d[['open', 'close']].min(axis=1))].reset_index(drop=True)
    d['segment'] = d.time.diff().ne(60).cumsum()
    parts = []
    for _, g in d.groupby('segment'):
        g = g.copy()
        for period in (1, 5, 15, 30, 60):
            g[f'return{period}'] = g.close.pct_change(period)
        g['ema9'] = g.close.ewm(span=9, min_periods=9, adjust=False).mean()
        g['ema21'] = g.close.ewm(span=21, min_periods=21, adjust=False).mean()
        g['trend'] = (g.ema9 - g.ema21) / g.close
        g['ema50'] = g.close.ewm(span=50, min_periods=50, adjust=False).mean()
        g['trend_long'] = (g.ema21 - g.ema50) / g.close
        tr = pd.concat([g.high-g.low, (g.high-g.close.shift()).abs(), (g.low-g.close.shift()).abs()], axis=1).max(axis=1)
        g['atr'] = tr.rolling(14).mean()
        g['atr_pct'] = g.atr/g.close
        g['atr_long'] = tr.rolling(60).mean()
        g['atr_ratio'] = g.atr/g.atr_long.replace(0, np.nan)
        g['support'] = g.low.shift().rolling(20).min()
        g['resistance'] = g.high.shift().rolling(20).max()
        width = (g.resistance-g.support).replace(0, np.nan)
        g['range_position'] = (g.close-g.support)/width
        g['breakout_up'] = (g.close-g.resistance)/g.atr
        g['breakout_down'] = (g.support-g.close)/g.atr
        delta=g.close.diff()
        gain=delta.clip(lower=0).ewm(alpha=1/14,min_periods=14,adjust=False).mean()
        loss=(-delta.clip(upper=0)).ewm(alpha=1/14,min_periods=14,adjust=False).mean()
        rs=gain/loss.replace(0,np.nan)
        g['rsi14']=100-(100/(1+rs))
        g.loc[(loss==0)&(gain>0),'rsi14']=100
        g['volatility15']=g.return1.rolling(15).std()
        g['volatility60']=g.return1.rolling(60).std()
        g['momentum_change']=g.return5-g.return15/3
        g['activity'] = g.tick_volume/g.tick_volume.shift().rolling(20).mean().replace(0, np.nan)
        g['spread_pct'] = g.spread*point/g.close
        g['future_return'] = g.close.shift(-horizon)/g.close-1
        g['label_end'] = g.time.shift(-horizon)
        # Neutral zone includes recorded spread and an explicit 2 bp cost allowance.
        hurdle = g.spread_pct + .0002
        g['label'] = np.where(g.future_return > hurdle, 1, np.where(g.future_return < -hurdle, -1, 0))
        g.loc[g.future_return.isna(), 'label'] = np.nan
        parts.append(g)
    return pd.concat(parts).sort_values('time').reset_index(drop=True).replace([np.inf, -np.inf], np.nan) if parts else d


def diagnostic(labels, predicted):
    counts={c:int(np.sum(labels==c)) for c in (-1,0,1)}
    recalls={c:float(np.mean(predicted[labels==c]==c)) if counts[c] else 0.0 for c in counts}
    return {'class_counts':counts, 'class_recall':recalls,
            'balanced_accuracy':sum(recalls.values())/3,
            'evidence_sufficient':min(counts.values())>=20}


def independent_rows(frame, horizon):
    """Decision bars spaced far enough apart for their future windows not to overlap."""
    frame=frame.reset_index(drop=True)
    keep=[]
    next_time=-np.inf
    for i,row in frame.iterrows():
        if row.time>=next_time:
            future=frame.iloc[i+1:i+horizon+1]
            if len(future)==horizon and future.segment.eq(row.segment).all() and future.time.iloc[-1]==row.time+horizon*60:
                keep.append(i)
                next_time=row.time+horizon*60
    return np.asarray(keep,dtype=int)


def replay(frame, indices, probabilities, classes, threshold, point, horizon):
    """Simulate the configured ATR stop / 2R target over later bars, stop-first ties."""
    probs={int(c):probabilities[:,i] for i,c in enumerate(classes)}
    entries=[]
    for j,i in enumerate(indices):
        row=frame.iloc[int(i)]
        p_up=float(probs.get(1,np.zeros(len(indices)))[j])
        p_down=float(probs.get(-1,np.zeros(len(indices)))[j])
        winner=1 if p_up>=p_down else -1
        direction=int(winner) if max(p_up,p_down)>=threshold else 0
        if direction==0:
            continue
        future=frame.iloc[int(i)+1:int(i)+horizon+1]
        spread=float(row.spread*point)
        entry=float(row.close+spread if direction==1 else row.close)
        structure=float(entry-row.support if direction==1 else row.resistance-entry)
        risk=max(1.5*float(row.atr),min(max(structure,0),3*float(row.atr)),spread+point*2)
        reward=max(2*risk,2*float(row.atr))
        stop=entry-direction*risk
        target=entry+direction*reward
        exit_price=None
        for _,bar in future.iterrows():
            bar_spread=float(bar.spread*point)
            stopped=(bar.low<=stop if direction==1 else bar.high+bar_spread>=stop)
            targeted=(bar.high>=target if direction==1 else bar.low+bar_spread<=target)
            if stopped:
                exit_price=stop; break
            if targeted:
                exit_price=target; break
        if exit_price is None:
            last=future.iloc[-1]
            exit_price=float(last.close if direction==1 else last.close+last.spread*point)
        gross=direction*(exit_price-entry)/entry
        net=(gross-.0002)*10000
        entries.append({'net_bps':net,'win':net>0,'direction':direction,'time':int(row.time)})
    return entries


def policy_report(entries):
    if not entries:
        return {'trades':0,'mean_net_bps':None,'win_rate':None,'lower_90_bps':None}
    net=np.array([e['net_bps'] for e in entries],dtype=float)
    mean=float(net.mean())
    lower=mean-1.645*(float(net.std(ddof=1))/math.sqrt(len(net))) if len(net)>1 else float('-inf')
    return {'trades':len(net),'mean_net_bps':mean,'win_rate':float(np.mean(net>0)),
            'lower_90_bps':lower,'profit_factor':float(net[net>0].sum()/abs(net[net<0].sum())) if np.any(net<0) else None}


class ConditionalModel:
    """Calibrated chance of a directional move times its conditional direction."""
    classes_=np.array([-1,0,1],dtype=int)
    def __init__(self,event_model,direction_model):
        self.event_model=event_model
        self.direction_model=direction_model
    def predict_proba(self,x):
        event_classes=list(self.event_model.classes_)
        event_col=event_classes.index(1)
        event_probability=self.event_model.predict_proba(x)[:,event_col]
        direction_classes=list(self.direction_model.classes_)
        directional=self.direction_model.predict_proba(x)
        up=directional[:,direction_classes.index(1)]*event_probability
        down=directional[:,direction_classes.index(-1)]*event_probability
        neutral=1-event_probability
        return np.column_stack([down,neutral,up])


def calibrated(base,fit_x,fit_y,cal_x,cal_y,weights=None):
    if weights is None:
        base.fit(fit_x,fit_y)
    else:
        base.fit(fit_x,fit_y,sample_weight=weights)
    model=CalibratedClassifierCV(FrozenEstimator(base),method='sigmoid')
    model.fit(cal_x,cal_y)
    return model


def train(bars, point, horizon=HORIZON):
    # Reset after filtering: replay uses these indexes as frame positions, so
    # retaining feature-frame labels here can point past the filtered frame.
    d = features(bars, point, horizon).dropna(subset=FEATURES+['label', 'label_end']).reset_index(drop=True)
    if len(d) < 800:
        return {'ready': False, 'reason': f'Need 800 usable candles; currently {len(d)}. Open the instrument’s M1 chart in MT5 to load more history.'}
    boundary = float(d.iloc[int(len(d)*.7)].time)
    training = d[d.label_end < boundary]
    # Keep every later row here; independent event samples are selected after splitting.
    candidates = d[d.time >= boundary]
    test = candidates
    if len(test) < 40 or training.label.nunique() < 2:
        return {'ready': False, 'reason': 'Not enough varied history or independent test outcomes yet.'}
    # Reserve the last fifth of the training period for probability calibration and
    # policy selection. Purge labels crossing the inner boundary.
    calibration_boundary=float(training.iloc[int(len(training)*.8)].time)
    core=training[training.label_end<calibration_boundary]
    calibration=training[training.time>=calibration_boundary]
    if len(core)<300 or len(calibration)<100 or core.label.nunique()<2 or calibration.label.nunique()<3:
        return {'ready':False,'reason':'Not enough chronological history to fit and calibrate the trade model.'}
    core_direction=core[core.label!=0]
    calibration_direction=calibration[calibration.label!=0]
    if len(core_direction)<100 or core_direction.label.nunique()<2 or len(calibration_direction)<30 or calibration_direction.label.nunique()<2:
        return {'ready':False,'reason':'Not enough examples of both directional outcomes to calibrate the entry model.'}
    calibration_indices=independent_rows(calibration,horizon)
    test_indices=independent_rows(test,horizon)
    cal_x=calibration[FEATURES]
    cal_event_y=(calibration.label!=0).astype(int)
    cal_direction_y=calibration_direction.label.astype(int)
    # Cap fitting cost while retaining examples from the full chronological core.
    # Calibration and the untouched holdout continue to use all eligible rows.
    fit_core=core.iloc[np.linspace(0,len(core)-1,min(len(core),12000),dtype=int)]
    fit_core_direction=fit_core[fit_core.label!=0]
    if fit_core.label.nunique()<2 or fit_core_direction.label.nunique()<2:
        return {'ready':False,'reason':'The sampled chronological training core lacks both event and direction classes.'}
    # Compare two tree families on the calibration interval only. The outer test is
    # used once, after the model and entry threshold have been selected.
    factories=[
        ('Random forest',lambda:RandomForestClassifier(n_estimators=80,max_depth=6,min_samples_leaf=24,
            class_weight='balanced',random_state=42,n_jobs=2)),
        ('Extra trees',lambda:ExtraTreesClassifier(n_estimators=100,max_depth=6,min_samples_leaf=24,
            class_weight='balanced',random_state=43,n_jobs=2))]
    choices=[]
    fallback_model=None
    for name,factory in factories:
        event_model=calibrated(factory(),fit_core[FEATURES],(fit_core.label!=0).astype(int),cal_x,cal_event_y)
        direction_model=calibrated(factory(),fit_core_direction[FEATURES],fit_core_direction.label.astype(int),
                                   calibration_direction[FEATURES],cal_direction_y)
        candidate=ConditionalModel(event_model,direction_model)
        fallback_model=candidate
        cal_prob=candidate.predict_proba(calibration.iloc[calibration_indices][FEATURES])
        scores=np.max(cal_prob[:,[0,2]],axis=1)
        thresholds=np.unique(np.quantile(scores,[.35,.45,.55,.65,.75,.85,.92,.97]))
        for threshold in thresholds:
            outcomes=replay(d,calibration.index.to_numpy()[calibration_indices],cal_prob,candidate.classes_,float(threshold),point,horizon)
            report=policy_report(outcomes)
            if report['trades']>=30 and report['mean_net_bps'] is not None:
                choices.append((report['mean_net_bps'],name,float(threshold),report,candidate))
    chosen=max(choices,key=lambda x:x[0]) if choices else None
    if chosen:
        _,model_name,threshold,calibration_policy,model=chosen
        test_prob=model.predict_proba(test.iloc[test_indices][FEATURES])
    else:
        model=fallback_model;model_name=None;threshold=None;calibration_policy=None
        test_prob=model.predict_proba(test.iloc[test_indices][FEATURES])
    classes=ConditionalModel.classes_
    pred=classes[np.argmax(test_prob,axis=1)]
    test_labels=test.iloc[test_indices].label.to_numpy()
    accuracy=float(np.mean(pred==test_labels))
    majority = int(training.label.mode().iloc[0])
    baseline = float(np.mean(test_labels == majority))
    diagnostics=diagnostic(test_labels,pred)
    validation=policy_report([]) if chosen is None else policy_report(replay(d,test.index.to_numpy()[test_indices],test_prob,classes,threshold,point,horizon))
    policy_validated=bool(chosen is not None and validation['trades']>=50 and validation['mean_net_bps'] is not None and validation['lower_90_bps']>0)
    max_calibration_spread_bps=float(calibration.spread_pct.quantile(.95)*10000)
    return {'ready': True, 'version':MODEL_VERSION, 'model': model, 'model_name':model_name, 'accuracy': accuracy, 'baseline': baseline,
            **diagnostics, 'horizon':horizon,
            'threshold':threshold,'calibration_policy':calibration_policy,
            'validation':validation,'policy_validated':policy_validated,
            'max_calibration_spread_bps':max_calibration_spread_bps,
            'policy_reason':('No model and calibrated threshold produced 30 distinct calibration-period trades.' if chosen is None else
                f"Later untouched holdout had {validation['trades']} simulated trades; at least 50 are required." if validation['trades']<50 else
                f"Later untouched holdout mean was {validation['mean_net_bps']:.2f} bps/trade with a 90% lower bound of {validation['lower_90_bps']:.2f} bps; the lower bound must be positive." if not policy_validated else
                'Threshold selected on a past calibration period and retained positive lower 90% net-expectancy bound on a later holdout.'),
            'core_count':len(core),'fit_count':len(fit_core),'calibration_count':len(calibration),
            'calibration_classes':{int(k):int(v) for k,v in calibration.label.value_counts().items()},
            'train_class_counts':{int(k):int(v) for k,v in training.label.value_counts().items()},
            'test_count': len(test_indices), 'train_count': len(training), 'boundary': boundary,
            'training_label_end': float(training.label_end.max()), 'trained_at': time.time(),
            'test_start': float(test.time.min()), 'test_end': float(test.label_end.max())}


def assess(bars, point, fitted, bid, ask, server_now, min_stop=0):
    d = features(bars, point, fitted.get('horizon',HORIZON))
    result = {'frame': d, 'action': 'WAIT', 'reasons': [], 'ready': False}
    if d.empty:
        result['reasons'] = ['No completed XM candles are available.']
        return result
    row = d.iloc[-1]
    age = server_now-(row.time+60)
    if not 0 <= age <= 90:
        result['reasons'] = [f'Latest completed XM candle is not current (age {age:.0f}s).']
        return result
    if not np.isfinite(row[FEATURES].to_numpy(dtype=float)).all():
        result['reasons'] = ['Need at least 61 consecutive candles after the latest data gap.']
        return result
    if not fitted['ready']:
        result['reasons'] = [fitted['reason']]
        return result
    probabilities = fitted['model'].predict_proba(d.iloc[[-1]][FEATURES])[0]
    scores = {int(c): float(p) for c, p in zip(fitted['model'].classes_, probabilities)}
    direction = 1 if scores[1]>=scores[-1] else -1
    spread = ask-bid
    bias_direction=direction if scores[direction]>scores[0] else 0
    result.update(ready=True, scores=scores, bias={1:'BUY bias', -1:'SELL bias',0:'NEUTRAL'}[bias_direction],
                  directional_probability=float(scores[direction]),
                  calibrated=True, threshold=fitted.get('threshold'))
    horizon=fitted.get('horizon',HORIZON)
    result['reasons'].append(f'EMA 9 is {"above" if row.ema9 > row.ema21 else "below"} EMA 21; last {horizon}-minute move {row[f"return{horizon}"]*100:+.2f}%.')
    result['reasons'].append(f'Current spread {spread:.6g}; average one-minute true range {row.atr:.6g}; tick activity {row.activity:.2f}× recent average.')
    blockers = []
    if fitted.get('policy_validated', True) is False:
        result['action']='MODEL NOT VALIDATED'
        blockers.append(fitted.get('policy_reason','The held-out cost-aware policy has not been validated.'))
    elif scores.get(direction,0)<fitted.get('threshold',0):
        blockers.append(f"Joint probability for a {('buy' if direction==1 else 'sell')} setup is below the learned {fitted['threshold']:.0%} threshold selected on earlier data.")
    current_spread_bps=spread/float(row.close)*10000
    if current_spread_bps>fitted.get('max_calibration_spread_bps',float('inf')):
        blockers.append('Current spread is outside the 95th-percentile range seen during policy calibration.')
    if fitted.get('policy_validated', True) and not blockers:
        result['action'] = 'BUY setup' if direction == 1 else 'SELL setup'
    result['reasons'] += blockers
    result['scenarios'] = {}
    for side, sign, entry in [('BUY', 1, ask), ('SELL', -1, bid)]:
        structure = entry-row.support if sign == 1 else row.resistance-entry
        risk = max(1.5*row.atr, min(max(structure, 0), 3*row.atr), spread+min_stop+point*2)
        reward = max(2*risk, 2*row.atr)
        result['scenarios'][side] = {'entry': float(entry), 'sl': float(entry-sign*risk), 'tp': float(entry+sign*reward),
                                     'sl_bps': float(risk/entry*10000), 'tp_bps': float(reward/entry*10000)}
    return result


def snapshot(identity, symbol, offset, horizon=5):
    import streamlit as st
    from .mt5_demo import LOCK, api, checked_account, quote, DemoError

    @st.cache_data(ttl=60, show_spinner=False)
    def history(identity, symbol, offset):
        with LOCK:
            mt5 = api()
            checked_account(mt5, identity)
            if not mt5.symbol_select(symbol, True):
                raise DemoError('Cannot subscribe to this XM instrument.')
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, 50000)
            if rates is None or not len(rates):
                raise DemoError('XM candle history is not loaded. Open this instrument’s M1 chart in MT5, then retry.')
            bars = pd.DataFrame(rates)
            return bars[bars.time+60 <= time.time()+offset*3600]

    @st.cache_resource(ttl=3600, max_entries=120, show_spinner=False)
    def fit_cached(identity, symbol, offset, bucket, point, horizon, model_version, _bars):
        return train(_bars, point, horizon)

    bars = history(tuple(identity), symbol, offset)
    with LOCK:
        mt5 = api()
        checked_account(mt5, identity)
        info = mt5.symbol_info(symbol)
        if info is None:
            raise DemoError('Instrument specifications unavailable.')
        tick = quote(mt5, symbol, offset)
    fitted = fit_cached(tuple(identity), symbol, offset, int(time.time()//3600), info.point, horizon, MODEL_VERSION, bars)
    # Training can take long enough for the cached history tail to become stale.
    # Keep the large cached frame for fitting, but assess against a fresh MT5 tail.
    with LOCK:
        mt5 = api()
        checked_account(mt5, identity)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, 180)
        if rates is None or not len(rates):
            raise DemoError('Cannot refresh the latest completed XM candles. Open this instrument’s M1 chart in MT5, then retry.')
        live_bars = pd.DataFrame(rates)
        live_bars = live_bars[live_bars.time+60 <= time.time()+offset*3600]
        tick = quote(mt5, symbol, offset)
    result = assess(live_bars, info.point, fitted, tick.bid, tick.ask, time.time()+offset*3600, info.trade_stops_level*info.point)
    result['observed_at']=time.time()
    return result, fitted


def render(identity, symbol, offset):
    import streamlit as st
    import plotly.graph_objects as go
    from .mt5_demo import DemoError
    st.markdown('### XM AI analysis')
    st.caption('Local machine-learning model trained on this exact XM instrument. No API key required. Demo research only.')
    horizon=st.selectbox('Forecast horizon (minutes)',[5,15,30,60],key='xm_ai_horizon')
    try:
        with st.spinner('Learning from XM candles and checking later historical outcomes…'):
            result, fitted = snapshot(identity, symbol, offset, horizon)
        st.metric('Demo research decision', result['action'])
        if result['ready']:
            st.write(f"**Model outlook: {result['bias']}**")
            cols = st.columns(3)
            for col, label, code in zip(cols, ['Up score', 'Neutral score', 'Down score'], [1,0,-1]):
                col.metric(label, f"{result['scores'].get(code,0):.0%}")
            if result.get('calibrated') and result.get('threshold') is not None:
                st.caption(f"Calibrated probability of a cost-clearing move in this direction · learned entry threshold: {result['threshold']:.1%} · {horizon}-minute forecast")
        for reason in result['reasons']:
            st.write('• '+reason)
        chart = result['frame'].tail(180)
        if not chart.empty:
            x = pd.to_datetime(chart.time, unit='s')
            fig = go.Figure(go.Candlestick(x=x, open=chart.open, high=chart.high, low=chart.low, close=chart.close, name=symbol))
            for field in ['ema9','ema21']:
                fig.add_scatter(x=x, y=chart[field], name=field.upper(), mode='lines', connectgaps=False)
            fig.update_layout(height=400, template='plotly_dark', xaxis_rangeslider_visible=False, uirevision=symbol,
                              title=f'{symbol} · XM M1 candles · broker server time')
            st.plotly_chart(fig, width='stretch', key='xm_ai_chart')
        if fitted['ready']:
            report=fitted.get('validation',{})
            st.caption(f"Cost-aware, later holdout: {report.get('trades',0)} simulated non-overlapping trades; mean net {report.get('mean_net_bps') if report.get('mean_net_bps') is not None else float('nan'):.2f} bps; 90% lower bound {report.get('lower_90_bps') if report.get('lower_90_bps') is not None else float('nan'):.2f} bps. Probability calibration and entry threshold were fitted on earlier data. This later holdout was not used to choose the threshold.")
            with st.expander('Why the model is or is not validated'):
                st.dataframe(pd.DataFrame([{'Outcome':label,'Training examples':fitted['train_class_counts'].get(c,0),
                    'Test examples':fitted['class_counts'][c],'Test recall':fitted['class_recall'][c]}
                    for c,label in [(1,'Up beyond costs'),(0,'Inside cost band'),(-1,'Down beyond costs')]]),hide_index=True)
                st.write(f"Earlier calibration selected {fitted.get('threshold')} as the cutoff with best net expectancy among tested cutoffs. Calibration result: {fitted.get('calibration_policy')}. Later untouched holdout: {report}. Policy gate: {fitted['policy_reason']}")
                st.caption('The holdout simulates the configured volatility stop and 2R target, subtracts recorded spread plus a 2 bp allowance, and closes unresolved trades at the chosen horizon. It still cannot establish future profitability. Keep checking fresh forward results.')
        st.caption('Local, calibrated two-stage tree models compare the chance of a cost-clearing move and its direction using returns, trend, volatility, breakouts, RSI, tick activity and spread. A model and probability threshold are selected on earlier data; a later untouched, cost-aware trade replay must pass before signals are enabled. It does not include news, order-book depth or macro calendars. This is demo research; fills, fees and gaps can differ. Existing Alpaca models remain separate.')
        if result.get('scenarios'):
            st.write('**Dynamic scenarios — based on XM volatility, recent price levels and spread**')
            st.dataframe(pd.DataFrame(result['scenarios']).T[['entry','sl','tp']], width='stretch')
            st.caption('Scenarios use a 2:1 target/risk distance. They are illustrative, not optimized or guaranteed. The broker checks final rounded prices before submission.')
        return result.get('scenarios', {})
    except DemoError as exc:
        st.warning(str(exc))
        return {}

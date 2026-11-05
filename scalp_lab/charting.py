"""Observed chart structure, separate from model trade qualification."""
import numpy as np
import pandas as pd


def prepare_chart(bars, minutes=1, now=None):
    if minutes not in (1,5,15):
        raise ValueError("Supported chart intervals: 1, 5, 15 minutes")
    if bars is None or bars.empty:
        return pd.DataFrame()
    d=bars.copy()
    d["timestamp"]=pd.to_datetime(d.timestamp,utc=True,errors="coerce")
    for col in ("open","high","low","close","volume"):
        d[col]=pd.to_numeric(d[col],errors="coerce")
    d=d.replace([np.inf,-np.inf],np.nan).dropna(subset=["timestamp","open","high","low","close","volume"])
    current=pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    current=current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    d=d[(d.timestamp+pd.Timedelta(minutes=1)<=current)&(d.low>0)&(d.volume>=0)&(d.high>=d[["open","close","low"]].max(axis=1))&(d.low<=d[["open","close"]].min(axis=1))]
    d=d.sort_values("timestamp").drop_duplicates("timestamp",keep="last")
    ny=d.timestamp.dt.tz_convert("America/New_York")
    minute=ny.dt.hour*60+ny.dt.minute
    d=d[(minute>=570)&(minute<960)&(ny.dt.dayofweek<5)].copy()
    if d.empty:
        return d
    d["session"]=d.timestamp.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    # A bar-based VWAP estimate from observed minute bars, not trade-level VWAP.
    d["pv"]=(d.high+d.low+d.close)/3*d.volume
    d["vwap"]=d.groupby("session").pv.cumsum()/d.groupby("session").volume.cumsum().replace(0,np.nan)
    pieces=[]
    for _,session in d.groupby("session",sort=False):
        frame=session.set_index("timestamp").resample(f"{minutes}min",label="left",closed="left").agg(
            open=("open","first"),high=("high","max"),low=("low","min"),close=("close","last"),
            volume=("volume","sum"),vwap=("vwap","last"),count=("close","count"))
        frame=frame[frame["count"]==minutes].drop(columns="count").reset_index()
        pieces.append(frame)
    d=pd.concat(pieces,ignore_index=True)
    if d.empty:
        return d
    d=d[d.timestamp+pd.Timedelta(minutes=minutes)<=current].copy()
    segments=(d.timestamp.diff()!=pd.Timedelta(minutes=minutes)).cumsum()
    d["segment"]=segments
    for span in (9,21):
        d[f"ema{span}"]=d.groupby("segment").close.transform(lambda x:x.ewm(span=span,adjust=False,min_periods=span).mean())
    def rsi(close):
        change=close.diff()
        gain=pd.Series(np.nan,index=close.index)
        loss=pd.Series(np.nan,index=close.index)
        if len(close)<15:
            return gain
        gain.iloc[14]=change.iloc[1:15].clip(lower=0).mean()
        loss.iloc[14]=(-change.iloc[1:15].clip(upper=0)).mean()
        for i in range(15,len(close)):
            gain.iloc[i]=(gain.iloc[i-1]*13+max(change.iloc[i],0))/14
            loss.iloc[i]=(loss.iloc[i-1]*13+max(-change.iloc[i],0))/14
        value=100-100/(1+gain/loss.replace(0,np.nan))
        value=value.mask((loss==0)&(gain>0),100).mask((loss==0)&(gain==0),50)
        return value
    d["rsi"]=d.groupby("segment").close.transform(rsi)
    # Prior levels exclude the bar being assessed.
    d["support"]=d.groupby("segment").low.transform(lambda x:x.shift().rolling(20,min_periods=20).min())
    d["resistance"]=d.groupby("segment").high.transform(lambda x:x.shift().rolling(20,min_periods=20).max())
    baseline=d.groupby("segment").volume.transform(lambda x:x.shift().rolling(20,min_periods=20).mean())
    d["volume_ratio"]=d.volume/baseline.replace(0,np.nan)
    return d.reset_index(drop=True)


def analyze_chart(frame, minutes=1, now=None):
    if frame.empty:
        return {"available":False,"reason":"Waiting for completed regular-session candles"}
    row=frame.iloc[-1]
    current=pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    current=current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    closed=row.timestamp+pd.Timedelta(minutes=minutes)
    stale=(current-closed).total_seconds()>=max(90,minutes*60+30)
    values=[row.ema9,row.ema21,row.vwap,row.rsi,row.support,row.resistance]
    ready=bool(np.isfinite(values).all())
    if not ready:
        return {"available":False,"reason":"Indicators are warming up after a session start or missing candle. Need 21 consecutive candles.","stale":stale,"as_of":str(closed)}
    trend="Mixed / sideways"
    if row.close>row.ema9>row.ema21 and row.close>row.vwap:
        trend="Bullish chart structure"
    elif row.close<row.ema9<row.ema21 and row.close<row.vwap:
        trend="Bearish chart structure"
    structure="Inside the preceding 20-candle range"
    if row.close>row.resistance:
        structure="Closed above the preceding 20-candle high"
    elif row.close<row.support:
        structure="Closed below the preceding 20-candle low"
    position="above" if row.close>row.vwap else "below" if row.close<row.vwap else "at"
    momentum="positive" if row.rsi>55 else "negative" if row.rsi<45 else "mixed"
    return {"available":True,"trend":trend,"stale":stale,"as_of":str(closed),"support":float(row.support),
            "resistance":float(row.resistance),"rsi":float(row.rsi),"volume_ratio":float(row.volume_ratio) if np.isfinite(row.volume_ratio) else None,
            "summary":f"Price is {position} the observed-session VWAP; RSI momentum is {momentum} ({row.rsi:.1f}). {structure}.",
            "long_condition":f"Bullish continuation to watch: a close above ${row.resistance:.4f} with price above EMA 9, EMA 21 and VWAP.",
            "short_condition":f"Bearish continuation to watch: a close below ${row.support:.4f} with price below EMA 9, EMA 21 and VWAP."}


def make_figure(frame,symbol,minutes=1,candles=180,overlay=None):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    d=frame.tail(candles).copy()
    # Date axis retains missing minutes; no fabricated candles.
    x=d.timestamp.dt.tz_convert("America/New_York").dt.tz_localize(None)
    fig=make_subplots(rows=3,cols=1,shared_xaxes=True,vertical_spacing=0.035,row_heights=[0.65,0.18,0.17])
    fig.add_trace(go.Candlestick(x=x,open=d.open,high=d.high,low=d.low,close=d.close,name=symbol,
                                increasing_line_color="#61c6a5",decreasing_line_color="#e38a80"),row=1,col=1)
    for field,name,color in (("ema9","EMA 9","#e8ba69"),("ema21","EMA 21","#a2b9de"),("vwap","Session VWAP estimate","#b9a2d8")):
        fig.add_trace(go.Scatter(x=x,y=d[field],name=name,line=dict(color=color,width=1.4),connectgaps=False),row=1,col=1)
    for field,color in (("support","#61c6a5"),("resistance","#e38a80")):
        if np.isfinite(d.iloc[-1][field]):
            fig.add_hline(y=float(d.iloc[-1][field]),line_dash="dot",line_color=color,annotation_text=f"Prior 20-candle {field}",row=1,col=1)
    if overlay:
        for field,label,color in (("reference_price","Scenario entry","#d0d4dc"),("take_profit","Scenario target","#61c6a5"),("stop_loss","Scenario stop","#e38a80")):
            fig.add_hline(y=overlay[field],line_dash="dash",line_color=color,annotation_text=label,row=1,col=1)
    colors=np.where(d.close>=d.open,"#61c6a5","#e38a80")
    fig.add_trace(go.Bar(x=x,y=d.volume,marker_color=colors,name="Volume",showlegend=False),row=2,col=1)
    fig.add_trace(go.Scatter(x=x,y=d.rsi,name="RSI 14",line=dict(color="#b9a2d8",width=1.5),showlegend=False),row=3,col=1)
    for value in (30,70):
        fig.add_hline(y=value,line_dash="dot",line_color="#777f90",row=3,col=1)
    fig.update_yaxes(title_text="USD",row=1,col=1)
    fig.update_yaxes(title_text="Volume",row=2,col=1)
    fig.update_yaxes(title_text="RSI",range=[0,100],row=3,col=1)
    fig.update_xaxes(rangeslider_visible=False,rangebreaks=[dict(bounds=["sat","mon"]),dict(bounds=[16,9.5],pattern="hour")])
    fig.update_layout(height=660,margin=dict(l=15,r=20,t=40,b=20),template="plotly_dark",
                      paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h",y=1.04),hovermode="x unified",
                      uirevision=f"{symbol}-{minutes}-{candles}")
    return fig


def render_chart(bars,symbol,settings,report):
    import streamlit as st
    from .signals import adaptive_distances,paper_levels
    st.subheader("Price chart and technical reading")
    left,middle,right=st.columns(3)
    with left:
        minutes=st.selectbox("Candle interval",[1,5,15],format_func=lambda x:f"{x} minute" if x==1 else f"{x} minutes",key=f"chart_interval_{symbol}")
    with middle:
        count=st.selectbox("Visible candles",[90,180,390],index=1,key=f"chart_count_{symbol}")
    with right:
        scenario=st.selectbox("Price-level overlay",["None","Long scenario","Short scenario"],key=f"chart_overlay_{symbol}")
    frame=prepare_chart(bars,minutes)
    if frame.empty:
        st.info("Waiting for completed candles at this interval. No prices are invented to fill gaps.")
        return
    analysis=analyze_chart(frame,minutes)
    overlay=None
    if scenario!="None":
        dynamic=adaptive_distances(bars,horizon=int(report.get("horizon_minutes",5)),cost_bps=float(settings.get("roundtrip_cost_bps",0)))
        if dynamic["available"]:
            overlay=paper_levels(float(frame.iloc[-1].close),"PAPER_LONG" if scenario=="Long scenario" else "PAPER_SHORT",dynamic["tp_bps"],dynamic["sl_bps"])
            st.caption("Overlay is a hypothetical scenario using dynamic one-minute-bar distances and the last visible candle close; it is not an active model signal or confirmed entry.")
        else:
            st.caption("Scenario overlay unavailable: "+dynamic["reason"])
    st.caption(f"{symbol} | {minutes}-minute candles | Chart times: New York")
    st.plotly_chart(make_figure(frame,symbol,minutes,count,overlay),width="stretch",key=f"price_chart_{symbol}",config={"displaylogo":False,"scrollZoom":True})
    st.caption("Regular-session candles from your selected feed. Updates automatically; drag to zoom, double-click to reset. Missing minutes remain gaps. VWAP is estimated from the minute bars available, not every market trade.")
    if analysis.get("stale"):
        st.warning(f"Historical chart reading: latest completed candle closed at {analysis['as_of']}. This is not a current-market prediction.")
    if not analysis["available"]:
        st.info(analysis["reason"])
        return
    st.markdown(f"**{analysis['trend']}**")
    st.write(analysis["summary"])
    a,b=st.columns(2)
    a.metric("Prior-range low",f"${analysis['support']:.4f}")
    b.metric("Prior-range high",f"${analysis['resistance']:.4f}")
    c,d=st.columns(2)
    c.metric("RSI 14",f"{analysis['rsi']:.1f}")
    d.metric("Volume / prior 20 candles","Unavailable" if analysis["volume_ratio"] is None else f"{analysis['volume_ratio']:.2f}x")
    st.write(analysis["long_condition"])
    st.write(analysis["short_condition"])
    st.caption("This rule-based description explains observed price action. It has not been validated as a buy/sell strategy and does not enable a disabled model.")

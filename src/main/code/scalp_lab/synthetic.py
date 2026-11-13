"""Only for tests and smoke demos; deliberately NOT a predictive dataset."""
import numpy as np
import pandas as pd


def generate_demo(days=60, seed=17):
    rng=np.random.default_rng(seed)
    sessions=pd.bdate_range("2026-04-01",periods=days)
    stamps=[]
    for day in sessions:
        start=pd.Timestamp(f"{day.strftime('%Y-%m-%d')} 09:30",tz="America/New_York")
        stamps.extend(pd.date_range(start, periods=390, freq="min").tz_convert("UTC"))
    n=len(stamps)
    # Random-ish with weak autocorrelation and volatility clustering. Never presented as real data.
    impulses=rng.normal(0, 0.00044, size=n)
    rets=np.zeros(n)
    for i in range(1,n):
        rets[i]=0.08*rets[i-1]+impulses[i]
    prices=100*np.exp(np.cumsum(rets))
    opens=np.r_[100.0,prices[:-1]]
    closes=prices
    wicks=np.abs(rng.normal(0.00013,0.00008,n))
    highs=np.maximum(opens,closes)*(1+wicks)
    lows=np.minimum(opens,closes)*(1-wicks)
    volumes=rng.integers(40,1500,size=n)
    d=pd.DataFrame(dict(timestamp=stamps,open=opens,high=highs,low=lows,close=closes,volume=volumes))
    events=[]
    for i in range(300,len(d),820):
        events.append(dict(created_at=d.iloc[i]["timestamp"],headline=rng.choice(["Company reports strong profit growth","Firm faces investigation after losses","Analyst discusses new product launch","Market outlook unchanged"])))
    return d,pd.DataFrame(events)

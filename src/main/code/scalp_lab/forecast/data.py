"""Validate MT5 bar opens in UTC and build bounded, causal features."""
import numpy as np
import pandas as pd

COLUMNS = ['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread']
HORIZONS = (1, 3, 5, 15)
WINDOW = 61
GROUPS = {
    'price': ['r1', 'r3', 'r5', 'r15', 'r60', 'vol15', 'vol60', 'atr', 'rsi',
              'trend', 'momentum', 'body', 'upper', 'lower', 'range_position'],
    'context': ['spread_bps', 'activity', 'hour_sin', 'hour_cos'],
}
FEATURES = GROUPS['price'] + GROUPS['context']


def completed(raw, now, offset=0):
    """Normalize MT5 timestamps and reject malformed or conflicting observations."""
    if raw is None or len(raw) == 0:
        raise ValueError('Market data unavailable.')
    bars = pd.DataFrame(raw)
    if not set(COLUMNS).issubset(bars):
        raise ValueError('Missing MT5 candle fields.')
    bars = bars.loc[:, COLUMNS].apply(pd.to_numeric, errors='raise')
    if not np.isfinite(bars.to_numpy(dtype=float)).all():
        raise ValueError('Non-finite market data.')
    bars['time'] = bars.time - offset * 3600
    if ((bars.time <= 0) | (bars.time % 60 != 0)).any():
        raise ValueError('Expected UTC minute-aligned candle opens.')
    bars = bars[bars.time + 60 <= now].drop_duplicates().sort_values('time')
    if bars.time.duplicated().any():
        raise ValueError('Conflicting completed candles share a timestamp.')
    if ((bars.low <= 0) | (bars.high < bars[['open', 'close', 'low']].max(axis=1))
            | (bars.low > bars[['open', 'close']].min(axis=1))
            | (bars.tick_volume < 0) | (bars.spread < 0)).any():
        raise ValueError('Invalid candle prices or volume/spread.')
    return bars.reset_index(drop=True)


def features(bars, point):
    """Every feature uses at most 61 consecutive completed candles."""
    log_close = np.log(bars.close)
    move = log_close.diff()
    returns = {f'r{n}': log_close.diff(n) for n in (1, 3, 5, 15, 60)}
    prev = bars.close.shift()
    tr = pd.concat([bars.high-bars.low, (bars.high-prev).abs(), (bars.low-prev).abs()], axis=1).max(axis=1)
    gains = move.clip(lower=0).rolling(14).sum()
    losses = (-move.clip(upper=0)).rolling(14).sum()
    height = bars.high-bars.low
    scale = height.where(height > 0, point)
    prior_low = bars.low.shift().rolling(20).min()
    prior_high = bars.high.shift().rolling(20).max()
    avg_volume = bars.tick_volume.shift().rolling(20).mean()
    angle = (bars.time + 60) % 86400 * (2*np.pi/86400)
    frame = pd.DataFrame({
        **returns, 'vol15': move.rolling(15).std(), 'vol60': move.rolling(60).std(),
        'atr': tr.rolling(14).mean()/bars.close,
        'rsi': (gains/(gains+losses).replace(0, np.nan)).fillna(.5),
        'trend': (log_close.rolling(9).mean()-log_close.rolling(21).mean()),
        'momentum': returns['r5']-returns['r15']/3,
        'body': (bars.close-bars.open)/scale,
        'upper': (bars.high-bars[['open', 'close']].max(axis=1))/scale,
        'lower': (bars[['open', 'close']].min(axis=1)-bars.low)/scale,
        'range_position': (bars.close-prior_low)/(prior_high-prior_low).clip(lower=point),
        'spread_bps': bars.spread*point/bars.close*1e4,
        'activity': bars.tick_volume/avg_volume.clip(lower=1),
        'hour_sin': np.sin(angle), 'hour_cos': np.cos(angle),
    })
    return frame.where(bars.time.diff(WINDOW-1).eq((WINDOW-1)*60), axis=0)


def labeled(bars, x, horizon):
    if horizon not in HORIZONS:
        raise ValueError('Unsupported horizon.')
    end = bars.time.shift(-horizon) + 60
    target = np.log(bars.close.shift(-horizon)/bars.close)*1e4
    frame = x.assign(time=bars.time+60, label_end=end, target=target)
    return frame.loc[(end-frame.time).eq(horizon*60)].dropna()


def before(frame, boundary):
    return frame[frame.label_end < boundary]

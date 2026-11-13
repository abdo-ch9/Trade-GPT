"""Read-only MT5 adapter and serialized, bounded inference state."""
import time
from pathlib import Path
from threading import Lock

import joblib
import pandas as pd

from .data import HORIZONS, WINDOW, completed, features
from .research import direction

SCHEMA = 2


def load(path):
    try:
        artifact = joblib.load(Path(path))
        if artifact['schema'] != SCHEMA or set(artifact['models']) != set(HORIZONS):
            raise ValueError('Unsupported forecast artifact schema.')
        return artifact
    except Exception as exc:
        raise ValueError(f'Cannot load local forecast artifact ({type(exc).__name__}). Train it again.') from exc


class Engine:
    def __init__(self, artifact):
        self.artifact = artifact
        self.bars = None
        self.last = None
        self.lock = Lock()

    def update(self, fetch, now=None, offset=0):
        with self.lock:
            start = time.perf_counter()
            replay_clock = now is not None
            now = time.time() if now is None else now
            count = WINDOW + 2
            if self.bars is not None and not self.bars.empty:
                count = min(count, max(3, int((now-self.bars.time.iloc[-1])/60)+2))
            raw = fetch(count)
            provider_ms = (time.perf_counter()-start)*1000
            begin = time.perf_counter()
            if not replay_clock:
                now = time.time()
            batch = completed(raw, now, offset)
            if batch.empty:
                raise ValueError('No completed candles returned.')
            if self.bars is None:
                merged = batch
            else:
                # Retain the first observation for completed candles.
                merged = batch[batch.time > self.bars.time.iloc[-1]]
                if not merged.empty:
                    merged = pd.concat([self.bars, merged], ignore_index=True)
                else:
                    merged = self.bars
            self.bars = merged.tail(WINDOW).reset_index(drop=True)
            close_time = int(self.bars.time.iloc[-1]+60)
            age = now-close_time
            market = {'close_time': close_time, 'close': float(self.bars.close.iloc[-1]),
                      'age_seconds': age, 'provider_ms': provider_ms}
            if age >= 90:
                return {**market, 'state': 'NO SIGNAL', 'reason': 'Stale data or market closure.', 'forecasts': []}
            if self.last and self.last['close_time'] == close_time:
                return {**self.last, **market}
            x = features(self.bars, self.artifact['point']).iloc[[-1]]
            feature_ms = (time.perf_counter()-begin)*1000
            if x.isna().any(axis=None):
                return {**market, 'state': 'NO SIGNAL', 'reason': 'Waiting for 61 contiguous completed minutes.',
                        'forecasts': []}
            predictions = []
            infer_start = time.perf_counter()
            for horizon, model in self.artifact['models'].items():
                expected, up = model.predict(x)
                side = int(direction(expected, up, x.spread_bps, self.artifact['commission'],
                                     self.artifact['slippage'], model.error90, model.threshold)[0])
                down = (1-up[0])*model.down_given_non_up
                if side < 0 and down < model.threshold:
                    side = 0
                predictions.append({'horizon_min': horizon, 'expected_bps': float(expected[0]),
                                    'p_up': float(up[0]), 'p_down': float(down),
                                    'p_flat': float(1-up[0]-down),
                                    'error90_bps': model.error90,
                                    'paper_signal': {1: 'UP', -1: 'DOWN', 0: 'NO SIGNAL'}[side]})
            self.last = {**market, 'state': 'FORECAST', 'version': self.artifact['version'],
                         'generated_at': now if replay_clock else time.time(), 'feature_ms': feature_ms,
                         'inference_ms': (time.perf_counter()-infer_start)*1000,
                         'local_total_ms': (time.perf_counter()-start)*1000, 'forecasts': predictions}
            return self.last


def mt5_fetch(bridge, identity, symbol, point):
    """Use the already selected dashboard symbol and existing MT5 lock."""
    def fetch(count):
        with bridge.LOCK:
            api = bridge.api()
            bridge.checked_account(api, identity, read_only=True) if bridge.BROKER_NAME == 'Exness' else bridge.checked_account(api, identity)
            info = api.symbol_info(symbol)
            if info is None or info.point != point:
                raise ValueError('MT5 instrument point differs from the trained artifact.')
            if not info.visible and not api.symbol_select(symbol, True):
                raise ValueError('MT5 could not select the forecast instrument.')
            return api.copy_rates_from_pos(symbol, api.TIMEFRAME_M1, 0, count)
    return fetch

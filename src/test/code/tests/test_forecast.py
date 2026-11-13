import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd

from scalp_lab.forecast.data import COLUMNS, FEATURES, HORIZONS, before, completed, features, labeled
from scalp_lab.forecast.research import Forecast, replay, walk_forward
from scalp_lab.forecast.runtime import Engine, load


def candles(count=1600):
    rng = np.random.default_rng(42)
    close = 3000*np.exp(rng.normal(0, .0004, count).cumsum())
    return pd.DataFrame({'time': 1700000040+np.arange(count)*60, 'open': close,
                         'close': close, 'high': close+1, 'low': close-1,
                         'spread': 20, 'tick_volume': 100})[COLUMNS]


class ForecastTests(unittest.TestCase):
    def test_validation_and_incomplete_candle(self):
        bars = candles(4)
        now = bars.time.iloc[-1]
        pd.testing.assert_frame_equal(completed(pd.concat([bars, bars.iloc[[0]]]), now),
                                      bars.iloc[:-1])
        invalid = bars.copy()
        invalid.loc[0, 'low'] = -1
        with self.assertRaisesRegex(ValueError, 'Invalid'):
            completed(invalid, now)
        conflicting = bars.iloc[[0]].assign(spread=5)
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            completed(pd.concat([bars, conflicting]), now)
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            completed(None, now)
        pd.testing.assert_frame_equal(completed(bars.assign(time=bars.time+7200), now, 2),
                                      bars.iloc[:-1])

    def test_future_changes_do_not_alter_features_and_windows_align(self):
        bars = candles()
        original = features(bars, .001)
        edited = bars.copy()
        edited.loc[900:, ['open', 'close', 'high', 'low']] *= 2
        pd.testing.assert_frame_equal(original.iloc[:900], features(edited, .001).iloc[:900])
        np.testing.assert_allclose(original.iloc[-1][FEATURES],
                                   features(bars.tail(61), .001).iloc[-1][FEATURES], atol=1e-9)

    def test_labels_purge_and_gap_recovery(self):
        bars = candles().drop(index=900).reset_index(drop=True)
        x = features(bars, .001)
        self.assertTrue(x.iloc[900:960].isna().all(axis=None))
        for horizon in HORIZONS:
            frame = labeled(bars, x, horizon)
            self.assertTrue((frame.label_end-frame.time == horizon*60).all())
            self.assertFalse(((frame.time <= bars.time.iloc[899]+60) &
                              (frame.label_end > bars.time.iloc[899]+60) &
                              (frame.label_end <= bars.time.iloc[900]+60)).any())
            boundary = frame.time.iloc[500]
            self.assertLess(before(frame, boundary).label_end.max(), boundary)

    def test_walk_forward_and_paper_replay_are_reproducible(self):
        bars = candles()
        frame = labeled(bars, features(bars, .001), 3)
        model, a = walk_forward(frame, bars, 3, .001)
        _, b = walk_forward(frame, bars, 3, .001)
        self.assertEqual(a, b)
        final = frame[frame.time >= a['final_start_utc_epoch']]
        self.assertEqual(a['paper'], replay(bars, final, model, 3, .001))

    def test_runtime_deduplication_downtime_and_staleness(self):
        model = Mock(spec=Forecast, error90=2., threshold=.65, down_given_non_up=1.)
        model.predict.return_value = (np.array([10.]), np.array([.8]))
        engine = Engine({'point': .001, 'commission': 1., 'slippage': .5,
                         'version': 'test', 'models': {1: model}})
        bars = candles(75)
        now = bars.time.iloc[-1]+60
        fetch = Mock(side_effect=lambda n: bars.tail(n))
        a = engine.update(fetch, now)
        b = engine.update(fetch, now+2)
        self.assertEqual(a['forecasts'], b['forecasts'])
        model.predict.assert_called_once()
        self.assertLess(fetch.call_args.args[0], 10)
        self.assertLess(a['local_total_ms'], 1000)
        self.assertEqual(engine.update(fetch, now+100)['state'], 'NO SIGNAL')
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            engine.update(lambda n: None, now+101)

    def test_missing_or_corrupt_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'missing.joblib'
            with self.assertRaisesRegex(ValueError, 'Cannot load'):
                load(path)
            path.write_text('corrupt', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Cannot load'):
                load(path)

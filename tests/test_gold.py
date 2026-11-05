import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import pandas as pd
from scalp_lab import gold


def bars(n=700):
    rng=np.random.default_rng(13)
    close=2000+np.cumsum(rng.normal(0,.6,n))
    return pd.DataFrame({'time':1800000000+np.arange(n)*60,'open':close-.1,
        'high':close+.8,'low':close-.8,'close':close,'tick_volume':100,'spread':10})


class GoldTests(unittest.TestCase):
    def test_future_bars_cannot_change_past_signals(self):
        b=bars()
        short=gold.features(b.iloc[:503])
        full=gold.features(b).iloc[:503]
        for column in ['fast5','slow15','atr15','side','setup','vwap_proxy','support']:
            pd.testing.assert_series_equal(short[column].reset_index(drop=True),full[column].reset_index(drop=True))

    def test_incomplete_higher_timeframe_is_not_used(self):
        b=bars()
        baseline=gold.features(b)
        altered=b.copy()
        # Last M15 bucket after the cutoff must not affect the preceding minute.
        altered.loc[501:,'high']+=500
        changed=gold.features(altered)
        pd.testing.assert_frame_equal(baseline.iloc[:501],changed.iloc[:501])

    def test_gap_resets_indicator_warmup(self):
        b=bars()
        b.loc[500:,'time']+=3600
        d=gold.features(b)
        self.assertTrue(d.iloc[500:]['slow15'].isna().all())
        self.assertTrue((d.iloc[500:].side==0).all())

    def test_gold_filter_excludes_gold_stocks_and_synthetic_weekend(self):
        for symbol,expected in [('GOLD',True),('XAUUSD',True),('EURUSD',False),('BarrickGold',False),('GOLD24-7',False)]:
            self.assertEqual(gold.eligible_symbol(SimpleNamespace(name=symbol,currency_profit='USD')),expected)

    def test_stop_first_collision_and_next_bar_entry(self):
        d=gold.features(bars())
        d['side']=0
        d.loc[400,'side']=1
        d.loc[401,'high']=9999
        d.loc[401,'low']=1
        trades=gold.simulate(d,.01)
        self.assertEqual(len(trades),1)
        self.assertEqual(trades.iloc[0].time,d.iloc[401].time)
        self.assertLess(trades.iloc[0].r,-1)

    def test_no_trade_across_missing_future_minutes(self):
        d=gold.features(bars())
        d['side']=0
        d.loc[400,'side']=1
        d.loc[401:,'time']+=60
        self.assertTrue(gold.simulate(d,.01).empty)

    def test_risk_levels_direction_and_18_reward_ratio(self):
        row=gold.features(bars()).iloc[-1]
        for side in (1,-1):
            plan=gold.levels(row,side,row.close,.2)
            self.assertGreater(side*(plan['tp']-plan['entry']),0)
            self.assertGreater(side*(plan['entry']-plan['sl']),0)
            self.assertAlmostEqual(plan['tp_bps']/plan['sl_bps'],1.8)

    def test_small_sample_cannot_validate(self):
        report,_=gold.evaluate(bars(),'GOLD',.01)
        self.assertFalse(report['eligible'])
        self.assertEqual(report['broker'],gold.bridge.BROKER_NAME)
        self.assertEqual(len(report['chronological_folds']),4)
        self.assertEqual(report['execution_policy'],'signal-close-plus-15m-v1')

    def test_old_broker_evaluation_cannot_authorize_entries(self):
        report={'broker':'XM','engine':gold.ENGINE,'symbol':'GOLD',
                'created_at':time.time(),'execution_policy':gold.EXIT_POLICY,
                'eligible':True,'reason':'old report'}
        with patch.object(gold,'REPORT',SimpleNamespace(read_text=lambda:json.dumps(report))):
            valid,reason=gold.validation('GOLD')
        self.assertFalse(valid)
        self.assertIn('IC Markets',reason)

    def test_previously_viewed_history_cannot_authorize(self):
        b=bars()
        b['time']=gold.PUBLISHED_THROUGH-60*(len(b)-1)+np.arange(len(b))*60
        report,_=gold.evaluate(b,'GOLD',.01)
        self.assertFalse(report['eligible'])
        self.assertIn('already inspected',report['reason'])

    def test_time_exit_lasts_fifteen_minutes(self):
        d=gold.features(bars())
        d['side']=0
        d.loc[400,'side']=1
        d.loc[401:415,'high']=d.loc[401:415,'close']
        d.loc[401:415,'low']=d.loc[401:415,'close']
        trades=gold.simulate(d,.01)
        self.assertEqual(len(trades),1)
        self.assertEqual(trades.iloc[0].exit_reason,'time')
        self.assertEqual(trades.iloc[0].exit_time-trades.iloc[0].time,15*60)


if __name__=='__main__':
    unittest.main()

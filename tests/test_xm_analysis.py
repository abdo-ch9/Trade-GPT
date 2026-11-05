import unittest
import numpy as np
import pandas as pd
from scalp_lab.xm_analysis import features, train, assess, diagnostic, FEATURES


def bars(n=1800):
    rng=np.random.default_rng(81)
    close=100*np.exp(np.cumsum(rng.normal(0,.001,n)))
    return pd.DataFrame({'time':1800000000+np.arange(n)*60,'open':close,'close':close,
                         'high':close+.12,'low':close-.12,'tick_volume':rng.integers(10,100,n),'spread':2})


class AnalysisTests(unittest.TestCase):
    def test_features_do_not_use_future_prices(self):
        original=bars()
        changed=original.copy()
        changed.loc[1000:,['open','high','low','close']]*=2
        pd.testing.assert_frame_equal(features(original,.01).loc[:999,FEATURES],features(changed,.01).loc[:999,FEATURES])

    def test_labels_and_indicators_do_not_cross_missing_candles(self):
        d=features(bars(100).drop(index=50),.01)
        self.assertTrue(d.iloc[45:50].label.isna().all())
        self.assertTrue(d.iloc[50:70].support.isna().all())

    def test_purged_training_and_nonoverlapping_test(self):
        result=train(bars(),.01)
        self.assertTrue(result['ready'])
        self.assertLess(result['training_label_end'],result['test_start'])
        self.assertLessEqual(result['test_count'],(result['test_end']-result['test_start'])/300+1)

    def test_stale_or_future_data_cannot_generate_scenarios(self):
        b=bars(100)
        for now in [b.time.iloc[-1]+200,b.time.iloc[-1]]:
            result=assess(b,.01,{'ready':False,'reason':'No model'},100,100.1,now)
            self.assertEqual(result['action'],'WAIT')
            self.assertNotIn('scenarios',result)

    def test_dynamic_levels_and_baseline_gate(self):
        b=bars()
        fitted=train(b,.01)
        fitted['balanced_accuracy']=1/3
        result=assess(b,.01,fitted,100,100.1,b.time.iloc[-1]+65,.05)
        self.assertEqual(result['action'],'MODEL NOT VALIDATED')
        for side, levels in result['scenarios'].items():
            if side=='BUY':
                self.assertLess(levels['sl'],levels['entry'])
                self.assertGreater(levels['tp'],levels['entry'])
            else:
                self.assertGreater(levels['sl'],levels['entry'])
                self.assertLess(levels['tp'],levels['entry'])
            self.assertAlmostEqual(levels['tp_bps']/levels['sl_bps'],2)

    def test_neutral_majority_cannot_fake_predictive_skill(self):
        y=np.array([0]*980+[1]*10+[-1]*10)
        result=diagnostic(y,np.zeros(len(y)))
        self.assertAlmostEqual(result['balanced_accuracy'],1/3)
        self.assertFalse(result['evidence_sufficient'])

    def test_longer_horizon_changes_labels_without_crossing_gaps(self):
        b=bars(200).drop(index=100)
        d=features(b,.01,30)
        self.assertTrue(d.iloc[70:100].label.isna().all())
        valid=d.dropna(subset=['label_end'])
        self.assertTrue(((valid.label_end-valid.time)==1800).all())

    def test_supported_direction_can_generate_both_sides(self):
        from types import SimpleNamespace
        for sign,expected in [(1,'BUY setup'),(-1,'SELL setup')]:
            b=bars(100)
            close=100+sign*np.arange(100)*.02
            for field in ['open','close']:
                b[field]=close
            b['high']=close+.05; b['low']=close-.05
            model=SimpleNamespace(classes_=np.array([-1,0,1]),
                 predict_proba=lambda x,s=sign:np.array([[.05,.05,.90] if s==1 else [.90,.05,.05]]))
            fitted={'ready':True,'model':model,'evidence_sufficient':True,'test_count':100,'balanced_accuracy':.60}
            result=assess(b,.01,fitted,close[-1],close[-1]+.01,b.time.iloc[-1]+65)
            self.assertEqual(result['action'],expected)


if __name__=='__main__':
    unittest.main()

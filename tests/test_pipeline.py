import unittest
import pandas as pd
from scalp_lab.synthetic import generate_demo
from scalp_lab.news import score_news, add_news_features
from scalp_lab.features import make_features
from scalp_lab.targets import label_outcomes
from scalp_lab.evaluation import wilson_lower_bound

class PipelineTests(unittest.TestCase):
    def test_no_future_news(self):
        t=pd.Timestamp('2026-04-01T13:31:00Z')
        features=pd.DataFrame({'decision_time':[t,t+pd.Timedelta(minutes=2)]})
        news=pd.DataFrame({'headline':['Profit beats estimates'],'created_at':[t+pd.Timedelta(seconds=30)]})
        got=add_news_features(features,score_news(news,assumed_latency_s=60))
        self.assertEqual(got.iloc[0]['news_count_15m'],0)
        self.assertEqual(got.iloc[1]['news_count_15m'],1)
    def test_same_bar_stop_first(self):
        bars=pd.DataFrame({'timestamp':pd.date_range('2026-04-01 13:30',periods=50,freq='min',tz='UTC'),'open':[100]*50,'close':[100]*50,'high':[101]*50,'low':[99]*50,'volume':[100]*50})
        feat=make_features(bars)
        lab=label_outcomes(feat,horizon=5,tp_bps=18,sl_bps=12,cost_bps=6)
        self.assertAlmostEqual(lab.iloc[0]['pnl_long'],-18)
    def test_gaps_do_not_count_as_5_minutes(self):
        bars,_=generate_demo(days=1)
        bars=bars.drop(index=bars.index[80]).reset_index(drop=True)
        feat=make_features(bars)
        lab=label_outcomes(feat,horizon=5)
        self.assertTrue(pd.isna(lab.iloc[78]['pnl_long']))
    def test_wilson_is_conservative(self):
        self.assertLess(wilson_lower_bound(8,10),0.80)

if __name__=='__main__':unittest.main()

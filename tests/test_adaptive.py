import unittest
import numpy as np
import pandas as pd
from scalp_lab.signals import adaptive_distances


class AdaptiveTests(unittest.TestCase):
    def bars(self, scale=1):
        close=100+np.sin(np.arange(40))*0.02*scale
        return pd.DataFrame({"timestamp":pd.date_range("2026-11-03T15:00:00Z",periods=40,freq="min"),
                             "open":close,"high":close+0.03*scale,"low":close-0.03*scale,
                             "close":close,"volume":1000})

    def calc(self,bars,**kwargs):
        return adaptive_distances(bars,now="2026-11-03T15:40:00Z",**kwargs)

    def test_more_movement_widens_stop_and_target(self):
        quiet=self.calc(self.bars())
        fast=self.calc(self.bars(4))
        self.assertGreater(fast["sl_bps"],quiet["sl_bps"])
        self.assertGreater(fast["tp_bps"],quiet["tp_bps"])
        self.assertFalse(quiet["stale"])

    def test_future_bars_do_not_affect_result(self):
        bars=self.bars()
        future=bars.iloc[[-1]].copy()
        future["timestamp"]=pd.Timestamp("2026-11-03T15:40:00Z")
        future["high"]=1000
        self.assertEqual(self.calc(bars),self.calc(pd.concat([bars,future])))

    def test_gap_requires_new_warmup(self):
        result=self.calc(self.bars().drop(index=30))
        self.assertFalse(result["available"])

    def test_cost_floor_and_stale_status(self):
        bars=self.bars()
        result=self.calc(bars,cost_bps=20)
        self.assertGreaterEqual(result["sl_bps"],24)
        historical=adaptive_distances(bars,now="2026-11-04T15:40:00Z")
        self.assertTrue(historical["stale"])

    def test_volume_and_velocity_change_levels(self):
        bars=self.bars()
        normal=self.calc(bars)
        bars.loc[35:,"volume"]=10000
        self.assertGreater(self.calc(bars)["sl_bps"],normal["sl_bps"])
        trend=self.bars()
        for col in ("open","high","low","close"):
            trend[col]+=np.arange(40)*0.02
        self.assertGreater(abs(self.calc(trend)["velocity_bps_per_minute"]),abs(normal["velocity_bps_per_minute"]))


if __name__=="__main__":
    unittest.main()

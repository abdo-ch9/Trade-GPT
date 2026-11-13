import unittest
import numpy as np
import pandas as pd
from scalp_lab.charting import prepare_chart,analyze_chart,make_figure


class ChartTests(unittest.TestCase):
    now="2026-11-03T17:00:00Z"

    def bars(self,direction=1):
        close=100+np.arange(150)*0.01*direction
        return pd.DataFrame({"timestamp":pd.date_range("2026-11-03T14:30:00Z",periods=150,freq="min"),
                             "open":close-0.001,"high":close+0.005,"low":close-0.005,"close":close,"volume":1000})

    def test_aggregate_ohlcv_and_exclude_incomplete_candles(self):
        bars=self.bars()
        chart=prepare_chart(bars,5,now=self.now)
        self.assertEqual(len(chart),30)
        self.assertEqual(chart.iloc[0].open,bars.iloc[0].open)
        self.assertEqual(chart.iloc[0].close,bars.iloc[4].close)
        self.assertEqual(chart.iloc[0].volume,5000)
        self.assertEqual(len(prepare_chart(bars,5,now="2026-11-03T14:39:30Z")),1)

    def test_gap_does_not_become_complete_five_minute_candle(self):
        chart=prepare_chart(self.bars().drop(index=7),5,now=self.now)
        self.assertEqual(len(chart),29)
        self.assertNotIn(pd.Timestamp("2026-11-03T14:35:00Z"),chart.timestamp.tolist())

    def test_bullish_bearish_and_flat_rsi(self):
        for direction,expected in ((1,"Bullish"),(-1,"Bearish")):
            frame=prepare_chart(self.bars(direction),now=self.now)
            result=analyze_chart(frame,now=self.now)
            self.assertIn(expected,result["trend"])
            self.assertFalse(result["stale"])
        flat=prepare_chart(self.bars(0),now=self.now)
        self.assertEqual(flat.iloc[-1].rsi,50)

    def test_support_resistance_exclude_current_candle(self):
        bars=self.bars()
        bars.loc[149,"high"]=999
        chart=prepare_chart(bars,now=self.now)
        self.assertEqual(chart.iloc[-1].resistance,bars.iloc[129:149].high.max())
        old=analyze_chart(chart,now="2026-11-04T17:00:00Z")
        self.assertTrue(old["stale"])

    def test_figure_contains_candles_volume_and_rsi(self):
        frame=prepare_chart(self.bars(),now=self.now)
        figure=make_figure(frame,"TEST")
        self.assertEqual(figure.data[0].type,"candlestick")
        self.assertEqual(figure.data[-2].type,"bar")
        self.assertEqual(figure.data[-1].name,"RSI 14")


if __name__=="__main__":
    unittest.main()

"""Focused checks for display transformations and read-only account summaries."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "main" / "code"))

from frontend import services
from frontend.pages.trading import _display_bars


class FrontendDisplayTests(unittest.TestCase):
    def test_m5_uses_only_complete_candle_groups(self):
        times = list(range(0, 5 * 60, 60)) + list(range(5 * 60, 8 * 60, 60))
        frame = pd.DataFrame({
            "time": times, "open": range(len(times)),
            "high": range(1, len(times) + 1), "low": range(len(times)),
            "close": range(1, len(times) + 1),
            "ema9": range(len(times)), "ema20": range(len(times)),
            "vwap_proxy": range(len(times)),
        })
        result = _display_bars(frame, "M5")
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["open"], 0)
        self.assertEqual(result.iloc[0]["close"], 5)

    def test_today_pnl_omits_deposits_and_includes_fees(self):
        class Lock:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        deals = [
            SimpleNamespace(symbol="XAUUSD", type=0, profit=12, commission=-1,
                            swap=-0.5, fee=-0.25),
            SimpleNamespace(symbol="", type=2, profit=3000, commission=0, swap=0, fee=0),
        ]
        mt5 = SimpleNamespace(DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1,
                              history_deals_get=lambda *_: deals)
        bridge = SimpleNamespace(LOCK=Lock(), api=lambda: mt5)
        broker = SimpleNamespace(bridge=bridge, account=lambda _identity: None)
        services.daily_trading_pnl.clear()
        with patch.dict(services.BROKERS, {"Test": broker}):
            self.assertEqual(services.daily_trading_pnl("Test", (123,)), 10.25)
        services.daily_trading_pnl.clear()


if __name__ == "__main__":
    unittest.main()

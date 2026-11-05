import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from scalp_lab.auto_update import (
    DEFAULT_SYMBOLS, acquire_lock, add_symbol, atomic_json, fetch_snapshots,
    read_json, snapshot_price, symbols_for, update_history,
)
from scalp_lab.features import FEATURE_COLUMNS
from scalp_lab.synthetic import generate_demo


class ConstantModel:
    def predict_proba(self, x):
        return np.array([[0.1, 0.9]])


class AutoUpdateTests(unittest.TestCase):
    def test_all_defaults_and_custom_persist_without_demo(self):
        with tempfile.TemporaryDirectory() as root:
            add_symbol(root, "AMD")
            add_symbol(root, "DEMO")
            self.assertEqual(set(symbols_for(root)), set(DEFAULT_SYMBOLS)|{"AMD"})
            with self.assertRaises(ValueError):
                add_symbol(root, "../BAD")

    def test_only_one_background_worker_can_hold_lock(self):
        with tempfile.TemporaryDirectory() as root:
            first = acquire_lock(root)
            self.assertIsNotNone(first)
            try:
                self.assertIsNone(acquire_lock(root))
            finally:
                first.close()
            restarted = acquire_lock(root)
            self.assertIsNotNone(restarted)
            restarted.close()

    def test_price_uses_market_time_not_poll_time(self):
        stamp, price = snapshot_price({
            "latestTrade": {"t": "2026-11-03T15:01:00Z", "p": 100},
            "minuteBar": {"t": "2026-11-03T15:02:00Z", "c": 101},
        })
        self.assertEqual((stamp, price), ("2026-11-03T15:02:00Z", 101))
        self.assertEqual(snapshot_price({}), (None, None))

    def test_bad_custom_ticker_does_not_block_valid_prices(self):
        from unittest.mock import Mock
        def response(url, **kwargs):
            symbol = kwargs["params"]["symbols"]
            return Mock(status_code=400 if "BAD" in symbol else 200,
                        json=lambda: {"AAPL": {"latestTrade": {"p": 123, "t": "2026-11-03T15:00:00Z"}}})
        with patch("requests.get", side_effect=response), patch("scalp_lab.feeds.headers", return_value={}):
            snapshots = fetch_snapshots(["AAPL", "BAD"], "iex")
        self.assertEqual(snapshots["AAPL"]["latestTrade"]["p"], 123)
        self.assertEqual(snapshots["BAD"], {})

    def test_updates_untrained_asset_without_touching_training_data(self):
        bars, _ = generate_demo(days=1)
        with tempfile.TemporaryDirectory() as root:
            training = Path(root)/"data"/"AAPL_bars.csv"
            training.parent.mkdir()
            bars.to_csv(training, index=False)
            before = training.read_bytes()
            with patch("scalp_lab.feeds.fetch_bars", return_value=bars), patch("scalp_lab.feeds.fetch_news", return_value=pd.DataFrame()):
                result = update_history(root, "AAPL", "iex")
                update_history(root, "AAPL", "iex")
            self.assertIn("model not trained", result["state"])
            self.assertEqual(training.read_bytes(), before)
            saved = pd.read_csv(Path(root)/"auto_live"/"AAPL"/"bars.csv")
            self.assertFalse(saved.timestamp.duplicated().any())
            signal = read_json(Path(root)/"auto_live"/"AAPL"/"signal.json")
            self.assertEqual(signal["signal"], "NO_SIGNAL")

    def test_stale_bars_never_produce_buy_even_with_high_probability(self):
        bars, _ = generate_demo(days=1)
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)/"results_AAPL"
            atomic_json(folder/"report.json", {"symbol": "AAPL", "horizon_minutes": 5,
                        "settings": {"tp_bps": 18, "sl_bps": 12}})
            (folder/"paper_models.joblib").touch()
            artifact = {"features": FEATURE_COLUMNS, "models": {"long": ConstantModel(), "short": ConstantModel()}, "threshold": 0.5}
            with patch("scalp_lab.feeds.fetch_bars", return_value=bars), patch("scalp_lab.feeds.fetch_news", return_value=pd.DataFrame()), patch("joblib.load", return_value=artifact):
                result = update_history(root, "AAPL", "iex")
            signal = read_json(Path(root)/"auto_live"/"AAPL"/"signal.json")
            self.assertEqual(signal["signal"], "NO_SIGNAL")
            self.assertIsNone(signal["levels"])
            self.assertEqual(result["state"], "Waiting for fresh market bars")


if __name__ == "__main__":
    unittest.main()

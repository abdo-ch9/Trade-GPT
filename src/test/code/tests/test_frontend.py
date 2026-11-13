"""Focused checks for display transformations and read-only account summaries."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pyarrow as pa

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "main" / "code"))

from frontend import components, services
from frontend.pages.automation import _can_override_holdout
from frontend.pages import automation
from frontend.pages.trading import _display_bars


class FrontendDisplayTests(unittest.TestCase):
    def test_value_table_is_arrow_compatible_with_mixed_display_values(self):
        rows = [{"Setting": "Automatic entries", "Value": "Stopped"},
                {"Setting": "Maximum entry attempts", "Value": 5},
                {"Setting": "Minimum volume", "Value": None}]
        with patch.object(components.st, "dataframe") as dataframe:
            components.value_table(rows)
        display_rows = dataframe.call_args.args[0]
        table = pa.Table.from_pandas(pd.DataFrame(display_rows), preserve_index=False)
        self.assertEqual(table.column("Value").to_pylist(), ["Stopped", "5", "—"])
        self.assertEqual(rows[1]["Value"], 5)

    def test_active_automation_page_saves_selected_trade_size(self):
        identity = (123, "Demo")
        instrument = SimpleNamespace(name="XAUUSD", volume_min=.01,
                                     volume_max=1.0, volume_step=.01)
        config = {"enabled": False, "identity": list(identity),
                  "symbols": ["XAUUSD"], "offset": 2, "lots": .01}
        auto = SimpleNamespace(settings=lambda: config,
                               eligible=lambda *_: ["XAUUSD"],
                               valid_lots=lambda *_: True,
                               set_lots=MagicMock())
        worker = SimpleNamespace(ensure_running=lambda: None,
                                 status=lambda: {}, healthy=lambda *_: False)
        news = SimpleNamespace(connection_status=lambda: (True, "Ready"))
        telegram = SimpleNamespace(configuration=lambda: {})
        modules = {"gold_worker": worker, "xm_news": news,
                   "telegram_notifications": telegram}
        broker = SimpleNamespace(name="IC Markets", is_exness=False, auto=auto,
                                 mode=lambda *_: "demo", module=modules.__getitem__,
                                 bridge=SimpleNamespace(DemoError=RuntimeError),
                                 gold=SimpleNamespace(execution_validation=lambda *_: (True, "Ready")))
        state = (broker, identity, SimpleNamespace(currency="USD"),
                 [instrument], instrument, 2)
        st = MagicMock()
        st.number_input.side_effect = [.02, 1.0, 5]
        st.button.side_effect = lambda label, **_: label == "Save trade size"
        st.checkbox.return_value = False
        start, stop = MagicMock(), MagicMock()
        start.button.return_value = stop.button.return_value = False
        st.columns.return_value = (start, stop)
        with patch.object(automation, "page_state", return_value=state), \
             patch.object(automation, "st", st), \
             patch.object(automation, "components"), \
             patch.object(automation.services, "events", return_value=[]), \
             patch.object(automation.services, "invalidate_analysis") as invalidate:
            automation.render()
        auto.set_lots.assert_called_once_with(.02)
        invalidate.assert_called_once()
        st.rerun.assert_called_once()

    def test_live_holdout_override_requires_exact_failure_and_ready_session(self):
        broker = SimpleNamespace(is_exness=True,
                                 gold=SimpleNamespace(HOLDOUT_FAILURE="Holdout failed"))
        args = (broker, "real", False, "Holdout failed", True, True, ["XAUUSD"], False)
        self.assertTrue(_can_override_holdout(*args))
        for change in ({"mode": "demo"}, {"validated": True},
                       {"reason": "Missing exit checks"},
                       {"news_ready": False}, {"context_matches": False},
                       {"symbols": []}, {"enabled": True}):
            values = dict(zip(("broker", "mode", "validated", "reason", "news_ready",
                               "context_matches", "symbols", "enabled"), args))
            values.update(change)
            self.assertFalse(_can_override_holdout(**values), change)

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

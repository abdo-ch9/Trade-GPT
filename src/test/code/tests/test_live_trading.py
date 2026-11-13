"""Live routing tests use only MT5 mocks; no terminal or real order is used."""
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing, nullcontext
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from frontend.context import broker_for
from frontend import services
from frontend import app


class State(dict):
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


def terminal(broker, mode):
    company = "IC Markets Global" if broker == "IC Markets" else "Exness Technologies Ltd"
    server = "ICMarkets-Live" if broker == "IC Markets" else "Exness-MT5Real"
    mt5 = NS(ACCOUNT_TRADE_MODE_DEMO=0, ACCOUNT_TRADE_MODE_REAL=2,
             TRADE_RETCODE_DONE=10009, TRADE_RETCODE_DONE_PARTIAL=10010)
    mt5.terminal_info = Mock(return_value=NS(connected=True, trade_allowed=True,
                                             tradeapi_disabled=False))
    mt5.account_info = Mock(return_value=NS(login=123, server=server, company=company,
                                            trade_mode=mode, trade_allowed=True,
                                            trade_expert=True))
    mt5.order_check = Mock(return_value=NS(retcode=0, comment="ok"))
    mt5.order_send = Mock(return_value=NS(retcode=10009, order=8, deal=9, comment="done"))
    return mt5


class LiveRoutingTests(unittest.TestCase):
    def test_mode_change_is_reverted_while_automation_runs(self):
        state = State(active_broker="IC Markets", active_environment="DEMO",
                      selected_broker="Exness", trading_environment="DEMO")
        running = NS(auto=NS(settings=lambda: {"enabled": True}))
        with patch.object(app.st, "session_state", state), \
             patch.object(app, "broker_for", return_value=running), \
             patch.object(app, "clear_broker_state") as clear:
            app._on_context_change()
        self.assertEqual(state["selected_broker"], "IC Markets")
        self.assertTrue(state["selection_blocked"])
        clear.assert_not_called()

    def test_switching_demo_to_live_stops_demo_entries_without_starting_live(self):
        state = State(active_broker="IC Markets", active_environment="DEMO",
                      selected_broker="IC Markets", trading_environment="LIVE")
        running = NS(auto=NS(settings=Mock(side_effect=[{"enabled": True}, {"enabled": False}]),
                             stop=Mock(), arm=Mock()))
        with patch.object(app.st, "session_state", state), \
             patch.object(app, "broker_for", return_value=running) as broker_for, \
             patch.object(app, "clear_broker_state") as clear:
            app._on_context_change()
        running.auto.stop.assert_called_once_with("Stopped when switching to LIVE")
        running.auto.arm.assert_not_called()
        broker_for.assert_called_once_with("IC Markets", "demo")
        clear.assert_called_once()
        self.assertEqual(state["active_environment"], "LIVE")
        self.assertIn("does not start LIVE automation", state["selection_notice"])

    def test_failed_demo_stop_prevents_switching_to_live(self):
        state = State(active_broker="IC Markets", active_environment="DEMO",
                      selected_broker="IC Markets", trading_environment="LIVE")
        running = NS(auto=NS(settings=Mock(return_value={"enabled": True}),
                             stop=Mock(side_effect=OSError("write failed"))))
        with patch.object(app.st, "session_state", state), \
             patch.object(app, "broker_for", return_value=running), \
             patch.object(app, "clear_broker_state") as clear:
            app._on_context_change()
        self.assertEqual(state["trading_environment"], "DEMO")
        self.assertEqual(state["active_environment"], "DEMO")
        self.assertIn("Could not stop DEMO entries", state["selection_error"])
        clear.assert_not_called()

    def test_each_environment_rejects_opposite_account_mode(self):
        for name in ("IC Markets", "Exness"):
            with self.subTest(broker=name):
                demo = broker_for(name)
                live = broker_for(name, "real")
                real_mt5 = terminal(name, 2)
                demo_mt5 = terminal(name, 0)
                with self.assertRaises(demo.bridge.DemoError):
                    demo.bridge.checked_account(real_mt5, read_only=True)
                self.assertEqual(live.bridge.checked_account(real_mt5, read_only=True).login, 123)
                with self.assertRaises(live.bridge.DemoError):
                    live.bridge.checked_account(demo_mt5, read_only=True)
                real_mt5.account_info.return_value.login = 999
                with self.assertRaises(live.bridge.DemoError):
                    live.bridge.checked_account(real_mt5, (123, real_mt5.account_info.return_value.server))

    def test_live_automation_and_manual_entry_require_explicit_confirmation(self):
        for name in ("IC Markets", "Exness"):
            with self.subTest(broker=name):
                auto = broker_for(name, "real").auto
                with self.assertRaisesRegex(auto.bridge.DemoError, "Confirm the real account"):
                    auto.arm((123, "server"), ["XAUUSD"], 0)
                with self.assertRaisesRegex(auto.bridge.DemoError, "Confirm the real account"):
                    auto.trade_row((123, "server"), "XAUUSD", 0, "BUY")

    def test_live_management_sends_once_and_stores_outcome(self):
        manager = broker_for("IC Markets", "real").module("trade_management")
        mt5 = terminal("IC Markets", 2)
        identity = (123, "ICMarkets-Live")
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(manager, "AUDIT", Path(folder) / "actions.sqlite3"), \
             patch.object(manager.bridge, "api", return_value=mt5), \
             patch.object(manager.auto, "process_guard", return_value=nullcontext()), \
             patch.object(manager, "record"):
            with self.assertRaises(manager.bridge.DemoError):
                manager._send(identity, "cancel", 8, {"action": 2}, lambda api: None)
            mt5.order_send.assert_not_called()
            result = manager._send(identity, "cancel", 8, {"action": 2},
                                   lambda api: None, confirm_live=True)
            self.assertEqual(result["state"], "filled")
            mt5.order_send.assert_called_once()
            with closing(sqlite3.connect(manager.AUDIT)) as db:
                self.assertEqual(db.execute("SELECT state FROM actions").fetchone()[0], "filled")

    def test_account_switch_after_broker_check_never_sends(self):
        manager = broker_for("Exness", "real").module("trade_management")
        mt5 = terminal("Exness", 2)
        identity = (123, "Exness-MT5Real")
        def switch_account(request):
            mt5.account_info.return_value.login = 999
            return NS(retcode=0, comment="ok")
        mt5.order_check.side_effect = switch_account
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(manager, "AUDIT", Path(folder) / "actions.sqlite3"), \
             patch.object(manager.bridge, "api", return_value=mt5), \
             patch.object(manager.auto, "process_guard", return_value=nullcontext()):
            with self.assertRaises(manager.bridge.DemoError):
                manager._send(identity, "close", 8, {"action": 1},
                              lambda api: None, confirm_live=True)
            mt5.order_send.assert_not_called()

    def test_unknown_management_result_blocks_another_attempt(self):
        manager = broker_for("IC Markets", "real").module("trade_management")
        mt5 = terminal("IC Markets", 2)
        mt5.order_send.return_value = None
        identity = (123, "ICMarkets-Live")
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(manager, "AUDIT", Path(folder) / "actions.sqlite3"), \
             patch.object(manager.bridge, "api", return_value=mt5), \
             patch.object(manager.auto, "process_guard", return_value=nullcontext()), \
             patch.object(manager, "record"):
            result = manager._send(identity, "cancel", 8, {"action": 2},
                                   lambda api: None, confirm_live=True)
            self.assertEqual(result["state"], "unknown")
            with self.assertRaisesRegex(manager.bridge.DemoError, "unresolved outcome"):
                manager._send(identity, "cancel", 8, {"action": 2},
                              lambda api: None, confirm_live=True)
            mt5.order_send.assert_called_once()

    def test_position_and_pending_actions_keep_ticket_and_size(self):
        manager = broker_for("IC Markets", "real").module("trade_management")
        mt5 = terminal("IC Markets", 2)
        mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_SELL = 0, 1
        mt5.ORDER_TYPE_BUY_LIMIT = 2
        mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_TIME_GTC = 1, 0, 0
        mt5.TRADE_ACTION_SLTP, mt5.TRADE_ACTION_MODIFY = 6, 7
        mt5.TRADE_ACTION_REMOVE, mt5.TRADE_ACTION_DEAL = 8, 1
        position = NS(ticket=42, identifier=420, symbol="XAUUSD", type=0,
                      volume=.01, sl=90., tp=110.)
        order = NS(ticket=43, symbol="XAUUSD", type=2, volume_initial=.02,
                   price_open=95., sl=90., tp=110., type_time=0,
                   time_expiration=0, price_stoplimit=0)
        mt5.positions_get = Mock(return_value=(position,))
        mt5.orders_get = Mock(return_value=(order,))
        mt5.symbol_info = Mock(return_value=NS(point=.01, digits=2,
                                               trade_stops_level=1, filling_mode=2))
        mt5.symbol_info_tick = Mock(return_value=NS(bid=100., ask=100.02))
        identity = (123, "ICMarkets-Live")
        with patch.object(manager.bridge, "api", return_value=mt5), \
             patch.object(manager.bridge, "quote", return_value=NS(bid=100., ask=100.02)), \
             patch.object(manager, "_send", return_value={"state": "filled"}) as send:
            with self.assertRaises(manager.bridge.DemoError):
                manager.update_stops(identity, 42, "XAUUSD", 89., 110., confirm_live=True)
            send.assert_not_called()
            manager.update_stops(identity, 42, "XAUUSD", 91., 110., confirm_live=True)
            self.assertEqual(send.call_args.args[3]["position"], 42)
            manager.update_pending_stops(identity, 43, "XAUUSD", 91., 110.,
                                         confirm_live=True)
            self.assertEqual(send.call_args.args[3]["order"], 43)
            manager.cancel_pending(identity, 43, "XAUUSD", confirm_live=True)
            self.assertEqual(send.call_args.args[3]["action"], 8)
            manager.close_position(identity, 42, "XAUUSD", 2, confirm_live=True)
            self.assertEqual(send.call_args.args[3]["volume"], .01)
            self.assertEqual(send.call_args.args[3]["position"], 42)

    def test_broker_history_uses_selected_live_runtime_and_account(self):
        deal = NS(ticket=7, symbol="XAUUSD", profit=2.0)
        deal._asdict = lambda: {"ticket": 7, "symbol": "XAUUSD", "profit": 2.0}
        mt5 = NS(history_deals_get=Mock(return_value=(deal,)))
        bridge = NS(LOCK=threading.RLock(), api=Mock(return_value=mt5), DemoError=RuntimeError)
        account = Mock()
        broker = NS(bridge=bridge, account=account)
        services.broker_deals.clear()
        with patch.object(services, "broker_for", return_value=broker) as select:
            rows = services.broker_deals("IC Markets", "real", (123, "ICMarkets-Live"))
        select.assert_called_once_with("IC Markets", "real")
        self.assertEqual(rows[0]["ticket"], 7)
        self.assertEqual(account.call_count, 2)


if __name__ == "__main__":
    unittest.main()

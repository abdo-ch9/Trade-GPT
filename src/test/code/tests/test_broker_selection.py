"""Broker selection must not share terminals, records, or account permissions."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from scalp_lab import mt5_demo as ic
from scalp_lab.paths import LIB_DIR as IC_DIR
from scalp_lab_exness import mt5_demo as exness
from scalp_lab_exness.gold_events import DB as EXNESS_EVENTS
from scalp_lab_exness.paths import LIB_DIR as EXNESS_DIR


def fake_mt5(company, server, mode):
    mt5 = NS(ACCOUNT_TRADE_MODE_DEMO=0, ACCOUNT_TRADE_MODE_REAL=2)
    mt5.initialize = Mock(return_value=True)
    mt5.account_info = Mock(return_value=NS(
        login=123, company=company, server=server, trade_mode=mode,
        trade_allowed=True, trade_expert=True))
    mt5.terminal_info = Mock(return_value=NS(
        connected=True, trade_allowed=True, tradeapi_disabled=False))
    return mt5


class BrokerSelectionTests(unittest.TestCase):
    def test_terminal_paths_are_selected_independently(self):
        ic_mt5 = fake_mt5('IC Markets', 'ICMarkets-Demo', 0)
        exness_mt5 = fake_mt5('Exness', 'Exness-Demo', 0)
        with patch.dict('os.environ', {'IC_MARKETS_MT5_PATH': r'C:\ic\terminal64.exe',
                                    'EXNESS_MT5_PATH': r'C:\exness\terminal64.exe'}):
            self.assertTrue(ic.initialize(ic_mt5))
            self.assertTrue(exness.initialize(exness_mt5))
        ic_mt5.initialize.assert_called_once_with(r'C:\ic\terminal64.exe', timeout=10000)
        exness_mt5.initialize.assert_called_once_with(r'C:\exness\terminal64.exe', timeout=10000)

    def test_broker_and_account_guards(self):
        ic_mt5 = fake_mt5('IC Markets', 'ICMarkets-Demo', 0)
        exness_mt5 = fake_mt5('Exness', 'Exness-Demo', 0)
        self.assertEqual(ic.checked_account(ic_mt5).login, 123)
        self.assertEqual(exness.checked_account(exness_mt5).login, 123)
        with self.assertRaises(ic.DemoError):
            ic.checked_account(exness_mt5)
        with self.assertRaises(exness.DemoError):
            exness.checked_account(ic_mt5)
        ic_mt5.account_info.return_value.trade_mode = 2
        with self.assertRaises(ic.DemoError):
            ic.checked_account(ic_mt5)
        exness_mt5.account_info.return_value.trade_mode = 2
        self.assertEqual(exness.checked_account(exness_mt5, read_only=True).login, 123)
        with self.assertRaises(exness.DemoError):
            exness.checked_account(exness_mt5, expected=(999, 'Exness-Demo'))

    def test_runtime_and_shared_modules_use_exness_path(self):
        self.assertNotEqual(IC_DIR, EXNESS_DIR)
        self.assertEqual(EXNESS_EVENTS.parent, EXNESS_DIR)
        self.assertEqual(exness.LEDGER.parent, EXNESS_DIR)


if __name__ == '__main__':
    unittest.main()

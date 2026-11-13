import unittest
from scalp_lab.gold_events import latest_trade_notice


class TradeNoticeTests(unittest.TestCase):
    def test_old_connection_error_is_never_a_trade_notice(self):
        self.assertIsNone(latest_trade_notice([{'kind': 'exit_delayed', 'time': 999, 'message': 'sign in'}], now=1000))

    def test_old_trades_expire_from_banner(self):
        self.assertIsNone(latest_trade_notice([{'kind': 'entry_filled', 'time': 600}], now=1000))

    def test_recent_trade_is_shown_even_with_newer_error(self):
        trade = {'kind': 'entry_filled', 'time': 990}
        self.assertEqual(latest_trade_notice([{'kind': 'error', 'time': 999}, trade], now=1000), trade)

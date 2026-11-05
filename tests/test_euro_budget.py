import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from scalp_lab import auto_demo as auto
from scalp_lab.mt5_demo import DemoError


class EuroBudgetTests(unittest.TestCase):
    def test_eur_account_needs_no_conversion(self):
        self.assertEqual(auto.daily_budget({'daily_loss_eur': 50}, 200, 'EUR'), 50)

    def test_usd_account_uses_fresh_verified_broker_bid(self):
        mt5 = Mock()
        mt5.symbol_info.return_value = SimpleNamespace(currency_base='EUR', currency_profit='USD')
        config = {'daily_loss_eur': 50, 'daily_loss_usd': 30, 'identity': [123, 'demo'], 'offset': 3}
        with patch.object(auto.bridge, 'api', return_value=mt5), patch.object(auto.bridge, 'checked_account') as check, patch.object(auto.bridge, 'quote', return_value=SimpleNamespace(bid=1.15)) as quote:
            self.assertAlmostEqual(auto.daily_budget(config, 200, 'USD'), 57.5)
            check.assert_called_once_with(mt5, config['identity'])
            quote.assert_called_once_with(mt5, 'EURUSD', 3)

    def test_stale_conversion_blocks_entries(self):
        mt5 = Mock()
        mt5.symbol_info.return_value = SimpleNamespace(currency_base='EUR', currency_profit='USD')
        with patch.object(auto.bridge, 'api', return_value=mt5), patch.object(auto.bridge, 'checked_account'), patch.object(auto.bridge, 'quote', side_effect=DemoError('stale')):
            with self.assertRaisesRegex(DemoError, 'stale'):
                auto.daily_budget({'daily_loss_eur': 50}, 200, 'USD')

    def test_invalid_euro_amounts_are_rejected(self):
        for amount in [True, -1, 0, float('nan'), '50']:
            with self.subTest(amount=amount), self.assertRaises(DemoError):
                auto.daily_budget({'daily_loss_eur': amount}, 200, 'EUR')

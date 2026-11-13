import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scalp_lab import auto_demo as auto
from scalp_lab.mt5_demo import DemoError


class SessionBindingTests(unittest.TestCase):
    def bind(self, config, symbols=('XAUUSD',)):
        mt5 = Mock()
        mt5.symbols_get.return_value = [SimpleNamespace(
            name='XAUUSD', currency_profit='USD', volume_min=.01,
            volume_max=100, volume_step=.01)]
        with patch.object(auto, 'settings', return_value=config), \
             patch.object(auto, 'process_guard', return_value=nullcontext()), \
             patch.object(auto.bridge, 'api', return_value=mt5), \
             patch.object(auto.bridge, 'checked_account'), \
             patch.object(auto, 'save') as save:
            result = auto.bind_stopped_session([321, 'Exness-MT5Trial'], list(symbols), 2)
            save.assert_called_once_with(result)
            mt5.order_send.assert_not_called()
            return result

    def test_rebind_preserves_consent_and_budget_without_arming(self):
        result = self.bind({'enabled': False, 'symbols': ['GOLD'],
                            'allow_unvalidated_demo': True, 'daily_loss_usd': 30})
        self.assertEqual(result['symbols'], ['XAUUSD'])
        self.assertEqual(result['identity'], [321, 'Exness-MT5Trial'])
        self.assertTrue(result['allow_unvalidated_demo'])
        self.assertEqual(result['daily_loss_usd'], 30)
        self.assertFalse(result['enabled'])
        self.assertEqual(result['expires'], 0)

    def test_rebind_does_not_grant_research_override(self):
        self.assertNotIn('allow_unvalidated_demo', self.bind({'enabled': False}))

    def test_running_session_cannot_be_rebound(self):
        with self.assertRaisesRegex(DemoError, 'Stop automation'):
            self.bind({'enabled': True})

    def test_unknown_instrument_cannot_be_bound(self):
        with self.assertRaisesRegex(DemoError, 'verified gold'):
            self.bind({'enabled': False}, ('GOLD',))

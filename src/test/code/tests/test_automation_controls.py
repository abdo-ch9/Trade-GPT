import unittest
from contextlib import ExitStack, nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scalp_lab import auto_demo as ic, auto_demo_ui
from scalp_lab_exness import auto_demo as exness, gold as exness_gold


class AutomationControlTests(unittest.TestCase):
    def test_trade_size_can_only_be_saved_while_stopped_and_on_broker_step(self):
        instrument = SimpleNamespace(name='XAUUSD', volume_min=.01,
                                     volume_max=1.0, volume_step=.01)
        for engine in (ic, exness):
            with self.subTest(broker=engine.__package__), ExitStack() as stack:
                config = {'enabled': False, 'symbols': ['XAUUSD'], 'lots': .01}
                stack.enter_context(patch.object(engine, 'settings', return_value=config))
                stack.enter_context(patch.object(engine, 'process_guard', return_value=nullcontext()))
                stack.enter_context(patch.object(engine.bridge, 'api',
                                                 return_value=SimpleNamespace(symbols_get=lambda: [instrument])))
                stack.enter_context(patch.object(engine, 'eligible_symbol', return_value=True))
                stack.enter_context(patch.object(engine, 'STATUS', {}))
                saved = stack.enter_context(patch.object(engine, 'save'))
                stack.enter_context(patch.object(engine, 'save_status'))
                self.assertEqual(engine.set_lots(.02)['lots'], .02)
                self.assertFalse(saved.call_args.args[0]['enabled'])
                with self.assertRaises(engine.bridge.DemoError):
                    engine.set_lots(.015)
                config['enabled'] = True
                with self.assertRaises(engine.bridge.DemoError):
                    engine.set_lots(.03)
                self.assertEqual(saved.call_count, 1)

    def test_entry_limits_save_without_starting_and_reject_invalid_values(self):
        for engine in (ic, exness):
            with self.subTest(broker=engine.__package__), ExitStack() as stack:
                config = {'enabled': False, 'daily_loss_fraction': .01,
                          'daily_loss_usd': 30, 'max_entries': 5}
                stack.enter_context(patch.object(engine, 'settings', return_value=config))
                stack.enter_context(patch.object(engine, 'process_guard', return_value=nullcontext()))
                stack.enter_context(patch.object(engine, 'STATUS', {}))
                saved = stack.enter_context(patch.object(engine, 'save'))
                stack.enter_context(patch.object(engine, 'save_status'))
                result = engine.set_entry_limits(2.0, 7)
                self.assertEqual(result['daily_loss_fraction'], .02)
                self.assertEqual(result['max_entries'], 7)
                self.assertIsNone(result['daily_loss_usd'])
                self.assertFalse(result['enabled'])
                for percentage, attempts in ((0, 7), (6, 7), (2, 0), (2, 21)):
                    with self.assertRaises(engine.bridge.DemoError):
                        engine.set_entry_limits(percentage, attempts)
                config['enabled'] = True
                with self.assertRaises(engine.bridge.DemoError):
                    engine.set_entry_limits(2, 7)
                self.assertEqual(saved.call_count, 1)

    def test_click_start_checks_news_and_validation_before_arming(self):
        for engine, ui, mode in ((ic, auto_demo_ui, None), (exness, exness, 'real')):
            with self.subTest(broker=engine.__package__), ExitStack() as stack:
                package = engine.__package__
                identity = (123, 'Test account')
                config = {'enabled': False, 'identity': list(identity),
                          'symbols': ['XAUUSD'], 'offset': 0}
                stack.enter_context(patch.object(engine, 'settings', return_value=config))
                stack.enter_context(patch.object(engine, 'eligible', return_value=['XAUUSD']))
                stack.enter_context(patch.object(engine, 'STATUS', {}))
                status_file = stack.enter_context(patch.object(engine, 'STATUS_FILE', MagicMock()))
                status_file.read_text.side_effect = FileNotFoundError()
                news = stack.enter_context(patch(f'{package}.xm_news.connection_status',
                                                 return_value=(False, 'News unavailable.')))
                validation = stack.enter_context(patch(f'{package}.gold.execution_validation',
                                                       return_value=(False, 'Validation missing.')))
                stack.enter_context(patch(f'{package}.gold_worker.ensure_running'))
                stack.enter_context(patch(f'{package}.gold_worker.status', return_value={}))
                stack.enter_context(patch(f'{package}.gold_events.recent', return_value=[]))
                arm = stack.enter_context(patch.object(engine, 'arm',
                    side_effect=lambda *args, **kwargs: config.update(enabled=True)))
                st = MagicMock()
                start, stop = MagicMock(), MagicMock()
                st.columns.return_value = (start, stop)
                start.button.return_value = True
                stop.button.return_value = False
                stack.enter_context(patch.dict('sys.modules', {'streamlit': st}))
                render_options = {'mode': mode} if mode else {}

                ui.render(identity, [], 0, **render_options)
                self.assertFalse(start.button.call_args.kwargs['disabled'])
                st.warning.assert_called_once_with('News unavailable. Validation missing.')
                arm.assert_not_called()

                news.return_value = (True, 'News configured.')
                validation.return_value = (True, 'Validation passed.')
                ui.render(identity, [], 0, **render_options)
                arm.assert_called_once_with(identity, ['XAUUSD'], 0)
                st.rerun.assert_called_once()

                if mode == 'real':
                    config['enabled'] = False
                    arm.reset_mock()
                    start.button.reset_mock()
                    start.button.side_effect = lambda *args, **kwargs: (
                        kwargs['key'] == 'start_real_holdout_override'
                    )
                    validation.return_value = (False, exness_gold.HOLDOUT_FAILURE)
                    news.return_value = (False, 'News unavailable.')
                    ui.render(identity, [], 0, **render_options)
                    arm.assert_not_called()
                    self.assertEqual(start.button.call_count, 1)

                    news.return_value = (True, 'News configured.')
                    ui.render(identity, [], 0, **render_options)
                    arm.assert_called_once_with(identity, ['XAUUSD'], 0,
                                                override_live_validation=True)

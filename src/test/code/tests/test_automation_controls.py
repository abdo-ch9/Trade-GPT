import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from scalp_lab import auto_demo as ic, auto_demo_ui
from scalp_lab_exness import auto_demo as exness, gold as exness_gold


class AutomationControlTests(unittest.TestCase):
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

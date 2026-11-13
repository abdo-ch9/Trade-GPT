import tempfile

import time

import unittest

from pathlib import Path

from types import SimpleNamespace

from unittest.mock import patch,Mock

import pandas as pd

from test_mt5_demo import terminal

from scalp_lab import auto_demo as auto

from scalp_lab.mt5_demo import DemoError





class AutoDemoTests(unittest.TestCase):

    def setUp(self):

        self.tmp=tempfile.TemporaryDirectory()

        self.addCleanup(self.tmp.cleanup)

        self.db=Path(self.tmp.name)/'auto.sqlite3'

        self.mt5=terminal()

        self.mt5.account_info.return_value.equity=10000

        self.config={'enabled':True,'identity':[123,'Exness-MT5Trial'],'symbols':['GOLD'],

                     'offset':2,'lots':.01,'max_entries':5,'daily_loss_fraction':.01,

                     'engine':auto.ENGINE,'horizon':5,'expires':time.time()+1000,'run_id':'test'}

        self.result={'action':'BUY setup','observed_at':time.time(),

                     'engine':auto.ENGINE,

                     'news':{'status':'ready','relevant':True,'direction':'BUY','high_risk':False,

                             'checked_at':time.time(),'expires_at':time.time()+300,

                             'evidence_ids':['a'],'articles':[{'id':'a','published_at':time.time()-60}]},

                     'frame':pd.DataFrame({'time':[time.time()+7200-65]}),

                     'scenarios':{'BUY':{'tp_bps':20,'sl_bps':10}}}

        for name,value in [('api',self.mt5),('preview',{'request':{},'loss':-10}),

                           ('submit',{'state':'filled','message':'Done'})]:

            p=patch.object(auto.bridge,name,return_value=value)

            setattr(self,name,p.start()); self.addCleanup(p.stop)

        p=patch.object(auto,'settings',return_value=self.config)

        p.start(); self.addCleanup(p.stop)

        p=patch.object(auto,'stop')

        self.stop=p.start(); self.addCleanup(p.stop)

        p=patch('scalp_lab.gold.validation',return_value=(True,'Test validation fixture'))

        p.start(); self.addCleanup(p.stop)

        from scalp_lab.gold_exits import EXIT_POLICY

        p=patch('scalp_lab.gold_worker.status',side_effect=lambda:{'heartbeat':time.time(),

                'last_exit_check':time.time(),'exit_policy':EXIT_POLICY,'exit_error':None})

        p.start(); self.addCleanup(p.stop)

        p=patch.object(auto,'record')

        p.start(); self.addCleanup(p.stop)



    def execute(self):

        return auto.execute(self.config,'GOLD',self.result,self.db)



    def test_fixed_30_usd_budget_replaces_percent_on_small_account(self):

        self.config['daily_loss_usd']=30

        self.mt5.account_info.return_value.equity=119

        self.preview.return_value['loss']=-15.4

        self.assertEqual(self.execute()['state'],'filled')



    def test_fixed_budget_counts_cost_reserve(self):

        self.config['daily_loss_usd']=30

        self.preview.return_value['loss']=-26

        with self.assertRaisesRegex(DemoError,'remaining daily budget'):

            self.execute()

        self.submit.assert_not_called()



    def test_fixed_budget_counts_existing_daily_loss(self):

        self.config['daily_loss_usd']=30

        auto.record_day(self.config['identity'],10000,self.db)

        self.mt5.account_info.return_value.equity=9980

        self.preview.return_value['loss']=-10

        with self.assertRaisesRegex(DemoError,'remaining daily budget'):

            self.execute()

        self.submit.assert_not_called()



    def test_usd_budget_does_not_silently_use_other_currency(self):

        with self.assertRaises(DemoError):

            auto.daily_budget({'daily_loss_usd':30},100,'EUR')



    def test_final_equity_refresh_blocks_new_loss(self):

        from copy import copy

        initial=self.mt5.account_info.return_value

        changed=copy(initial)

        changed.equity=9800

        self.mt5.account_info.side_effect=[initial,changed]

        with self.assertRaisesRegex(DemoError,'Combined account stop risk'):

            self.execute()

        self.submit.assert_not_called()



    def test_missing_exit_worker_blocks_entry(self):

        with patch('scalp_lab.gold_worker.status',return_value={}):

            with self.assertRaisesRegex(DemoError,'watchdog'):

                self.execute()

        self.submit.assert_not_called()



    def test_stale_other_position_explains_account_risk_and_blocks_send(self):

        self.mt5.positions_get.return_value=[SimpleNamespace(symbol='Tesla',volume=.1,sl=379.04,type=0)]

        with patch.object(auto.bridge,'quote',side_effect=DemoError('No fresh Exness quote for Tesla.')):

            with self.assertRaisesRegex(DemoError,'Account risk check blocked: an existing Tesla position'):

                self.execute()

        self.preview.assert_not_called()

        self.submit.assert_not_called()



    def test_explicit_tesla_exclusion_skips_only_tesla(self):

        positions=[SimpleNamespace(symbol='Tesla',volume=.1,sl=0,type=0),

                   SimpleNamespace(symbol='Other',volume=.1,sl=100,type=0)]

        self.mt5.order_calc_profit.return_value=-5

        with patch.object(auto.bridge,'quote',return_value=SimpleNamespace(bid=110,ask=111)) as quote:

            risk=auto.portfolio_stop_risk(self.mt5,positions,2,exclude_tesla=True)

        self.assertEqual(risk,5)

        quote.assert_called_once_with(self.mt5,'Other',2)



    def test_tesla_exclusion_allows_entry_without_tesla_quote(self):

        self.config['exclude_tesla_stop_risk']=True

        self.mt5.positions_get.return_value=[SimpleNamespace(symbol='Tesla',volume=.1,sl=379.04,type=0)]

        with patch.object(auto.bridge,'quote',side_effect=DemoError('Stale Tesla')) as quote:

            self.assertEqual(self.execute()['state'],'filled')

        quote.assert_not_called()

        self.submit.assert_called_once()



    def test_gold_validation_cannot_be_bypassed_by_buy_label(self):

        with patch('scalp_lab.gold.validation',return_value=(False,'No evidence')):

            with self.assertRaises(DemoError):

                self.execute()

        self.submit.assert_not_called()



    def test_explicit_demo_override_allows_failed_research(self):

        self.config['allow_unvalidated_demo']=True

        with patch('scalp_lab.gold.validation',return_value=(False,'Failed research')):

            self.assertEqual(self.execute()['state'],'filled')

        self.submit.assert_called_once()



    def test_demo_override_keeps_loss_budget(self):

        self.config['allow_unvalidated_demo']=True

        self.preview.return_value['loss']=-200

        with patch('scalp_lab.gold.validation',return_value=(False,'Failed research')):

            with self.assertRaises(DemoError):

                self.execute()

        self.submit.assert_not_called()



    def test_demo_override_keeps_news_requirement(self):

        self.config['allow_unvalidated_demo']=True

        self.result['news']={'status':'not_connected'}

        with self.assertRaises(DemoError):

            self.execute()

        self.submit.assert_not_called()



    def test_revoked_override_prevents_submission(self):

        self.config['allow_unvalidated_demo']=True

        def revoke(*args,**kwargs):

            self.config['allow_unvalidated_demo']=False

            return {'request':{},'loss':-10}

        self.preview.side_effect=revoke

        with patch('scalp_lab.gold.validation',return_value=(False,'Failed research')):

            with self.assertRaises(DemoError):

                self.execute()

        self.submit.assert_not_called()



    def test_non_gold_instrument_is_rejected(self):

        self.config['symbols']=['EURUSD']

        with self.assertRaises(DemoError):

            auto.execute(self.config,'EURUSD',self.result,self.db)

        self.submit.assert_not_called()



    def test_manual_row_uses_fixed_size_budget_and_dedup_while_stopped(self):

        self.config['enabled']=False

        self.config['expires']=time.time()-10

        outcome=auto.execute(self.config,'GOLD',self.result,self.db,manual=True)

        self.assertEqual(outcome['state'],'filled')

        self.assertEqual(self.preview.call_args.args[3],.01)

        self.assertEqual(auto.execute(self.config,'GOLD',self.result,self.db,manual=True)['state'],'waiting')

        self.submit.assert_called_once()

        self.assertFalse(self.config['enabled'])



    def test_manual_row_rejected_during_automation(self):

        with self.assertRaises(DemoError):

            auto.execute(self.config,'GOLD',self.result,self.db,manual=True)

        self.submit.assert_not_called()



    def test_manual_row_keeps_daily_loss_limit(self):

        self.config['enabled']=False

        self.preview.return_value['loss']=-100

        with self.assertRaises(DemoError):

            auto.execute(self.config,'GOLD',self.result,self.db,manual=True)

        self.submit.assert_not_called()



    def test_row_click_rechecks_direction_before_execution(self):

        from contextlib import nullcontext

        from scalp_lab import gold as gold_module

        self.config['enabled']=False

        with patch.object(auto,'process_guard',return_value=nullcontext()), \
             patch.object(gold_module,'snapshot',return_value=({'action':'SELL setup'},{})), \
             patch.object(auto,'execute') as execute:

            with self.assertRaises(DemoError):

                auto.trade_row(self.config['identity'],'GOLD',2,'BUY')

            execute.assert_not_called()



    def test_manual_row_aborts_if_automation_starts_during_preview(self):

        self.config['enabled']=False

        def changed(*args,**kwargs):

            self.config['enabled']=True

            return {'request':{},'loss':-10}

        self.preview.side_effect=changed

        with self.assertRaises(DemoError):

            auto.execute(self.config,'GOLD',self.result,self.db,manual=True)

        self.submit.assert_not_called()



    def test_pending_order_allows_analysis_but_blocks_submission(self):

        from contextlib import nullcontext

        from scalp_lab import gold as gold_module

        self.result['news']['articles'][0]['url']='https://example.com/news'

        self.mt5.orders_get.return_value=[SimpleNamespace(symbol='GBPUSD')]

        with patch.object(auto,'process_guard',return_value=nullcontext()), \
             patch.object(auto,'record_day'), patch.object(auto,'save_status'), \
             patch.object(auto,'LAST_SCAN',0), patch.object(auto,'CURSOR',0), \
             patch.object(auto,'STATUS',{}), \
             patch.object(gold_module,'snapshot',return_value=(self.result,{})) as snapshot:

            auto.scan(self.config['identity'],2)

            snapshot.assert_called_once()

            self.assertIn('GBPUSD',auto.STATUS['Account']['message'])

            self.assertEqual(auto.STATUS['GOLD']['state'],'waiting')

            self.assertIn('pending order',auto.STATUS['GOLD']['message'])

        self.submit.assert_not_called()



    def test_qualified_setup_submits_fixed_size_and_deduplicates(self):

        self.assertEqual(self.execute()['state'],'filled')

        self.assertEqual(self.preview.call_args.args[3],.01)

        self.assertEqual(self.execute()['state'],'waiting')

        self.submit.assert_called_once()



    def test_wait_and_unvalidated_do_not_submit(self):

        for action in ['WAIT','MODEL NOT VALIDATED']:

            self.result['action']=action

            self.execute()

        self.submit.assert_not_called()



    def test_news_required_even_for_buy_setup(self):

        for news in [{}, {'status':'not_connected'},

                     dict(self.result['news'],direction='SELL'),

                     dict(self.result['news'],high_risk=True),

                     dict(self.result['news'],expires_at=time.time()-1)]:

            with self.subTest(news=news), patch.dict(self.result,news=news):

                with self.assertRaises(DemoError):self.execute()

        self.submit.assert_not_called()



    def test_legacy_model_cannot_submit(self):

        self.result['engine']='conditional-direction-cost-policy-v4'

        with self.assertRaises(DemoError):self.execute()

        self.submit.assert_not_called()



    def test_live_account_cannot_use_demo_validation_override(self):
        self.mt5.account_info.return_value.trade_mode = self.mt5.ACCOUNT_TRADE_MODE_REAL
        self.mt5.account_info.return_value.server = 'Exness-MT5Real'
        self.config['identity'] = [123, 'Exness-MT5Real']
        self.config['allow_unvalidated_demo'] = True
        with patch('scalp_lab.gold.validation', return_value=(False, 'Failed historical evaluation')):
            with self.assertRaisesRegex(DemoError, 'Failed historical evaluation'):
                self.execute()
        self.submit.assert_not_called()

    def test_validated_live_account_can_submit_through_existing_gates(self):
        self.mt5.account_info.return_value.trade_mode = self.mt5.ACCOUNT_TRADE_MODE_REAL
        self.mt5.account_info.return_value.server = 'Exness-MT5Real'
        self.config['identity'] = [123, 'Exness-MT5Real']
        self.assertEqual(self.execute()['state'], 'filled')
        self.submit.assert_called_once()

    def test_changed_account_blocked(self):
        self.mt5.account_info.return_value.login = 999
        with self.assertRaises(DemoError):
            self.execute()
        self.submit.assert_not_called()


    def test_existing_positions_pending_orders_and_unavailable_exposure(self):

        for value in [(SimpleNamespace(symbol='GOLD'),),None]:

            self.mt5.positions_get.return_value=value

            if value is None:

                with self.assertRaises(DemoError):self.execute()

            else:self.assertEqual(self.execute()['state'],'waiting')

        self.mt5.positions_get.return_value=()

        self.mt5.orders_get.return_value=(SimpleNamespace(symbol='GOLD'),)

        self.assertEqual(self.execute()['state'],'waiting')

        self.submit.assert_not_called()



    def test_expired_analysis_candle_and_session(self):

        self.result['observed_at']=time.time()-16

        with self.assertRaises(DemoError):self.execute()

        self.result['observed_at']=time.time()

        self.result['frame']['time']-=200

        with self.assertRaises(DemoError):self.execute()

        self.config['expires']=0

        with self.assertRaises(DemoError):self.execute()

        self.submit.assert_not_called()



    def test_daily_cap_survives_repeated_execution(self):

        self.config['max_entries']=1

        self.execute()

        with self.assertRaisesRegex(DemoError,'entry attempts'):self.execute()

        self.submit.assert_called_once()



    def test_equity_limit_and_estimated_stop_budget(self):

        self.preview.return_value['loss']=-90

        with self.assertRaisesRegex(DemoError,'remaining daily budget'):self.execute()

        self.preview.return_value['loss']=-10

        self.mt5.account_info.return_value.equity=9899

        with self.assertRaisesRegex(DemoError,'equity loss limit'):self.execute()

        self.submit.assert_not_called()



    def test_pre_send_quote_change_skips_signal_and_leaves_automation_running(self):
        self.submit.side_effect = auto.bridge.EntryQuoteMoved('Quote moved')
        self.assertEqual(self.execute()['state'], 'skipped')
        self.assertEqual(self.execute()['state'], 'waiting')
        self.submit.assert_called_once()
        self.stop.assert_not_called()

    def test_ambiguous_result_stops_and_never_retries(self):

        self.submit.return_value={'state':'unknown','message':'No response'}

        self.execute()

        self.stop.assert_called_once()

        with self.assertRaisesRegex(DemoError,'Unresolved'):self.execute()

        self.submit.assert_called_once()



    def test_disallowed_size_symbol_and_stop_before_send(self):

        self.config['lots']=.02

        with self.assertRaises(DemoError):self.execute()

        self.config['lots']=.01

        self.config['symbols']=[]

        with self.assertRaises(DemoError):self.execute()

        self.config['symbols']=['GOLD']

        with patch.object(auto,'settings',return_value={'enabled':False}):

            with self.assertRaises(DemoError):self.execute()

        self.submit.assert_not_called()





    def test_process_guard_thread_serialization(self):

        import threading

        results = []

        def worker(idx):

            with auto.process_guard():

                results.append(f"start_{idx}")

                time.sleep(0.02)

                results.append(f"end_{idx}")

        t1 = threading.Thread(target=worker, args=(1,))

        t2 = threading.Thread(target=worker, args=(2,))

        t1.start()

        t2.start()

        t1.join()

        t2.join()

        self.assertEqual(len(results), 4)

        self.assertTrue(

            results == ['start_1', 'end_1', 'start_2', 'end_2'] or

            results == ['start_2', 'end_2', 'start_1', 'end_1']

        )





if __name__=='__main__':unittest.main()

import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
import pandas as pd
from scalp_lab import xm_chart as chart
from scalp_lab import xm_news as news


def candles(direction=1):
    # Aligned, completed M5 groups. A steady synthetic trend tests both directions.
    start=1800000000
    close=1.1+direction*np.arange(300)*.00003
    return pd.DataFrame({'time':start+np.arange(300)*60,'open':close-direction*.00002,
        'high':close+.00005,'low':close-.00005,'close':close,'tick_volume':100})


def current_news(direction='NEUTRAL', now=None):
    now=time.time() if now is None else now
    return {'status':'ready','direction':direction,'relevant':True,'high_risk':False,
        'checked_at':now,'expires_at':now+300,'reason':'Cited test evidence',
        'articles':[{'id':'a','published_at':now-60,'url':'https://example.com/news'}],
        'evidence_ids':['a']}


class ChartTests(unittest.TestCase):
    def assess(self, direction=1, news_override=None, spread=.00002, age=5):
        b=candles(direction)
        close=b.iloc[-1].close
        return chart.assess_chart(b,.00001,close,close+spread,b.time.iloc[-1]+60+age,
                                  current_news() if news_override is None else news_override)

    def test_both_sides_can_qualify_without_training(self):
        for direction, side in [(1,'BUY'),(-1,'SELL')]:
            result=self.assess(direction)
            self.assertEqual(result['action'],side+' setup')
            self.assertEqual(result['chart_signal'],side)
            level=result['scenarios'][side]
            self.assertLess(level['sl'],level['entry']) if side=='BUY' else self.assertGreater(level['sl'],level['entry'])
            self.assertAlmostEqual(level['tp_bps']/level['sl_bps'],2)

    def test_missing_news_keeps_direction_but_blocks_orders(self):
        r=self.assess(news_override={'status':'not_connected','reason':'Need key'})
        self.assertEqual(r['chart_signal'],'BUY')
        self.assertEqual(r['action'],'AI NEWS NOT CONNECTED')

    def test_news_conflict_risk_expiry_and_missing_evidence(self):
        for changes, action in [({'direction':'SELL'},'NEWS CONFLICT'),
                                ({'high_risk':True},'NEWS RISK'),
                                ({'expires_at':time.time()-1},'NEWS UNAVAILABLE'),
                                ({'evidence_ids':['invented']},'NEWS UNAVAILABLE'),
                                ({'relevant':False},'NEWS UNAVAILABLE')]:
            self.assertEqual(self.assess(news_override=dict(current_news(),**changes))['action'],action)

    def test_stale_candles_and_wide_spread_cannot_trade(self):
        self.assertEqual(self.assess(age=200)['action'],'DATA STALE')
        self.assertEqual(self.assess(spread=.002)['action'],'SPREAD TOO WIDE')

    def test_m5_uses_only_completed_full_buckets_and_resets_gaps(self):
        b=candles()
        _,higher=chart.chart_frames(b,b.time.iloc[-1]+30)
        self.assertEqual(len(higher),59)
        _,higher=chart.chart_frames(b.drop(index=250),b.time.iloc[-1]+65)
        self.assertLess(len(higher),10)

    def test_flat_market_does_not_force_direction(self):
        b=candles(0)
        result=chart.assess_chart(b,.00001,1.1,1.10001,b.time.iloc[-1]+65,current_news())
        self.assertEqual(result['chart_signal'],'MIXED')
        self.assertEqual(result['action'],'NO CLEAR SETUP')

    def test_snapshot_fetches_bars_after_news_and_never_trains(self):
        b=candles()
        events=[]
        mt5=Mock()
        mt5.symbol_info.return_value=SimpleNamespace(point=.00001,trade_stops_level=0)
        mt5.order_calc_profit.return_value=-2.5
        mt5.copy_rates_from_pos.side_effect=lambda *a: events.append('bars') or b.to_records(index=False)
        with patch.object(chart,'get_news',side_effect=lambda *a,**kw: events.append('news') or current_news()), \
             patch.object(chart.bridge,'api',return_value=mt5), \
             patch.object(chart.bridge,'checked_account',return_value=SimpleNamespace(currency='USD',equity=1000)), \
             patch.object(chart.bridge,'quote',return_value=SimpleNamespace(bid=b.close.iloc[-1],ask=b.close.iloc[-1]+.00002)), \
             patch.object(chart.time,'time',return_value=b.time.iloc[-1]+65):
            result,_=chart.snapshot((1,'Demo'),'EURUSD',0)
        self.assertEqual(events,['bars','news','bars'])
        self.assertEqual(result['engine'],chart.ENGINE)

    def test_broker_risk_uses_equity_and_fixed_lot_for_both_sides(self):
        mt5=Mock()
        mt5.order_calc_profit.return_value=-2.5
        result={'scenarios':{'BUY':{'entry':1.2,'sl':1.1},'SELL':{'entry':1.2,'sl':1.3}}}
        chart.add_scenario_risk(result,mt5,'EURUSD',SimpleNamespace(currency='USD',equity=1000))
        for side in result['scenarios'].values():
            self.assertEqual(side['lots'],.01)
            self.assertEqual(side['risk_amount'],2.5)
            self.assertEqual(side['risk_pct'],.25)
        self.assertEqual(mt5.order_calc_profit.call_args_list[0].args,(mt5.ORDER_TYPE_BUY,'EURUSD',.01,1.2,1.1))
        self.assertEqual(mt5.order_calc_profit.call_args_list[1].args,(mt5.ORDER_TYPE_SELL,'EURUSD',.01,1.2,1.3))
        for invalid in (None,float('nan'),float('inf'),2.5):
            mt5.order_calc_profit.return_value=invalid
            chart.add_scenario_risk(result,mt5,'EURUSD',SimpleNamespace(currency='USD',equity=1000))
            self.assertIsNone(result['scenarios']['BUY']['risk_pct'])
        mt5.order_calc_profit.return_value=-2.5
        chart.add_scenario_risk(result,mt5,'EURUSD',SimpleNamespace(currency='USD',equity=0))
        self.assertIsNone(result['scenarios']['BUY']['risk_pct'])

    def test_history_sync_recovers_without_changing_offset(self):
        fresh=candles()
        stale=fresh.copy()
        stale.time-=3600
        now=fresh.time.iloc[-1]+65-7200
        mt5=Mock()
        mt5.copy_rates_from_pos.return_value=stale.to_records(index=False)
        mt5.copy_rates_from.return_value=fresh.to_records(index=False)
        with patch.object(chart.time,'time',return_value=now), patch.object(chart.time,'sleep') as sleep:
            rates=chart.recent_rates(mt5,'EURUSD',2)
        self.assertEqual(rates[-1]['time'],fresh.time.iloc[-1])
        self.assertEqual(mt5.copy_rates_from.call_args.args[2].timestamp(),now+7200)
        sleep.assert_called_once_with(.5)

    def test_history_sync_is_bounded_and_still_blocks_stale_data(self):
        b=candles()
        now=b.time.iloc[-1]+3600
        mt5=Mock()
        mt5.copy_rates_from_pos.return_value=b.to_records(index=False)
        mt5.copy_rates_from.return_value=b.to_records(index=False)
        with patch.object(chart.time,'time',return_value=now), patch.object(chart.time,'sleep') as sleep:
            rates=chart.recent_rates(mt5,'EURUSD',0)
        self.assertEqual(sleep.call_count,4)
        self.assertEqual(mt5.copy_rates_from.call_count,4)
        result=chart.assess_chart(pd.DataFrame(rates),.00001,1.1,1.10001,now,current_news())
        self.assertEqual(result['action'],'DATA STALE')

    def test_future_history_does_not_pass_refresh(self):
        b=candles()
        mt5=Mock()
        mt5.copy_rates_from_pos.return_value=b.to_records(index=False)
        mt5.copy_rates_from.return_value=b.to_records(index=False)
        with patch.object(chart.time,'time',return_value=b.time.iloc[0]-100), patch.object(chart.time,'sleep'):
            rates=chart.recent_rates(mt5,'EURUSD',0)
        self.assertEqual(mt5.copy_rates_from.call_count,4)
        result=chart.assess_chart(pd.DataFrame(rates),.00001,1.1,1.10001,b.time.iloc[0]-100,current_news())
        self.assertEqual(result['action'],'DATA UNAVAILABLE')


class NewsTests(unittest.TestCase):
    def test_exness_suffixed_gold_uses_gold_headlines(self):
        response = Mock(content=b'<rss><channel/></rss>')
        with patch.object(news.requests, 'get', return_value=response) as get:
            self.assertEqual(news.fetch_headlines('XAUUSDm', 1800000000), [])
        self.assertIn('Treasury yields', get.call_args.kwargs['params']['q'])
        self.assertTrue(news.pair_name('XAUUSDm').startswith('XAU/USD'))

    def tearDown(self):
        news.CACHE.clear()
        news.HEALTH.clear()

    def test_no_key_skips_network_for_scanner(self):
        with patch.object(news,'configuration',return_value={'provider':'openai','key':'','model':'test','url':'http://127.0.0.1:11434'}), patch.object(news.requests,'get') as get:
            result=news.get_news('EURUSD')
        self.assertEqual(result['status'],'not_connected')
        get.assert_not_called()

    def test_feed_rejects_undated_old_future_and_unsafe_links(self):
        from email.utils import formatdate
        now=time.time()
        items=''.join(f'<item><title>{i}</title><link>{url}</link><pubDate>{stamp}</pubDate></item>'
            for i,(url,stamp) in enumerate([
                ('https://example.com/a',formatdate(now-60,usegmt=True)),
                ('https://example.com/b',formatdate(now+3600,usegmt=True)),
                ('https://example.com/c',formatdate(now-90000,usegmt=True)),
                ('javascript:bad',formatdate(now-60,usegmt=True)),
                ('https://example.com/d','')]))
        parsed=news.parse_headlines('<rss><channel>'+items+'</channel></rss>',now)
        self.assertEqual([a['title'] for a in parsed],['0'])

    def test_ai_must_cite_real_headline_ids(self):
        import json
        response=Mock()
        response.json.return_value={'status':'completed','output':[{'content':[
            {'type':'output_text','text':json.dumps({'direction':'BUY','relevant':True,
                'high_risk':False,'reason':'Test','evidence_ids':['invented']})}]}]}
        with patch.object(news.requests,'post',return_value=response):
            with self.assertRaises(ValueError):
                news.interpret('EURUSD',[{'id':'real'}],'test-key','test',time.time())

    def test_provider_failure_never_becomes_neutral(self):
        with patch.object(news,'configuration',return_value={'provider':'openai','key':'test-key','model':'test','url':'http://127.0.0.1:11434'}), \
             patch.object(news,'fetch_headlines',side_effect=news.requests.Timeout()):
            result=news.get_news('EURUSD')
        self.assertEqual(result['status'],'unavailable')
        self.assertIsNone(result['direction'])

    def test_ollama_uses_local_structured_chat_without_api_key(self):
        import json
        verdict={'direction':'BUY','relevant':True,'high_risk':False,'reason':'Test','evidence_ids':['real']}
        response=Mock()
        response.json.return_value={'done':True,'done_reason':'stop','message':{'content':json.dumps(verdict)}}
        with patch.object(news.requests,'post',return_value=response) as post:
            result=news.interpret('EURUSD',[{'id':'real'}],'','local-model',time.time(),provider='ollama')
        self.assertEqual(result,verdict)
        self.assertEqual(post.call_args.args[0],'http://127.0.0.1:11434/api/chat')
        self.assertNotIn('headers',post.call_args.kwargs)
        self.assertEqual(post.call_args.kwargs['json']['format']['type'],'object')
        self.assertFalse(post.call_args.kwargs['json']['stream'])

    def test_ollama_rejects_partial_response_and_remote_url(self):
        response=Mock()
        response.json.return_value={'done':True,'done_reason':'length','message':{'content':'{}'}}
        with patch.object(news.requests,'post',return_value=response):
            with self.assertRaises(ValueError):
                news.interpret('EURUSD',[],'','test',time.time(),provider='ollama')
        with patch.object(news.requests,'post') as post:
            with self.assertRaises(ValueError):
                news.interpret('EURUSD',[],'','test',time.time(),provider='ollama',base_url='https://remote.example')
            post.assert_not_called()

    def test_ollama_requires_installed_model_and_service(self):
        cfg={'provider':'ollama','model':'installed','url':'http://127.0.0.1:11434','key':''}
        response=Mock()
        response.json.return_value={'models':[{'name':'installed'}]}
        with patch.object(news.requests,'get',return_value=response):
            self.assertTrue(news.connection_status(cfg)[0])
            self.assertFalse(news.connection_status(dict(cfg,model='missing'))[0])
        news.HEALTH.clear()
        with patch.object(news.requests,'get',side_effect=news.requests.ConnectionError()):
            self.assertFalse(news.connection_status(cfg)[0])


if __name__=='__main__':unittest.main()

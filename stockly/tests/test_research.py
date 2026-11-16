import asyncio
import os
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
from app.main import app
from app.research.evidence import Study, study, summary
from app.research import search

client=TestClient(app)


def bars(n=300):
    return [{'date':1600000000+i*86400,'open':100+i,'high':102+i,'low':99+i,
             'close':101+i,'volume':10000} for i in range(n)]


class ResearchTests(unittest.TestCase):
    def test_study_split_costs(self):
        d=study(Study(symbol='TEST',candles=bars()))
        self.assertGreater(d['holdout']['sample_size'],0)
        self.assertIsNone(d['forecast_probability'])
        self.assertFalse(d['news_conditioned'])
        self.assertEqual(d['all_history']['historical_net_win_frequency'],1)
        for t in d['recent_trades']:
            if t['partition']=='development':
                self.assertLess(t['exit_bar_at'],d['holdout_start'])
            else:
                self.assertGreaterEqual(t['signal_at'],d['holdout_start'])
        self.assertTrue(all(a['exit_bar_at']<b['entry_at'] for a,b in zip(d['recent_trades'],d['recent_trades'][1:])))

    def test_costs_turn_flat_prices_into_losses(self):
        candles=bars()
        for c in candles:
            c.update(open=100,high=100,low=100,close=100)
        d=study(Study(symbol='TEST',candles=candles,rule='unconditional'))
        self.assertEqual(d['all_history']['historical_net_win_frequency'],0)
        self.assertLess(d['all_history']['mean_net_profit_inr'],0)

    def test_no_matches_and_interval(self):
        d=study(Study(symbol='TEST',candles=bars(),rule='below_sma'))
        self.assertIsNone(d['all_history']['historical_net_win_frequency'])
        self.assertIsNone(summary([])['wilson_95_interval_iid_approximation'])
        s=summary([{'net_profit':1,'net_return_pct':1}]*5+[{'net_profit':-1,'net_return_pct':-1}]*5)
        self.assertAlmostEqual(s['wilson_95_interval_iid_approximation'][0],.236593,places=5)

    def test_routes_and_validation(self):
        self.assertEqual(client.get('/api/research/guide').status_code,200)
        self.assertEqual(client.post('/api/research/evidence',json={'symbol':'TEST','candles':bars()}).status_code,200)
        for extra in ({'side':'short'},{'horizon_bars':0},{'quantity':0},{'candles':bars()[::-1]}):
            self.assertEqual(client.post('/api/research/evidence',json={'symbol':'TEST','candles':bars(),**extra}).status_code,422)
        with patch('app.research.routes.yahoo.get_history',new=AsyncMock(return_value={'candles':bars()})):
            self.assertEqual(client.get('/api/research/historical/TCS').status_code,200)
        self.assertEqual(client.get('/api/research/historical/TCS?side=short').status_code,422)
        self.assertEqual(client.get('/api/research/historical/TCS?interval=5m').status_code,422)

    def test_intraday_no_overnight_or_late_fills(self):
        candles=[]
        for day in range(5):
            start=datetime(2024,1,1,9,15,tzinfo=ZoneInfo('Asia/Kolkata'))+timedelta(days=day)
            for j in range(75):
                c=bars(1)[0];c['date']=int((start+timedelta(minutes=j*5)).timestamp());candles.append(c)
        d=study(Study(symbol='TEST',candles=candles,interval='5m',side='short',rule='unconditional'))
        self.assertGreater(d['all_history']['sample_size'],0)
        for t in d['recent_trades']:
            a=datetime.fromtimestamp(t['entry_at'],ZoneInfo('Asia/Kolkata'))
            b=datetime.fromtimestamp(t['exit_bar_at']+300,ZoneInfo('Asia/Kolkata'))
            self.assertEqual(a.date(),b.date())
            self.assertLessEqual((b.hour,b.minute),(15,15))

    def test_holdout_cannot_change_development(self):
        original=bars()
        changed=bars()
        for c in changed[210:]:
            c.update(open=100,high=101,low=99,close=100)
        a=study(Study(symbol='TEST',candles=original))
        b=study(Study(symbol='TEST',candles=changed))
        self.assertEqual(a['development'],b['development'])

    def test_rss_fallback(self):
        search._gdelt_down_until[0]=0
        rss=b'<rss><channel><item><title>TCS results</title><link>https://example.com/a</link><pubDate>Thu, 10 Sep 2026 10:00:00 GMT</pubDate><source url="https://example.com">Example</source></item></channel></rss>'
        feeds=[RuntimeError('bing down'), rss]          # Bing fails, Google answers
        def rss_get(url, params):
            r=feeds.pop(0)
            if isinstance(r, Exception): raise r
            return r
        with patch('app.research.search.gdelt_news',new=AsyncMock(side_effect=ValueError())), patch('app.research.search.rss_get',side_effect=rss_get):
            d=asyncio.run(search.news('TCS',90))
        self.assertEqual(d['provider'],'google_news_rss')
        self.assertEqual(d['providers_tried'],['gdelt: ValueError','bing_news_rss: RuntimeError','google_news_rss'])
        self.assertEqual(d['count'],1)
        self.assertEqual(d['articles'][0]['source'],'Example')
        self.assertEqual(d['articles'][0]['published_at'],'2026-09-10T10:00:00+00:00')

    def test_web_adapter(self):
        response=MagicMock()
        response.json.return_value={'web':{'results':[{'url':'https://example.com','title':'TCS','description':'<b>Results</b>'}]}}
        with patch.dict(os.environ,{'BRAVE_SEARCH_API_KEY':'test-only'}), patch('app.research.search.httpx.AsyncClient') as cls:
            cls.return_value.__aenter__.return_value.get=AsyncMock(return_value=response)
            d=asyncio.run(search.web_search('TCS'))
            self.assertEqual(d['results'][0]['snippet'],'Results')
            kwargs=cls.return_value.__aenter__.return_value.get.call_args.kwargs
            self.assertEqual(kwargs['headers']['X-Subscription-Token'],'test-only')

    def test_search_news_and_failures(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(client.get('/api/research/search?q=TCS').status_code,503)
        with patch('app.research.routes.search.news',new=AsyncMock(return_value={'articles':[]})):
            self.assertEqual(client.get('/api/research/news?q=TCS').status_code,200)
        with patch('app.research.routes.search.web_search',new=AsyncMock(return_value={'results':[]})):
            self.assertEqual(client.get('/api/research/search?q=TCS').status_code,200)
        with patch('app.research.routes.search.news',new=AsyncMock(side_effect=ValueError())):
            self.assertEqual(client.get('/api/research/news?q=TCS').status_code,502)
        response=MagicMock()
        response.json.return_value={'articles':[{'url':'https://example.com/a','title':'<b>TCS</b>','seendate':'20260910T010000Z'},
                                                {'url':'https://example.com/a'},{'url':'javascript:bad'}]}
        with patch('app.research.search.httpx.AsyncClient') as cls:
            cls.return_value.__aenter__.return_value.get=AsyncMock(return_value=response)
            d=asyncio.run(search.gdelt_news('TCS'))
        self.assertEqual(d['count'],1)
        self.assertEqual(d['articles'][0]['title'],'TCS')
        self.assertIsNone(d['articles'][0]['published_at'])

if __name__=='__main__':
    unittest.main()

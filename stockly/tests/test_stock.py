import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.stock import context as cx

client = TestClient(app)


class StockTests(unittest.TestCase):
    """/api/stock/{symbol} from the saved real NSE payload (tests/fixtures/stock_HDFCBANK.json)."""
    def setUp(self):
        cx._cache.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'STOCKLY_OFFLINE': '1'}); self.env.start()
        self.dir = patch.object(cx, 'STOCKS_DIR', Path(self.tmp.name)); self.dir.start()

    def tearDown(self):
        self.env.stop(); self.dir.stop(); self.tmp.cleanup(); cx._cache.clear()

    def test_context(self):
        with patch('app.stock.context.fetch', side_effect=AssertionError('network')):
            d = client.get('/api/stock/hdfcbank.ns').json()['data']
        self.assertEqual((d['symbol'], d['company_name']), ('HDFCBANK', 'HDFC Bank Limited'))
        p = d['price']
        self.assertEqual((p['last'], p['change_pct'], p['lower_circuit'], p['upper_circuit']), (816.5, 1.55, 723.6, 884.4))
        self.assertEqual(p['year_high_date'], '2025-12-01')
        self.assertEqual(d['valuation'], {'pe': 15.49, 'sector_pe': 15.27, 'sector_index': 'NIFTY BANK'})
        self.assertEqual(d['company']['basic_industry'], 'Private Sector Bank')
        names = [i['name'] for i in d['indices']]
        self.assertIn('NIFTY 50', names); self.assertIn('NIFTY BANK', names)
        kinds = [i['kind'] for i in d['indices']]
        self.assertEqual(kinds, sorted(kinds, key=['broad', 'sector', 'theme'].index))   # broad, then sector, then theme
        n50 = next(i for i in d['indices'] if i['name'] == 'NIFTY 50')
        self.assertEqual(n50['stock_minus_index_pct'], round(1.55 - n50['change_pct'], 2))
        self.assertTrue(n50['links']['chart'].startswith('https://www.tradingview.com/'))
        self.assertEqual(d['report'], {'exists': False, 'url': '/stocks/HDFCBANK', 'file': 'stocks/HDFCBANK/report.json', 'updated': None})
        self.assertIn('HDFC%20Bank%20Limited', d['next_calls']['news'])

    def test_errors(self):
        self.assertEqual(client.get('/api/stock/BAD!SYM').status_code, 422)
        self.assertEqual(client.get('/api/stock/TCS').status_code, 404)   # offline has no saved TCS quote
        os.environ.pop('STOCKLY_OFFLINE')
        with patch('app.stock.context.fetch', side_effect=cx.NotFound('x')):
            self.assertEqual(client.get('/api/stock/NOTREAL').status_code, 404)
        with patch('app.stock.context.fetch', side_effect=RuntimeError('down')):
            self.assertEqual(client.get('/api/stock/NOTREAL2').status_code, 502)
        os.environ['STOCKLY_OFFLINE'] = '1'

    def test_report_page_and_json(self):
        page = client.get('/stocks/HDFCBANK')
        self.assertEqual(page.status_code, 200); self.assertIn('data-page="stock"', page.text); self.assertIn('/static/stock.js', page.text)
        self.assertEqual(client.get('/stocks/HDFCBANK/report.json').status_code, 404)
        f = Path(self.tmp.name) / 'HDFCBANK' / 'report.json'; f.parent.mkdir()
        f.write_text(json.dumps({'symbol': 'HDFCBANK', 'headline': 'Test'}))
        self.assertEqual(client.get('/stocks/HDFCBANK/report.json').json()['headline'], 'Test')
        self.assertTrue(client.get('/api/stock/HDFCBANK').json()['data']['report']['exists'])
        f.write_text('{not json')
        self.assertEqual(client.get('/stocks/HDFCBANK/report.json').status_code, 500)
        self.assertIn(client.get('/stocks/..%2Fetc/report.json').status_code, (404, 422))   # never reads outside stocks/
        self.assertEqual(client.get('/stocks/A.B/report.json').status_code, 422)
        self.assertEqual(client.get('/static/stock.js?v=8').status_code, 200)


class FilingsAndNewsTests(unittest.TestCase):
    def test_filings_shape(self):
        from datetime import datetime, timedelta
        fmt = lambda d: d.strftime('%d-%b-%Y')
        now = datetime.now()
        raw = {'announcements': [{'an_dt': fmt(now - timedelta(days=2)) + ' 10:00:00', 'desc': 'Outcome', 'attchmntText': ' Results ', 'attchmntFile': 'https://x/a.pdf'},
                                 {'an_dt': fmt(now - timedelta(days=90)) + ' 10:00:00', 'desc': 'Old', 'attchmntText': 'old'}],
               'actions': [{'exDate': fmt(now + timedelta(days=5)), 'recDate': '-', 'subject': 'Dividend - Rs 5'}],
               'meetings': [{'bm_date': fmt(now - timedelta(days=40)), 'bm_purpose': 'Results', 'bm_desc': 'Q2'}]}
        d = cx.shape_filings('TCS', raw, 30, 10)
        self.assertEqual([a['category'] for a in d['announcements']], ['Outcome'])
        self.assertEqual(d['announcements'][0]['text'], 'Results')
        self.assertEqual(d['corporate_actions'][0]['record_date'], None)
        self.assertEqual([u['subject'] for u in d['upcoming']], ['Dividend - Rs 5'])
        self.assertFalse(d['board_meetings'][0]['upcoming'])

    def test_news_falls_back_to_rss(self):
        import asyncio
        from app.research import search
        rss = (b'<?xml version="1.0"?><rss xmlns:News="https://www.bing.com/news/search?q=x&amp;format=rss"><channel>'
               b'<item><title>TCS wins deal</title><link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url=https%3a%2f%2fexample.com%2fa</link>'
               b'<pubDate>' + datetime_now_rfc() + b'</pubDate><News:Source>Example Times</News:Source></item></channel></rss>')
        search._gdelt_down_until[0] = 0
        async def down(*a, **k): raise RuntimeError('429')
        with patch.object(search, 'gdelt_news', down), patch.object(search, 'rss_get', return_value=rss):
            d = asyncio.run(search.news('Tata Consultancy Services', 7, 5))
        self.assertEqual(d['provider'], 'bing_news_rss')
        self.assertEqual(d['articles'][0]['url'], 'https://example.com/a')
        self.assertEqual(d['articles'][0]['source'], 'Example Times')
        with patch.object(search, 'gdelt_news', down), patch.object(search, 'rss_get', side_effect=RuntimeError('x')):
            self.assertEqual(client.get('/api/research/news?q=Tata%20Consultancy').status_code, 502)


class ProviderHeaderTests(unittest.TestCase):
    def test_no_brotli_without_decoder(self):
        # httpx returns raw bytes for 'br' when no brotli package is installed (Screener came back garbled)
        import importlib.util
        from app.providers import screener, yahoo
        if not (importlib.util.find_spec('brotli') or importlib.util.find_spec('brotlicffi')):
            for h in (screener.HEADERS, yahoo.HEADERS):
                self.assertNotIn('br', h['Accept-Encoding'].replace(' ', '').split(','))


def datetime_now_rfc():
    from email.utils import format_datetime
    from datetime import datetime, timezone
    return format_datetime(datetime.now(timezone.utc)).encode()


if __name__ == '__main__':
    unittest.main()

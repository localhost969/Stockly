import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import os
from fastapi.testclient import TestClient
from app.main import app
from app.home import overview as ov, symbols as sy

client = TestClient(app)


def indices_payload():
    row = lambda name, pct, **kw: {'index': name, 'last': 1000, 'variation': pct * 10, 'percentChange': pct,
                                   'yearHigh': 1100, 'yearLow': 900, 'perChange30d': 1, 'perChange365d': 2,
                                   'oneWeekAgoVal': 980, **kw}
    return {'timestamp': '16-Nov-2026 15:30', 'data': [
        row('NIFTY 50', 0.5, pe='20.6', pb='3.1', dy='1.37', advances='31', declines='19'), row('INDIA VIX', 1.3),
        row('NIFTY 500', 0.1, advances='300', declines='190', unchanged='10'),
        row('NIFTY IT', -1.0), row('NIFTY AUTO', 2.0)]}


def watch_payload():
    stock = lambda s, p, v, hi=20, lo=5, high=11, low=9: {
        'symbol': s, 'lastPrice': 10, 'pChange': p, 'previousClose': 10, 'open': 10, 'dayHigh': high,
        'dayLow': low, 'yearHigh': hi, 'yearLow': lo, 'totalTradedValue': v}
    return {'timestamp': '16-Nov-2026 15:30:00', 'marketStatus': {'marketStatus': 'Open', 'marketStatusMessage': 'open'},
            'data': [{'symbol': 'NIFTY 500'}, stock('A', 5, 100, hi=11), stock('B', -4, 300, lo=9),
                     stock('C', 0, 200), stock('D', 2, 50)]}


class OverviewTests(unittest.TestCase):
    def setUp(self):
        ov._cache.update(at=0.0, ttl=0, data=None); ov._year.update(at=0.0, charts={})

    def test_build(self):
        d = ov.build(indices_payload(), watch_payload())
        self.assertEqual([(i['name'], i['tv']) for i in d['indices']], [('NIFTY 50', 'NIFTY'), ('INDIA VIX', 'INDIAVIX')])
        self.assertEqual(d['indices'][0]['return_7d_pct'], 2.04)
        self.assertEqual((d['indices'][0]['advances'], d['indices'][0]['declines']), (31, 19))
        self.assertEqual({k: d['breadth'][k] for k in ('advances', 'declines', 'unchanged', 'advance_pct')}, {'advances': 2, 'declines': 1, 'unchanged': 1, 'advance_pct': 50.0})
        self.assertEqual([b['count'] for b in d['breadth']['buckets']], [1, 1, 0, 0, 0, 1])  # +5, +2, -4
        self.assertEqual([(s['name'], s['tv']) for s in d['sectors']], [('NIFTY AUTO', 'CNXAUTO'), ('NIFTY IT', 'CNXIT')])
        self.assertEqual([g['symbol'] for g in d['gainers']], ['A', 'D'])
        self.assertEqual([l['symbol'] for l in d['losers']], ['B'])
        self.assertEqual([a['symbol'] for a in d['most_active']], ['B', 'C', 'A', 'D'])
        self.assertEqual((d['year_highs']['count'], d['year_highs']['stocks'][0]['symbol']), (1, 'A'))
        self.assertEqual((d['year_lows']['count'], d['year_lows']['stocks'][0]['symbol']), (1, 'B'))
        self.assertEqual(d['valuation']['pe'], 20.6)
        self.assertEqual({k: d['gainers'][0][k] for k in ('day_high', 'day_low', 'previous_close')}, {'day_high': 11, 'day_low': 9, 'previous_close': 10})

    def test_links_use_a_source_that_has_data(self):
        auto = ov.links('NIFTY AUTO', 'CNXAUTO')
        self.assertEqual(auto['stocks'], {'url': 'https://www.tradingview.com/symbols/NSE-CNXAUTO/components/', 'source': 'TradingView'})
        self.assertIn('symbol=NIFTY%20AUTO', auto['nse'])
        pvt = ov.links('NIFTY PRIVATE BANK', 'NIFTYPVTBANK')   # NSE empty -> TradingView only
        self.assertEqual(pvt['stocks']['source'], 'TradingView'); self.assertNotIn('nse', pvt)
        cement = ov.links('NIFTY CEMENT', 'NIFTY_CEMENT')       # no TV components -> NSE
        self.assertEqual(cement['stocks']['source'], 'NSE'); self.assertIn('NIFTY%20CEMENT', cement['stocks']['url'])
        vix = ov.links('INDIA VIX', 'INDIAVIX')
        self.assertEqual(set(vix), {'chart'})
        for name, tv in {**ov.KEY_INDICES, **ov.SECTORS}.items():
            self.assertIn('chart', ov.links(name, tv))

    def test_cache_ttl_follows_market_status_and_stale_fallback(self):
        with patch('app.home.overview.fetch', return_value=(indices_payload(), watch_payload(), {}, {})) as f:
            self.assertFalse(asyncio.run(ov.overview())['cached'])
            self.assertTrue(asyncio.run(ov.overview())['cached'])
            self.assertEqual(f.call_count, 1)
            self.assertEqual(ov._cache['ttl'], ov.TTL_OPEN)
        ov._cache['ttl'] = 0
        with patch('app.home.overview.fetch', side_effect=RuntimeError()):
            self.assertTrue(asyncio.run(ov.overview())['stale'])

    def test_route_502_without_any_data(self):
        ov._year.update(at=0.0, charts={})
        with patch('app.home.overview.fetch', side_effect=RuntimeError()):
            self.assertEqual(client.get('/api/market/overview').status_code, 502)


    def test_summary_is_factual(self):
        d = ov.build(indices_payload(), watch_payload())
        self.assertEqual(d['summary'][0], 'NIFTY 50 rose 0.50% to 1,000.00.')
        self.assertEqual(d['summary'][1], '2 of 4 NIFTY 500 stocks rose and 1 fell.')
        self.assertEqual(d['summary'][2], '1 of 2 sectors rose. Best: Auto +2.00%; worst: IT −1.00%.')
        self.assertIn('India VIX rose 1.30% to 1000.00', d['summary'][3])
        self.assertEqual(d['summary'][4], '1 NIFTY 500 stock touched a new 52-week high; 1 touched a new 52-week low.')

    def test_day_points_keep_market_minutes_only(self):
        ist = lambda hh, mm: ((20000 * 1440 + hh * 60 + mm) * 60) * 1000   # NSE: IST wall clock as epoch ms
        raw = {'grapthData': [[ist(9, 0), 100, 'PO'], [ist(9, 15), 101, 'NM'], [ist(12, 0), 102, 'NM'],
                              [ist(15, 30), 103, 'NM'], [ist(15, 39), 103, 'NM']]}
        pts = ov.day_points(raw)
        self.assertEqual([p[1] for p in pts], [101, 102, 103])
        self.assertEqual(pts[0][0], ist(9, 15) // 1000 - 19800)   # real unix seconds
        self.assertIsNone(ov.day_points(None))

    def test_buckets_cover_every_mover_once(self):
        changes = [3, 2.99, 1, 0.5, 0, -0.5, -1, -2.99, -3, -7]
        counts = [b['count'] for b in ov.bucket_counts(changes)]
        self.assertEqual(counts, [1, 2, 1, 1, 2, 2])
        self.assertEqual(sum(counts), sum(1 for c in changes if c))

    def test_year_points_replace_today_with_live(self):
        import time
        today_ms = ((int(time.time()) + 19800) // 86400) * 86400 * 1000
        raw = {'grapthData': [[today_ms - 86400000, 10, 'NM'], [today_ms, 11, 'NM']]}
        self.assertEqual([p[1] for p in ov.year_points(raw, last=12)], [10, 12])


class OfflineTests(unittest.TestCase):
    """Full pipeline on the saved real payloads in tests/fixtures; no network."""
    def setUp(self):
        ov._cache.update(at=0.0, ttl=0, data=None); sy._mem.clear()
        self.env = patch.dict(os.environ, {'STOCKLY_OFFLINE': '1'}); self.env.start()

    def tearDown(self):
        self.env.stop(); ov._cache.update(at=0.0, ttl=0, data=None); sy._mem.clear()

    def test_overview_from_fixture(self):
        with patch('app.home.overview.fetch', side_effect=AssertionError('network')):
            d = client.get('/api/market/overview').json()['data']
        self.assertTrue(d['sample'])
        self.assertEqual(len(d['indices']), 5)
        by = {i['name']: i for i in d['indices']}
        self.assertGreater(len(by['NIFTY 50']['day_chart']), 300)
        for name in ('NIFTY BANK', 'NIFTY MIDCAP 100', 'NIFTY SMALLCAP 100', 'INDIA VIX'):
            self.assertGreater(len(by[name]['year_chart']), 200, name)
            self.assertEqual(by[name]['year_chart'][-1][1], by[name]['last'], name)
        self.assertEqual(len(d['sectors']), 15)
        b = d['breadth']
        self.assertEqual(sum(x['count'] for x in b['buckets']), b['advances'] + b['declines'])
        self.assertEqual(len(d['summary']), 5)

    def test_symbols_from_fixture(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sy, 'FILE', Path(tmp) / 's.json'), patch.object(sy, 'DATA_DIR', Path(tmp)):
            d = client.get('/api/market/symbols').json()['data']
        self.assertGreater(d['count'], 2000)


class SymbolTests(unittest.TestCase):
    CSV = 'SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING\n' + ''.join(f'S{i},Company {i},EQ,01-JAN-2000\n' for i in range(150))

    def test_parse_and_disk_cache(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(sy, 'FILE', Path(tmp) / 'symbols.json'), patch.object(sy, 'DATA_DIR', Path(tmp)), \
             patch('app.home.symbols.fetch', return_value=self.CSV) as f:
            sy._mem.clear()
            r = client.get('/api/market/symbols').json()['data']
            self.assertEqual((r['count'], r['symbols'][0]), (150, ['S0', 'Company 0', 'EQ']))
            sy._mem.clear()  # simulate restart: served from disk, no refetch
            client.get('/api/market/symbols')
            self.assertEqual(f.call_count, 1)
        sy._mem.clear()

    def test_incomplete_list_rejected(self):
        with self.assertRaises(ValueError):
            sy.parse('SYMBOL,NAME OF COMPANY\nA,B\n')


class PageTests(unittest.TestCase):
    def test_pages_and_docs(self):
        html = client.get('/', headers={'accept': 'text/html'})
        self.assertIn('Stockly · Market', html.text)
        self.assertEqual(client.get('/').json()['status'], 'ok')
        self.assertEqual(client.get('/docs').status_code, 200)
        for asset, kind in (('/static/app.css?v=8', 'text/css'), ('/static/app.js?v=8', 'javascript')):
            r = client.get(asset)
            self.assertEqual(r.status_code, 200, asset); self.assertIn(kind, r.headers['content-type'])
        self.assertIn('/static/app.js', html.text)
        self.assertTrue(client.get('/api.md').text.startswith('# Stockly API'))
        paths = client.get('/openapi.json').json()['paths']
        self.assertIn('/api/market/overview', paths)
        self.assertNotIn('/api/desk/cards', paths)


if __name__ == '__main__':
    unittest.main()

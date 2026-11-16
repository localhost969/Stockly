import asyncio
import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app
from app.analytics.costs import Trade, calculate
from app.analytics.technical import analyze
from app.analytics import market

client = TestClient(app)


def snapshot():
    return {'source':'nse','index':'NIFTY 50','as_of':'09-Sep-2026 15:30:00', 'is_today':False,
            'count':4,'stocks':[{'symbol':s,'change_pct':p,'volume':v,'traded_value':v*100,
                'gap_pct':p,'day_range_pct':2,'price':100,'year_high':110,'year_low':90}
                for s,p,v in [('A',2,100),('B',-3,400),('C',0,200),('D',None,0)]]}


def history(n=220):
    return {'symbol':'TEST','source':'yahoo','interval':'1d','meta':{'currency':'INR'},
            'candles':[{'date':1700000000+i*86400,'open':100+i,'high':102+i,'low':99+i,'close':101+i,'volume':1000} for i in range(n)]}


class AnalyticsTests(unittest.TestCase):
    def test_catalog_and_rates(self):
        self.assertEqual(client.get('/api/analytics/catalog').status_code,200)
        self.assertEqual(client.get('/api/analytics/charges').json()['data']['statutory']['nse_transaction'],'0.0000307')

    def test_long_charges_reference(self):
        d=client.post('/api/analytics/pnl',json={'entry':1000,'exit':1010,'quantity':100}).json()['data']
        self.assertEqual(d['gross_profit'],1000)
        self.assertEqual(d['charges'],{'brokerage':40,'stt':25,'exchange':6.17,'sebi':.20,'ipft':0,'gst':8.35,'stamp_duty':3,'dp':0,'additional':0})
        self.assertEqual(d['total_charges'],82.72)
        self.assertEqual(d['net_profit'],917.28)

    def test_short_and_delivery(self):
        d=calculate(Trade(entry=1010,exit=1000,quantity=100,side='short'))
        self.assertEqual(d['gross_profit'],1000)
        self.assertEqual(d['charges']['stt'],25)
        d=calculate(Trade(entry=1000,exit=1010,quantity=100,product='delivery'))
        self.assertEqual(d['charges']['stt'],201)
        self.assertEqual(d['charges']['dp'],13)               # Zerodha 15.34 incl. GST = 13 + 2.34
        self.assertEqual(d['total_charges'],238.86)
        self.assertEqual(d['charges']['brokerage'],0)

    def test_brokers(self):
        pnl = lambda **k: client.post('/api/analytics/pnl',json={'entry':1000,'exit':1010,'quantity':100,**k}).json()['data']
        # delivery: Groww/Upstox/Angel One charge Rs 20 per order and Rs 20 + GST DP; Dhan Rs 0 and 12.50 + GST
        for b in ('groww','upstox','angelone'):
            d=pnl(product='delivery',broker=b)
            self.assertEqual((d['charges']['brokerage'],d['charges']['dp'],d['total_charges']),(40,20,294.32),b)
        d=pnl(product='delivery',broker='dhan')
        self.assertEqual((d['charges']['brokerage'],d['charges']['dp'],d['total_charges']),(0,12.5,238.27))
        # minimum Rs 5 per order on Groww / Angel One, never more than the order value
        small=client.post('/api/analytics/pnl',json={'entry':10,'exit':10.1,'quantity':10,'broker':'groww'}).json()['data']
        self.assertEqual(small['charges']['brokerage'],10)
        tiny=client.post('/api/analytics/pnl',json={'entry':1,'exit':1,'quantity':2,'broker':'angelone'}).json()['data']
        self.assertEqual(tiny['charges']['brokerage'],4)
        d=pnl(broker='custom',brokerage_pct=0.01,brokerage_cap=20)  # 0.01% of 1,00,000 = 10 per order
        self.assertEqual(d['charges']['brokerage'],20.1)
        self.assertEqual(d['breakeven_move_per_share'],round(d['total_charges']/100,2))
        self.assertEqual(client.post('/api/analytics/pnl',json={'entry':1,'exit':1,'quantity':1,'broker':'custom'}).status_code,422)
        self.assertEqual(client.post('/api/analytics/pnl',json={'entry':1,'exit':1,'quantity':1,'broker':'xyz'}).status_code,422)

    def test_validation(self):
        for extra in ({'quantity':0},{'quantity':1.2},{'entry':-1},{'entry':'NaN'}, {'side':'short','product':'delivery'},{'exchange':'BSE'}):
            self.assertEqual(client.post('/api/analytics/pnl',json={'entry':100,'exit':110,'quantity':1,**extra}).status_code,422)
        self.assertEqual(client.get('/api/analytics/technicals/TCS?range=1y&interval=1m').status_code,422)
        self.assertEqual(client.get('/api/analytics/movers?limit=101').status_code,422)
        self.assertEqual(client.get('/api/analytics/market?index=INVALID').status_code,422)

    def test_risk(self):
        r={'capital':100000,'entry':1000,'stop':990,'target':1030,'risk_pct':1}
        d=client.post('/api/analytics/position-size',json=r).json()['data']
        self.assertGreater(d['quantity'],0)
        self.assertLessEqual(-d['stop_outcome']['net_profit'],1000)
        self.assertGreater(-calculate(Trade(entry=1000,exit=990,quantity=d['quantity']+1))['net_profit'],1000)
        self.assertEqual(client.post('/api/analytics/position-size',json={**r,'stop':1010}).status_code,422)
        d=client.post('/api/analytics/position-size',json={**r,'capital':1}).json()['data']
        self.assertEqual(d['quantity'],0)

    def test_market_routes(self):
        with patch('app.analytics.market.snapshot',side_effect=lambda _: snapshot()):
            self.assertEqual(client.get('/api/analytics/market').json()['data']['count'],4)
            for kind,first in [('gainers','A'),('losers','B'),('absolute','B'),('volume','B'),('value','B'),('gap_up','A'),('gap_down','B'),('range','A')]:
                d=client.get('/api/analytics/movers',params={'kind':kind}).json()['data']
                self.assertEqual(d['stocks'][0]['symbol'],first)
                self.assertFalse(d['is_today'])
            d=client.get('/api/analytics/breadth').json()['data']
            self.assertEqual([d[k] for k in ('advances','declines','unchanged','unknown')],[1,1,1,1])

    def test_nse_adapter(self):
        payload = {'timestamp':'09-Sep-2026 16:00:00','data':[
            {'symbol':'NIFTY 50'},
            {'symbol':'TCS','lastPrice':'1,100','previousClose':1000,'open':1050,
             'dayHigh':1120,'dayLow':1040,'pChange':10,'totalTradedVolume':'2,000'},
            {'symbol':'INFY','lastPrice':'NaN','pChange':'-'}]}
        with patch('app.analytics.market.fetch',return_value=payload):
            d=asyncio.run(market.snapshot('NIFTY 50'))
        self.assertEqual(d['count'],2)
        self.assertEqual(d['session_date'],'2026-09-09')
        self.assertEqual(d['stocks'][0]['gap_pct'],5)
        self.assertEqual(d['stocks'][0]['day_range_pct'],8)
        self.assertEqual(d['stocks'][0]['volume'],2000)
        self.assertIsNone(d['stocks'][1]['price'])
        with patch('app.analytics.market.requests.Session') as session:
            response=session.return_value.__enter__.return_value.get.return_value
            response.json.return_value={'data':payload}
            self.assertEqual(market.fetch('NIFTY 50'),payload)

    def test_upstream_failures(self):
        with patch('app.analytics.market.snapshot',new=AsyncMock(side_effect=RuntimeError('upstream'))):
            for route in ('market','movers','breadth'):
                self.assertEqual(client.get('/api/analytics/'+route).status_code,502)
        with patch('app.analytics.routes.yahoo.get_history',new=AsyncMock(side_effect=RuntimeError())):
            self.assertEqual(client.get('/api/analytics/technicals/TCS').status_code,502)

    def test_indicators(self):
        d=analyze(history())
        self.assertEqual(d['sma']['20'],310.5)
        self.assertEqual(d['rsi_14_wilder'],100)
        self.assertEqual(d['atr_14_wilder'],3)
        self.assertEqual(d['relative_volume_20_bars'],1)
        self.assertEqual(d['max_close_drawdown_pct'],0)
        self.assertIsNone(d['session_vwap'])
        with patch('app.analytics.routes.yahoo.get_history',new=AsyncMock(return_value=history())):
            self.assertEqual(client.get('/api/analytics/technicals/TCS').status_code,200)
        d=analyze(history(3))
        self.assertIsNone(d['sma']['20'])
        self.assertIsNone(d['rsi_14_wilder'])

    def test_flat_missing_and_intraday(self):
        h=history(30)
        for c in h['candles']:
            c.update(open=100,high=100,low=100,close=100,volume=0)
        h['candles'][0]['close']=None
        d=analyze(h)
        self.assertEqual(d['candles_dropped'],1)
        self.assertEqual(d['rsi_14_wilder'],50)
        self.assertIsNone(d['relative_volume_20_bars'])
        h=history(3)
        h['interval']='5m'
        for i,c in enumerate(h['candles']):
            c['date']=1700000000+i*300
        self.assertAlmostEqual(analyze(h)['session_vwap'],101+2/3)

    def test_legacy_routes(self):
        self.assertEqual(client.get('/health').json(),{'status':'ok'})
        self.assertEqual(client.get('/').json()['status'],'ok')
        with patch('app.main.yahoo.get_live',new=AsyncMock(return_value={'price':100})):
            self.assertEqual(client.get('/api/live/TCS').json(),{'success':True,'data':{'price':100}})
        with patch('app.main.yahoo.get_history',new=AsyncMock(return_value=history())):
            self.assertEqual(client.get('/api/history/TCS').json()['data'],history())
        with patch('app.main.screener.get_screener_markdown',new=AsyncMock(return_value='# TCS')):
            self.assertEqual(client.get('/api/screener/TCS').text,'# TCS')

if __name__=='__main__':
    unittest.main()

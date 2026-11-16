"""Opt-in real provider smoke checks: python -m tests.live_smoke (or run from root below)."""
from fastapi.testclient import TestClient
from app.main import app

if __name__ == '__main__':
    client = TestClient(app)
    paths = ['/api/research/guide', '/api/research/news?q=Reliance%20Industries&limit=5',
             '/api/research/historical/RELIANCE',
             '/api/research/historical/TCS?interval=5m&range=1mo&side=short&rule=below_sma&horizon_bars=3',
             '/api/analytics/catalog', '/api/analytics/charges', '/api/market/overview', '/api/market/symbols', '/api/stock/TCS', '/api/stock/TCS/filings',
             '/api/analytics/market?index=NIFTY%20500',
             '/api/analytics/movers?kind=gainers', '/api/analytics/movers?kind=losers',
             '/api/analytics/breadth', '/api/analytics/technicals/RELIANCE',
             '/api/analytics/technicals/RELIANCE?range=5d&interval=5m']
    failed = []
    for path in paths:
        response = client.get(path)
        print(response.status_code, path, flush=True)
        if response.status_code != 200:
            failed.append((path, response.json()))
    for path, body in [('/api/analytics/pnl', {'entry':1000,'exit':1010,'quantity':100}),
                       ('/api/analytics/position-size', {'capital':100000,'entry':1000,'stop':990,'target':1030})]:
        response = client.post(path, json=body)
        print(response.status_code, path, flush=True)
        if response.status_code != 200:
            failed.append((path, response.json()))
    if failed:
        raise SystemExit(str(failed))

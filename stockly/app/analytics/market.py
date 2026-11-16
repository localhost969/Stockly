"""Independent NSE snapshot adapter; no changes to legacy provider sessions."""
import asyncio
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from curl_cffi import requests

IST = ZoneInfo('Asia/Kolkata')
INDICES = ('NIFTY 50', 'NIFTY NEXT 50', 'NIFTY 100', 'NIFTY 200', 'NIFTY 500',
           'NIFTY BANK', 'NIFTY IT', 'NIFTY AUTO', 'NIFTY PHARMA', 'NIFTY FMCG',
           'NIFTY METAL', 'NIFTY REALTY', 'NIFTY ENERGY', 'NIFTY FINANCIAL SERVICES')


def number(value):
    try:
        value = float(str(value).replace(',', ''))
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def fetch(index):
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.nseindia.com/', 'Accept': 'application/json'}
    with requests.Session(impersonate='chrome') as session:
        session.get('https://www.nseindia.com/', headers=headers, timeout=10).raise_for_status()
        response = session.get('https://www.nseindia.com/api/NextApi/apiClient/marketWatchApi',
                               params={'functionName': 'getIndicesData', 'symbol': index}, headers=headers, timeout=15)
        response.raise_for_status()
        payload = response.json()
        return payload.get('data', {})


async def snapshot(index):
    return parse(await asyncio.to_thread(fetch, index), index)


def parse(payload, index):
    """Turn a raw NSE getIndicesData payload into the normalized snapshot dict."""
    if not isinstance(payload.get('data'), list) or not payload['data']:
        raise ValueError('Empty NSE snapshot')
    rows = []
    mapping = {'price': 'lastPrice', 'change': 'change', 'change_pct': 'pChange',
               'open': 'open', 'high': 'dayHigh', 'low': 'dayLow', 'previous_close': 'previousClose',
               'volume': 'totalTradedVolume', 'traded_value': 'totalTradedValue',
               'year_high': 'yearHigh', 'year_low': 'yearLow',
               'return_30d_pct': 'perChange30d', 'return_365d_pct': 'perChange365d'}
    for row in payload['data']:
        if not row.get('symbol') or row['symbol'] == index:
            continue
        item = {'symbol': row['symbol'], 'as_of': row.get('lastUpdateTime'), 'company_name': row.get('companyName'), **{k: number(row.get(v)) for k,v in mapping.items()}}
        prev, op = item['previous_close'], item['open']
        item['gap_pct'] = round((op/prev-1)*100, 4) if prev and op is not None else None
        item['day_range_pct'] = round((item['high']-item['low'])/prev*100, 4) if prev and item['high'] is not None and item['low'] is not None else None
        rows.append(item)
    if not rows:
        raise ValueError('No constituents in NSE snapshot')
    timestamp = payload.get('timestamp')
    session_date = None
    try:
        session_date = datetime.strptime(timestamp, '%d-%b-%Y %H:%M:%S').date().isoformat()
    except (TypeError, ValueError):
        pass
    now = datetime.now(IST)
    return {'source': 'nse', 'index': index, 'currency': 'INR', 'as_of': timestamp,
            'timezone': 'Asia/Kolkata', 'session_date': session_date,
            'is_today': session_date == now.date().isoformat() if session_date else None,
            'fetched_at': now.isoformat(), 'market_status': payload.get('marketStatus'), 'count': len(rows), 'stocks': rows,
            'warnings': ['Latest available session, not guaranteed real-time. Scope is selected index constituents.',
                         'Traded value uses provider units; do not assume INR without provider confirmation.']}

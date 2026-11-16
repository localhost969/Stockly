"""Everything an agent needs before writing about one NSE stock, in one call.

Two NSE requests per symbol (quote + allIndices, the latter shared and cached), cached 30 s while
the market is open and 10 min otherwise. Offline mode reads tests/fixtures.
"""
import asyncio
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from curl_cffi import requests
from app.analytics.market import number, IST
from app.home import overview as ov

FIXTURES = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures'
STOCKS_DIR = Path(os.environ.get('STOCKLY_STOCKS_DIR') or Path(__file__).resolve().parents[3] / 'stocks')
SYMBOL = re.compile(r'^[A-Z0-9&_-]{1,20}$')
QUOTE_URL = 'https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi'
TV = {**ov.KEY_INDICES, **ov.SECTORS, 'NIFTY 500': 'CNX500', 'NIFTY 100': 'CNX100', 'NIFTY 200': 'CNX200',
      'NIFTY NEXT 50': 'NIFTYJR', 'NIFTY MIDCAP 150': 'NIFTYMIDCAP150', 'NIFTY SMALLCAP 250': 'NIFTYSMLCAP250'}

BROAD = re.compile(r'^NIFTY (50|NEXT 50|100|200|500|MIDCAP (50|100|150|SELECT)|SMALLCAP (50|100|250)|MICROCAP 250|LARGEMIDCAP 250|MIDSMALLCAP 400|TOTAL MARKET|1000)$')
_cache = {}              # symbol -> (expires, data)
_indices = {'at': 0.0, 'data': None}


class NotFound(Exception):
    pass


def clean(symbol):
    s = (symbol or '').strip().upper().removesuffix('.NS')
    if not SYMBOL.match(s):
        raise ValueError('Use an NSE equity symbol such as RELIANCE or M&M.')
    return s


def fetch(symbol, need_indices):
    with requests.Session(impersonate='chrome') as s:
        s.get('https://www.nseindia.com/', headers=ov.NSE_HEADERS, timeout=10).raise_for_status()
        r = s.get(QUOTE_URL, params={'functionName': 'getSymbolData', 'marketType': 'N', 'series': 'EQ', 'symbol': symbol},
                  headers=ov.NSE_HEADERS, timeout=15)
        if r.status_code == 404:
            raise NotFound(f'{symbol} is not an NSE EQ-series stock (check /api/market/symbols).')
        r.raise_for_status()
        q = r.json()
        idx = None
        if need_indices:
            i = s.get('https://www.nseindia.com/api/allIndices', headers=ov.NSE_HEADERS, timeout=15)
            i.raise_for_status()
            idx = i.json()
        return q, idx


async def raw(symbol):
    if ov.offline():
        f = FIXTURES / f'stock_{symbol}.json'
        if not f.exists():
            raise NotFound(f'Offline mode has saved data only for: {", ".join(sorted(p.stem[6:] for p in FIXTURES.glob("stock_*.json")))}')
        q = json.loads(f.read_text())
        return q, json.loads((FIXTURES / 'overview_raw.json').read_text())['indices']
    need = _indices['data'] is None or time.monotonic() - _indices['at'] > 60
    q, idx = await asyncio.to_thread(fetch, symbol, need)
    if idx:
        _indices.update(at=time.monotonic(), data=idx)
    return q, _indices['data']


def index_links(name):
    tv = TV.get(name)
    out = ov.links(name, tv) if tv else {}
    if not out.get('nse') and name not in ov.NSE_EMPTY:
        out['nse'] = f'https://www.nseindia.com/market-data/live-equity-market?symbol={quote(name)}'
    return out


def dmy(s):
    """'01-Dec-2025 00:00:00' -> '2025-12-01'."""
    try:
        return datetime.strptime((s or '').split(' ')[0], '%d-%b-%Y').date().isoformat()
    except ValueError:
        return None


def report_info(symbol):
    f = STOCKS_DIR / symbol / 'report.json'
    return {'exists': f.exists(), 'url': f'/stocks/{symbol}', 'file': f'stocks/{symbol}/report.json',
            'updated': datetime.fromtimestamp(f.stat().st_mtime, IST).isoformat(timespec='seconds') if f.exists() else None}


def build(symbol, q, indices_payload):
    rows = (q or {}).get('equityResponse') or []
    if not rows or not (rows[0].get('metaData') or {}).get('symbol'):
        raise NotFound(f'{symbol} is not an NSE EQ-series stock (check /api/market/symbols).')
    e = rows[0]
    m, t, p, si = e.get('metaData') or {}, e.get('tradeInfo') or {}, e.get('priceInfo') or {}, e.get('secInfo') or {}
    last, chg_pct = number(t.get('lastPrice') or m.get('closePrice')), number(m.get('pChange'))
    band = (p.get('priceBand') or '').split('-')
    by_name = {d.get('index'): d for d in (indices_payload or {}).get('data', [])}
    members = []
    for name in si.get('indexList') or []:
        d = by_name.get(name)
        ic = number(d.get('percentChange')) if d else None
        kind = 'broad' if BROAD.match(name) else 'sector' if name in ov.SECTORS or name == (si.get('pdSectorInd') or '').strip() or name == 'NIFTY BANK' else 'theme'
        members.append({
            'name': name, 'kind': kind, 'last': number(d.get('last')) if d else None, 'change_pct': ic,
            'stock_minus_index_pct': round(chg_pct - ic, 2) if chg_pct is not None and ic is not None else None,
            'return_30d_pct': number(d.get('perChange30d')) if d else None,
            'return_365d_pct': number(d.get('perChange365d')) if d else None,
            'year_high': number(d.get('yearHigh')) if d else None, 'year_low': number(d.get('yearLow')) if d else None,
            'links': index_links(name)})
    order = {'broad': 0, 'sector': 1, 'theme': 2}
    members.sort(key=lambda r: order[r['kind']])
    sector_index = (si.get('pdSectorInd') or '').strip() or None
    return {
        'symbol': m.get('symbol', symbol), 'company_name': m.get('companyName'), 'isin': m.get('isinCode'),
        'series': m.get('series'), 'as_of': e.get('lastUpdateTime'), 'status': si.get('isSuspended'),
        'fetched_at': datetime.now(IST).isoformat(timespec='seconds'),
        'price': {
            'last': last, 'change': number(m.get('change')), 'change_pct': chg_pct,
            'open': number(m.get('open')), 'high': number(m.get('dayHigh')), 'low': number(m.get('dayLow')),
            'previous_close': number(m.get('previousClose')), 'vwap': number(m.get('averagePrice')),
            'year_high': number(p.get('yearHigh')), 'year_high_date': dmy(p.get('yearHightDt')),
            'year_low': number(p.get('yearLow')), 'year_low_date': dmy(p.get('yearLowDt')),
            'pct_below_year_high': round((1 - last / number(p['yearHigh'])) * 100, 2) if last and number(p.get('yearHigh')) else None,
            'pct_above_year_low': round((last / number(p['yearLow']) - 1) * 100, 2) if last and number(p.get('yearLow')) else None,
            'lower_circuit': number(band[0]) if len(band) == 2 else None, 'upper_circuit': number(band[1]) if len(band) == 2 else None,
            'daily_volatility_pct': number(p.get('cmDailyVolatility')), 'annual_volatility_pct': number(p.get('cmAnnualVolatility')),
        },
        'trading': {
            'volume': number(t.get('totalTradedVolume')), 'traded_value': number(t.get('totalTradedValue')),
            'delivery_quantity': number(t.get('deliveryquantity')), 'delivery_pct': number(t.get('deliveryToTradedQuantity')),
            'impact_cost_pct': number(t.get('impactCost')), 'margin_pct': number(t.get('applicableMargin')),
        },
        'company': {
            'macro': si.get('macro'), 'sector': si.get('sector'), 'industry': si.get('industryInfo'),
            'basic_industry': si.get('basicIndustry'), 'listing_date': dmy(si.get('listingDate')),
            'face_value': number(t.get('faceValue')), 'issued_shares': number(t.get('issuedSize')),
            'market_cap': number(t.get('totalMarketCap')), 'free_float_market_cap': number(t.get('ffmc')),
        },
        'valuation': {'pe': number(si.get('pdSymbolPe')), 'sector_pe': number(si.get('pdSectorPe')), 'sector_index': sector_index},
        'main_index': (si.get('index') or None),
        'indices': members,
        'links': {'chart': f'https://www.tradingview.com/chart/?symbol={quote("NSE:" + re.sub(r"[&-]", "_", symbol))}',
                  'fundamentals': f'https://www.screener.in/company/{quote(symbol)}/consolidated/',
                  'nse': f'https://www.nseindia.com/get-quotes/equity?symbol={quote(symbol)}'},
        'report': report_info(symbol),
        'next_calls': {'news': f'/api/research/news?q={quote(m.get("companyName") or symbol)}&days=7',
                       'filings': f'/api/stock/{quote(symbol)}/filings?days=30',
                       'fundamentals': f'/api/screener/{quote(symbol)}',
                       'technicals': f'/api/analytics/technicals/{quote(symbol)}',
                       'history': f'/api/history/{quote(symbol)}?range=1y&interval=1d'},
        **({'sample': True} if ov.offline() else {}),
    }


async def context(symbol, force=False):
    symbol = clean(symbol)
    hit = _cache.get(symbol)
    if hit and hit[0] > time.monotonic() and not force:
        return {**hit[1], 'report': report_info(symbol), 'cached': True}
    q, idx = await raw(symbol)
    data = build(symbol, q, idx)
    is_open = ov._cache['data'] and (ov._cache['data'].get('market_status', {}).get('status') or '').lower() == 'open'
    _cache[symbol] = (time.monotonic() + (ov.TTL_OPEN if is_open else ov.TTL_CLOSED), data)
    return {**data, 'cached': False}


# ---------------------------------------------------------------- official exchange filings
FILINGS_TTL = 600
_filings = {}            # symbol -> (expires, raw)


def fetch_filings(symbol):
    base = 'https://www.nseindia.com/api/'
    with requests.Session(impersonate='chrome') as s:
        s.get('https://www.nseindia.com/', headers=ov.NSE_HEADERS, timeout=10).raise_for_status()
        out = {}
        for key, path in (('announcements', 'corporate-announcements'), ('actions', 'corporates-corporateActions'),
                          ('meetings', 'corporate-board-meetings')):
            r = s.get(base + path, params={'index': 'equities', 'symbol': symbol}, headers=ov.NSE_HEADERS, timeout=20)
            r.raise_for_status()
            out[key] = r.json()
        return out


def parse_dt(s, fmt='%d-%b-%Y %H:%M:%S'):
    try:
        return datetime.strptime((s or '').strip(), fmt)
    except ValueError:
        try:
            return datetime.strptime((s or '').strip().split(' ')[0], '%d-%b-%Y')
        except ValueError:
            return None


def shape_filings(symbol, raw, days, limit):
    now = datetime.now(IST).replace(tzinfo=None)
    since = now.timestamp() - days * 86400
    ann = []
    for a in raw.get('announcements') or []:
        t = parse_dt(a.get('an_dt') or a.get('exchdisstime'))
        if not t or t.timestamp() < since:
            continue
        ann.append({'time': t.isoformat(sep=' '), 'category': a.get('desc'), 'text': (a.get('attchmntText') or '').strip(),
                    'pdf': a.get('attchmntFile') or None})
    ann.sort(key=lambda r: r['time'], reverse=True)
    acts = []
    for a in raw.get('actions') or []:
        ex = parse_dt(a.get('exDate'), '%d-%b-%Y')
        rec = parse_dt(a.get('recDate'), '%d-%b-%Y')
        acts.append({'ex_date': ex.date().isoformat() if ex else None, 'record_date': rec.date().isoformat() if rec else None,
                     'subject': a.get('subject'), 'upcoming': bool(ex and ex.date() >= now.date())})
    acts.sort(key=lambda r: r['ex_date'] or '', reverse=True)
    meets = []
    for m in raw.get('meetings') or []:
        d = parse_dt(m.get('bm_date'), '%d-%b-%Y')
        meets.append({'date': d.date().isoformat() if d else None, 'purpose': m.get('bm_purpose'),
                      'text': (m.get('bm_desc') or '').strip(), 'upcoming': bool(d and d.date() >= now.date())})
    meets.sort(key=lambda r: r['date'] or '', reverse=True)
    return {'symbol': symbol, 'source': 'nse', 'lookback_days': days,
            'fetched_at': datetime.now(IST).isoformat(timespec='seconds'),
            'announcements': ann[:limit], 'announcements_in_window': len(ann),
            'corporate_actions': acts[:10], 'board_meetings': meets[:10],
            'upcoming': [x for x in acts + meets if x['upcoming']],
            'links': {'nse_filings': f'https://www.nseindia.com/get-quotes/equity?symbol={quote(symbol)}#corporate-announcements'},
            'note': 'Official NSE filings. Read the PDF before relying on a summary line.'}


async def filings(symbol, days=30, limit=20):
    symbol = clean(symbol)
    hit = _filings.get(symbol)
    if hit and hit[0] > time.monotonic():
        raw_ = hit[1]
    else:
        if ov.offline():
            raise NotFound('Filings are not available in offline mode.')
        raw_ = await asyncio.to_thread(fetch_filings, symbol)
        _filings[symbol] = (time.monotonic() + FILINGS_TTL, raw_)
    return shape_filings(symbol, raw_, days, limit)

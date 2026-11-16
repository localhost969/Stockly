"""Home-page market overview.

Live: 4 NSE requests per refresh (+4 one-year charts every 6 h), shared by all viewers via a cache.
Offline (STOCKLY_OFFLINE=1 or `python start.py --offline`): the same pipeline runs on raw payloads
saved in tests/fixtures/overview_raw.json — no network. Refresh that file with
`venv/bin/python -m tests.capture_fixtures`.
"""
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from curl_cffi import requests
from app.analytics import market
from app.analytics.market import number, IST

FIXTURE = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures' / 'overview_raw.json'

# NSE name -> TradingView symbol. Verified 2026-11-16.
KEY_INDICES = {'NIFTY 50': 'NIFTY', 'NIFTY BANK': 'BANKNIFTY', 'NIFTY MIDCAP 100': 'CNXMIDCAP',
               'NIFTY SMALLCAP 100': 'CNXSMALLCAP', 'INDIA VIX': 'INDIAVIX'}
# Charts: NIFTY 50 shows the day (1-minute); the other key indices show one year of daily closes.
DAY_CHART = ('NIFTY 50',)
YEAR_CHART = ('NIFTY BANK', 'NIFTY MIDCAP 100', 'NIFTY SMALLCAP 100', 'INDIA VIX')
CHART_ID = {'NIFTY SMALLCAP 100': 'NIFTY SMLCAP 100'}   # NSE's chart API uses an internal name for this one
YEAR_TTL = 6 * 3600
SECTORS = {'NIFTY AUTO': 'CNXAUTO', 'NIFTY FINANCIAL SERVICES': 'CNXFINANCE', 'NIFTY PRIVATE BANK': 'NIFTYPVTBANK',
           'NIFTY PSU BANK': 'CNXPSUBANK', 'NIFTY IT': 'CNXIT', 'NIFTY FMCG': 'CNXFMCG', 'NIFTY PHARMA': 'CNXPHARMA',
           'NIFTY HEALTHCARE INDEX': 'NIFTY_HEALTHCARE', 'NIFTY METAL': 'CNXMETAL', 'NIFTY REALTY': 'CNXREALTY',
           'NIFTY OIL & GAS': 'NIFTY_OIL_AND_GAS', 'NIFTY CONSUMER DURABLES': 'NIFTY_CONSR_DURBL',
           'NIFTY MEDIA': 'CNXMEDIA', 'NIFTY CHEMICALS': 'NIFTY_CHEMICALS', 'NIFTY CEMENT': 'NIFTY_CEMENT'}
UNIVERSE = 'NIFTY 500'
# NSE's live-market API returns no constituents for these names (their own page is empty too)
NSE_EMPTY = {'NIFTY SMALLCAP 100', 'NIFTY FINANCIAL SERVICES', 'NIFTY PRIVATE BANK', 'NIFTY HEALTHCARE INDEX',
             'NIFTY OIL & GAS', 'NIFTY CONSUMER DURABLES', 'INDIA VIX'}
# TradingView has no /components/ page for these (redirects to the chart overview)
TV_NO_COMPONENTS = {'NIFTY CHEMICALS', 'NIFTY CEMENT', 'INDIA VIX'}
TTL_OPEN, TTL_CLOSED = 30, 600
TOP = 5

_cache = {'at': 0.0, 'ttl': 0, 'data': None}
_year = {'at': 0.0, 'charts': {}}
_lock = asyncio.Lock()


def offline():
    return os.environ.get('STOCKLY_OFFLINE', '').lower() in ('1', 'true', 'yes')


# ---------------------------------------------------------------- fetch
NSE_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.nseindia.com/', 'Accept': 'application/json'}


def chart(session, name, flag):
    """Raw NSE index chart: flag '1D' (about 1-minute points) or '1Y' (daily closes). None on failure."""
    try:
        r = session.get('https://www.nseindia.com/api/NextApi/apiClient/indexTrackerApi',
                        params={'functionName': 'getIndexChart', 'index': CHART_ID.get(name, name), 'flag': flag},
                        headers=NSE_HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json().get('data') or {}
        return data if data.get('grapthData') else None
    except Exception:
        return None


def fetch(with_year=True):
    """Raw NSE payloads: allIndices, NIFTY 500 market watch, day charts, (optionally) one-year charts."""
    with requests.Session(impersonate='chrome') as s:
        s.get('https://www.nseindia.com/', headers=NSE_HEADERS, timeout=10).raise_for_status()
        indices = s.get('https://www.nseindia.com/api/allIndices', headers=NSE_HEADERS, timeout=15)
        indices.raise_for_status()
        watch = s.get('https://www.nseindia.com/api/NextApi/apiClient/marketWatchApi',
                      params={'functionName': 'getIndicesData', 'symbol': UNIVERSE}, headers=NSE_HEADERS, timeout=15)
        watch.raise_for_status()
        day = {n: c for n in DAY_CHART if (c := chart(s, n, '1D'))}
        year = {n: c for n in YEAR_CHART if (c := chart(s, n, '1Y'))} if with_year else None
        return indices.json(), watch.json().get('data', {}), day, year


async def fetch_all():
    """(indices, watch, day_charts, year_charts, captured_at). One-year charts are refetched every 6 h."""
    if offline():
        raw = json.loads(FIXTURE.read_text())
        return raw['indices'], raw['watch'], raw.get('day', {}), raw.get('year', {}), raw.get('captured_at')
    need_year = time.monotonic() - _year['at'] > YEAR_TTL or not _year['charts']
    indices, watch, day, year = await asyncio.to_thread(fetch, need_year)
    if year:
        _year.update(at=time.monotonic(), charts=year)
    return indices, watch, day, _year['charts'], None


# ---------------------------------------------------------------- shape
def links(name, tv):
    """Best working destinations for an index: chart, constituents (TradingView first, NSE fallback)."""
    out = {'chart': f'https://www.tradingview.com/chart/?symbol=NSE%3A{tv}'}
    nse = None if name in NSE_EMPTY else f'https://www.nseindia.com/market-data/live-equity-market?symbol={quote(name)}'
    if name not in TV_NO_COMPONENTS:
        out['stocks'] = {'url': f'https://www.tradingview.com/symbols/NSE-{tv}/components/', 'source': 'TradingView'}
        if nse:
            out['nse'] = nse
    elif nse:
        out['stocks'] = {'url': nse, 'source': 'NSE'}
    return out


def pct_from(now, then):
    now, then = number(now), number(then)
    return round((now / then - 1) * 100, 2) if now and then else None


IST_OFFSET = 19800


def nse_time(ms):
    """NSE chart timestamps are IST wall-clock written as if UTC; return real unix seconds."""
    return int(ms // 1000) - IST_OFFSET


def day_points(raw):
    """[[unix_seconds, value], ...] for normal-market minutes 09:15–15:30 IST (pre-open dropped)."""
    if not raw:
        return None
    pts = []
    for row in raw.get('grapthData') or []:
        ms, value, flag = row[0], number(row[1]), row[2] if len(row) > 2 else 'NM'
        minute = (ms // 60000) % 1440            # IST minute of day
        if flag == 'NM' and value is not None and 555 <= minute <= 930:
            pts.append([nse_time(ms), value])
    return pts or None


def year_points(raw, last=None, is_open=False):
    """[[unix_seconds, close], ...] daily closes. While the market is open, today's live value is the last point."""
    if not raw:
        return None
    pts = [[nse_time(r[0]), number(r[1])] for r in raw.get('grapthData') or [] if number(r[1]) is not None]
    if pts and last is not None:
        today = (int(time.time()) + IST_OFFSET) // 86400
        if (pts[-1][0] + IST_OFFSET) // 86400 == today:
            pts[-1][1] = last
        elif is_open and today > (pts[-1][0] + IST_OFFSET) // 86400:
            pts.append([int(time.time()), last])
    return pts or None


def index_row(d, tv, day=None, year=None, is_open=False):
    adv, dec = d.get('advances'), d.get('declines')
    return {'name': d['index'], 'tv': tv, 'links': links(d['index'], tv),
            'last': number(d.get('last')), 'change': number(d.get('variation')),
            'change_pct': number(d.get('percentChange')), 'open': number(d.get('open')),
            'high': number(d.get('high')), 'low': number(d.get('low')),
            'previous_close': number(d.get('previousClose')),
            'year_high': number(d.get('yearHigh')), 'year_low': number(d.get('yearLow')),
            'return_7d_pct': pct_from(d.get('last'), d.get('oneWeekAgoVal')),
            'return_30d_pct': number(d.get('perChange30d')), 'return_365d_pct': number(d.get('perChange365d')),
            'advances': int(number(adv) or 0) if adv not in (None, '') else None,
            'declines': int(number(dec) or 0) if dec not in (None, '') else None,
            'day_chart': day_points(day),
            'year_chart': year_points(year, number(d.get('last')), is_open)}


def stock_row(r):
    row = {k: r[k] for k in ('symbol', 'company_name', 'price', 'change_pct', 'traded_value', 'year_high', 'year_low')}
    row.update(day_high=r.get('high'), day_low=r.get('low'), previous_close=r.get('previous_close'))
    return row


def signed(x):
    return f'{"+" if x > 0 else "−" if x < 0 else ""}{abs(x):.2f}%'


def moved(x):
    """'rose 0.58%' / 'fell 1.20%' / 'was flat'."""
    return f'rose {x:.2f}%' if x > 0 else f'fell {abs(x):.2f}%' if x < 0 else 'was flat'


def summary(d):
    """Plain-English facts computed from the numbers. No opinions, no predictions."""
    lines = []
    n = next((i for i in d['indices'] if i['name'] == 'NIFTY 50'), None)
    if n and n['change_pct'] is not None:
        lines.append(f"NIFTY 50 {moved(n['change_pct'])} to {n['last']:,.2f}." if n['change_pct'] else 'NIFTY 50 was unchanged.')
    b = d['breadth']
    total = b['advances'] + b['declines'] + b['unchanged']
    if total:
        line = f"{b['advances']} of {total} NIFTY 500 stocks rose and {b['declines']} fell"
        if n and n['change_pct'] and n['change_pct'] > 0 and b['advances'] < b['declines']:
            line += ' — NIFTY 50 was up, but most stocks were down'
        elif n and n['change_pct'] and n['change_pct'] < 0 and b['advances'] > b['declines']:
            line += ' — NIFTY 50 was down, but most stocks were up'
        lines.append(line + '.')
    secs = [s for s in d['sectors'] if s['change_pct'] is not None]
    if secs:
        up = sum(s['change_pct'] > 0 for s in secs)
        best, worst = secs[0], secs[-1]
        lines.append(f"{up} of {len(secs)} sectors rose. Best: {short(best['name'])} {signed(best['change_pct'])}; "
                     f"worst: {short(worst['name'])} {signed(worst['change_pct'])}.")
    v = next((i for i in d['indices'] if i['name'] == 'INDIA VIX'), None)
    if v and v['change_pct'] is not None:
        lines.append(f"India VIX {moved(v['change_pct'])} to {v['last']:.2f}" +
                     (' — options are pricing in bigger NIFTY swings.' if v['change_pct'] > 0 else
                      ' — options are pricing in smaller NIFTY swings.' if v['change_pct'] < 0 else '.'))
    hi, lo = d['year_highs']['count'], d['year_lows']['count']
    lines.append(f"{hi} NIFTY 500 stock{'s' if hi != 1 else ''} touched a new 52-week high; {lo} touched a new 52-week low.")
    return lines


def short(name):
    keep = {'IT', 'FMCG', 'PSU', '&'}
    return ' '.join(w if w in keep else w.capitalize() for w in name.removeprefix('NIFTY ').removesuffix(' INDEX').split())


BUCKETS = ('Rose 3% or more', 'Rose 1% to under 3%', 'Rose under 1%',
           'Fell under 1%', 'Fell 1% to under 3%', 'Fell 3% or more')


def bucket_of(p):
    """Index into BUCKETS for a % change; None for exactly unchanged."""
    if p > 0:
        return 0 if p >= 3 else 1 if p >= 1 else 2
    if p < 0:
        return 5 if p <= -3 else 4 if p <= -1 else 3
    return None


def bucket_counts(changes):
    """Stocks per size-of-move group. Every rising/falling stock lands in exactly one group."""
    counts = [0] * len(BUCKETS)
    for p in changes:
        i = bucket_of(p)
        if i is not None:
            counts[i] += 1
    return [{'label': label, 'count': n} for label, n in zip(BUCKETS, counts)]


def build(indices_payload, watch_payload, day=None, year=None):
    day, year = day or {}, year or {}
    by_name = {d.get('index'): d for d in indices_payload.get('data', [])}
    if 'NIFTY 50' not in by_name:
        raise ValueError('NSE allIndices missing NIFTY 50')
    nifty = by_name['NIFTY 50']
    status = watch_payload.get('marketStatus') or {}
    is_open = (status.get('marketStatus') or '').lower() == 'open'
    rows = market.parse(watch_payload, UNIVERSE)['stocks']
    priced = [r for r in rows if r['change_pct'] is not None]
    by_value = sorted((r for r in rows if r['traded_value']), key=lambda r: r['traded_value'], reverse=True)
    highs = [r for r in rows if r['high'] is not None and r['year_high'] and r['high'] >= r['year_high']]
    lows = [r for r in rows if r['low'] is not None and r['year_low'] and r['low'] <= r['year_low']]
    # breadth from the same rows the page draws, so the counts and the dot grid always agree
    adv = sum(r['change_pct'] > 0 for r in priced)
    dec = sum(r['change_pct'] < 0 for r in priced)
    unch = len(priced) - adv - dec
    d = {
        'as_of': indices_payload.get('timestamp'),
        'fetched_at': datetime.now(IST).isoformat(timespec='seconds'),
        'market_status': {'status': status.get('marketStatus'), 'message': status.get('marketStatusMessage')},
        'indices': [index_row(by_name[n], tv, day.get(n), year.get(n), is_open) for n, tv in KEY_INDICES.items() if n in by_name],
        'valuation': {'index': 'NIFTY 50', 'pe': number(nifty.get('pe')), 'pb': number(nifty.get('pb')),
                      'dividend_yield_pct': number(nifty.get('dy'))},
        'universe': UNIVERSE,
        'universe_links': links(UNIVERSE, 'CNX500'),
        'breadth': {'advances': adv, 'declines': dec, 'unchanged': unch,
                    'advance_pct': round(adv / (adv + dec + unch) * 100, 1) if adv + dec + unch else None,
                    'buckets': bucket_counts([r['change_pct'] for r in priced])},
        'sectors': sorted((index_row(by_name[n], tv) for n, tv in SECTORS.items() if n in by_name),
                          key=lambda r: r['change_pct'] if r['change_pct'] is not None else 0, reverse=True),
        'gainers': [stock_row(r) for r in sorted(priced, key=lambda r: r['change_pct'], reverse=True)[:TOP] if r['change_pct'] > 0],
        'losers': [stock_row(r) for r in sorted(priced, key=lambda r: r['change_pct'])[:TOP] if r['change_pct'] < 0],
        'most_active': [stock_row(r) for r in by_value[:TOP]],
        'year_highs': {'count': len(highs), 'stocks': [stock_row(r) for r in sorted(highs, key=lambda r: r['change_pct'] or 0, reverse=True)[:TOP]]},
        'year_lows': {'count': len(lows), 'stocks': [stock_row(r) for r in sorted(lows, key=lambda r: r['change_pct'] or 0)[:TOP]]},
        'source': 'nse',
        'note': 'NSE public data, latest session; may be delayed. Not investment advice.',
    }
    d['summary'] = summary(d)
    return d


async def overview(force: bool = False):
    async with _lock:
        fresh = _cache['data'] and time.monotonic() - _cache['at'] < _cache['ttl']
        if fresh and not force:
            return {**_cache['data'], 'cached': True}
        try:
            indices, watch, day, year, captured = await fetch_all()
            data = build(indices, watch, day, year)
            if captured:
                data.update(sample=True, captured_at=captured)
        except Exception:
            if _cache['data']:  # serve stale rather than nothing
                return {**_cache['data'], 'cached': True, 'stale': True}
            raise
        is_open = (data['market_status']['status'] or '').lower() == 'open'
        _cache.update(at=time.monotonic(), ttl=TTL_OPEN if is_open and not captured else TTL_CLOSED, data=data)
        return {**data, 'cached': False}

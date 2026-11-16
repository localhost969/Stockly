"""Home page: a live market dashboard that needs no agent. Data comes from cached NSE calls."""
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.home import overview as ov, symbols as sy

router = APIRouter(prefix='/api/market', tags=['Market overview'])
STATIC = Path(__file__).parent / 'static'
assets = StaticFiles(directory=STATIC)   # /static/app.css, /static/app.js (cache-busted with ?v=)


def ok(data):
    return {'success': True, 'data': data}


def page():
    return FileResponse(STATIC / 'index.html', media_type='text/html', headers={'Cache-Control': 'no-cache'})


@router.get('/overview', summary='Market overview (home page data)')
async def market_overview(refresh: bool = Query(False, description='Bypass the cache. Avoid in loops.')):
    """Key indices + INDIA VIX, NIFTY 50 valuation, NIFTY 500 breadth, sectors, top gainers/losers,
    most active by traded value and new 52-week highs/lows.

    One cached bundle (30 s while the market is open, 10 min when closed; three NSE requests per
    refresh). If NSE fails after a good fetch, the last copy is returned with `stale: true`."""
    try:
        return ok(await ov.overview(force=refresh))
    except Exception:
        raise HTTPException(502, 'NSE overview unavailable; retry later.')


@router.get('/symbols', summary='All NSE-listed equities for search')
async def all_symbols():
    """`symbols: [[SYMBOL, company name, series], ...]` from NSE's official equity list. Refreshed daily."""
    try:
        d = await sy.symbols()
    except Exception:
        raise HTTPException(502, 'NSE equity list unavailable; retry later.')
    return ok({'count': d['count'], 'symbols': d['symbols']})

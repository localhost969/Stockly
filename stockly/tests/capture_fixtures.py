"""Save real NSE payloads for offline use:  venv/bin/python -m tests.capture_fixtures

Writes tests/fixtures/overview_raw.json, equity_list.csv and stock_HDFCBANK.json. Offline mode
(STOCKLY_OFFLINE=1 / start.py --offline) and the tests replay these instead of calling NSE.
"""
import json
from datetime import datetime
from app.home import overview, symbols
from app.stock import context
from app.analytics.market import IST

if __name__ == '__main__':
    indices, watch, day, year = overview.fetch(with_year=True)
    out = overview.FIXTURE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'captured_at': datetime.now(IST).isoformat(timespec='seconds'),
                               'indices': indices, 'watch': watch, 'day': day, 'year': year}, separators=(',', ':')))
    symbols.FIXTURE.write_text(symbols.fetch())
    quote, _ = context.fetch('HDFCBANK', False)
    (context.FIXTURES / 'stock_HDFCBANK.json').write_text(json.dumps(quote, separators=(',', ':')))
    context.build('HDFCBANK', quote, indices)
    d = overview.build(indices, watch, day, year)  # fail loudly if the payloads no longer parse
    print(f'saved {out} ({out.stat().st_size // 1024} KB); day charts {sorted(day)}; year charts {sorted(year)}')
    for i in d['indices']:
        print(f"  {i['name']:20} day={len(i['day_chart'] or [])} year={len(i['year_chart'] or [])}")

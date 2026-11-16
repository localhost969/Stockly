"""All NSE-listed equities (symbol, name) for search. One CSV download per day, kept on disk."""
import asyncio
import csv
import io
import json
import os
import time
from pathlib import Path
from curl_cffi import requests

URL = 'https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv'
DATA_DIR = Path(os.environ.get('STOCKLY_DATA', Path(__file__).resolve().parents[2] / 'data'))
FILE = DATA_DIR / 'symbols.json'
TTL = 24 * 3600
_lock = asyncio.Lock()
_mem: dict = {}


FIXTURE = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures' / 'equity_list.csv'


def fetch():
    if os.environ.get('STOCKLY_OFFLINE', '').lower() in ('1', 'true', 'yes'):
        return FIXTURE.read_text()
    r = requests.get(URL, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.nseindia.com/'},
                     impersonate='chrome', timeout=20)
    r.raise_for_status()
    return r.text


def parse(text):
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        row = {k.strip(): (v or '').strip() for k, v in row.items() if k}
        if row.get('SYMBOL'):
            rows.append([row['SYMBOL'], row.get('NAME OF COMPANY', ''), row.get('SERIES', '')])
    if len(rows) < 100:
        raise ValueError('NSE equity list looks incomplete')
    return rows


async def symbols():
    async with _lock:
        if _mem and time.time() - _mem['at'] < TTL:
            return _mem
        if FILE.exists():
            try:
                saved = json.loads(FILE.read_text())
                if time.time() - saved['at'] < TTL:
                    _mem.update(saved)
                    return _mem
            except (ValueError, KeyError):
                pass
        try:
            rows = parse(await asyncio.to_thread(fetch))
        except Exception:
            if _mem or FILE.exists():  # stale beats nothing
                return _mem or json.loads(FILE.read_text())
            raise
        data = {'at': time.time(), 'count': len(rows), 'symbols': rows}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        FILE.write_text(json.dumps(data, ensure_ascii=False))
        _mem.clear(); _mem.update(data)
        return _mem

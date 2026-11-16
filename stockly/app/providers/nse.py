import time
from datetime import datetime, timedelta
from curl_cffi import requests as cffi_requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

_session = None
_last_fetch = 0

def get_session():
    global _session, _last_fetch
    now = time.time()
    # refresh every 5 min
    if _session and (now - _last_fetch) < 300:
        return _session
    
    s = cffi_requests.Session(impersonate="chrome")
    # get cookies
    try:
        s.get("https://www.nseindia.com", headers=HEADERS, timeout=10)
        _session = s
        _last_fetch = now
        return s
    except Exception as e:
        raise Exception(f"NSE session init failed: {e}")

def nse_live(symbol: str):
    sym = symbol.strip().upper().split(".")[0]  # remove .NS
    s = get_session()
    url = f"https://www.nseindia.com/api/quote-equity?symbol={sym}"
    r = s.get(url, headers=HEADERS, timeout=10)
    if r.status_code != 200:
        raise Exception(f"NSE live {r.status_code}: {r.text[:200]}")
    j = r.json()
    price = j.get("priceInfo", {})
    return {
        "source": "nse",
        "symbol": sym,
        "price": price.get("lastPrice"),
        "previousClose": price.get("previousClose"),
        "open": price.get("open"),
        "dayHigh": price.get("intraDayHighLow", {}).get("max"),
        "dayLow": price.get("intraDayHighLow", {}).get("min"),
        "close": price.get("close"),
        "change": price.get("change"),
        "pChange": price.get("pChange"),
        "volume": j.get("preOpenMarket", {}).get("totalTradedVolume"),
        "raw": j
    }

RANGE_TO_DAYS = {
    "1d": 1,
    "5d": 5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
    "10y": 3650,
    "ytd": None,
    "max": 3650*3
}

def nse_history(symbol: str, range_: str):
    sym = symbol.strip().upper().split(".")[0]
    s = get_session()
    
    # calc from/to
    days = RANGE_TO_DAYS.get(range_, 30)
    to_dt = datetime.now()
    if range_ == "ytd":
        from_dt = datetime(to_dt.year, 1, 1)
    else:
        from_dt = to_dt - timedelta(days=days)
    
    frm = from_dt.strftime("%d-%m-%Y")
    to = to_dt.strftime("%d-%m-%Y")
    
    url = f"https://www.nseindia.com/api/historical/cm/equities?symbol={sym}&series=[\"EQ\"]&from={frm}&to={to}"
    r = s.get(url, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        raise Exception(f"NSE history {r.status_code}: {r.text[:300]}")
    j = r.json()
    data = j.get("data", [])
    
    # NSE data is already daily OHLC
    candles = []
    for d in data:
        # date format: 26-Aug-2026
        try:
            ts = int(datetime.strptime(d["CH_TIMESTAMP"], "%Y-%m-%dT%H:%M:%SZ").timestamp()) if "CH_TIMESTAMP" in d else None
        except:
            ts = None
        candles.append({
            "date": ts,
            "datetime": d.get("CH_TIMESTAMP") or d.get("mTIMESTAMP"),
            "open": d.get("CH_OPENING_PRICE"),
            "high": d.get("CH_TRADE_HIGH_PRICE"),
            "low": d.get("CH_TRADE_LOW_PRICE"),
            "close": d.get("CH_CLOSING_PRICE"),
            "volume": d.get("CH_TOT_TRADED_QTY"),
            "value": d.get("CH_TOT_TRADED_VAL"),
        })
    
    # NSE only gives 1d interval, ignore interval param
    return {
        "source": "nse",
        "symbol": sym,
        "range": range_,
        "interval": "1d",
        "candles": candles,
        "meta": {
            "from": frm,
            "to": to
        }
    }

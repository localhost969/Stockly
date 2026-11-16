"""Start Stockly:  python start.py   [--port 8000] [--no-browser]

Uses stockly/venv automatically when present. Safe to run twice: if the server is already
up it just prints the addresses and exits.
"""
import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT / 'stockly'
VENV_PY = ENGINE / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def in_use(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(('127.0.0.1', port)) == 0


def main():
    p = argparse.ArgumentParser(description='Run the Stockly server.')
    p.add_argument('--port', type=int, default=int(os.environ.get('STOCKLY_PORT', 8000)))
    p.add_argument('--host', default=os.environ.get('STOCKLY_HOST', '127.0.0.1'))
    p.add_argument('--no-browser', action='store_true', help='Do not open the dashboard.')
    p.add_argument('--offline', action='store_true',
                   help='Serve the home page from saved sample data (stockly/tests/fixtures); no NSE/Yahoo calls.')
    args = p.parse_args()
    if args.offline:
        os.environ['STOCKLY_OFFLINE'] = '1'

    # Re-launch inside the bundled virtualenv so `python start.py` always works.
    if VENV_PY.exists() and Path(sys.prefix).resolve() != (ENGINE / 'venv').resolve():
        sys.exit(subprocess.call([str(VENV_PY), __file__, *sys.argv[1:]]))

    base = f'http://localhost:{args.port}'
    urls = f'  Market  {base}/\n  Stock   {base}/stocks/<SYMBOL>\n  Docs    {base}/docs\n  API     {base}/api.md (markdown)'
    if in_use(args.port):
        print(f'Stockly is already running.\n{urls}')
        return

    try:
        import uvicorn  # noqa: F401
    except ImportError:
        sys.exit(f'Missing dependencies. Run:\n  python -m venv stockly/venv && '
                 f'stockly/venv/bin/pip install -r stockly/requirements.txt')

    (ROOT / 'stocks').mkdir(exist_ok=True)
    os.chdir(ENGINE)
    sys.path.insert(0, str(ENGINE))
    mode = '  (offline: sample data)' if os.environ.get('STOCKLY_OFFLINE') else ''
    print(f'Stockly starting{mode}\n{urls}\n  Ctrl+C to stop', flush=True)

    if not args.no_browser and sys.stdout.isatty() and not os.environ.get('CI'):
        def open_later():
            for _ in range(50):
                if in_use(args.port):
                    webbrowser.open(base)
                    return
                time.sleep(0.2)
        threading.Thread(target=open_later, daemon=True).start()

    import uvicorn
    uvicorn.run('app.main:app', host=args.host, port=args.port, log_level='warning')


if __name__ == '__main__':
    main()

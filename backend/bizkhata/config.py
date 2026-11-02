"""Settings come from environment variables or from the .env file in the project folder."""
import os
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_env():
    f = ROOT / '.env'
    if not f.exists():
        return
    for line in f.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


_load_env()
os.environ.setdefault('TZ', 'Asia/Karachi')          # dates (trial end, due dates) follow Pakistan time
try:
    time.tzset()
except AttributeError:                                # Windows has no tzset
    pass


def get(key, default=None):
    v = os.environ.get(key)
    return default if v is None or v == '' else v


def data_dir():
    p = pathlib.Path(get('DATA_DIR', str(ROOT / 'data'))).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

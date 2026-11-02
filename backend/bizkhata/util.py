import math
import re
import sys
import time
import uuid
from datetime import date, datetime, timedelta


class HttpError(Exception):
    def __init__(self, status, code, message=None, extra=None):
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code
        self.extra = extra or {}


def bad(code, message=None, **extra):
    return HttpError(400, code, message, extra)


def now_ms():
    return int(time.time() * 1000)


def ymd(d):
    return d.strftime('%Y-%m-%d')


def today():
    return ymd(date.today())


def _d(s):
    return datetime.strptime(s, '%Y-%m-%d').date()


def add_days(s, n):
    return ymd(_d(s) + timedelta(days=n))


def add_months(s, n):
    d = _d(s)
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return ymd(date(y, m, min(d.day, last)))


def days_between(a, b):
    return (_d(a) - _d(b)).days


def is_date(s):
    s = str(s)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        return False
    try:
        return ymd(_d(s)) == s
    except ValueError:
        return False


def check_date(s):
    """a date typed by the user: must be real and not in the future"""
    s = str(s or '').strip()
    if not is_date(s):
        raise bad('BAD_DATE', 'Choose a valid date')
    if s > today():
        raise bad('FUTURE_DATE', 'Date cannot be in the future')
    return s


MOBILE_RE = re.compile(r'^03\d{9}$')


def norm_mobile(s):
    d = re.sub(r'\D', '', '' if s is None else str(s))
    if d.startswith('0092'):
        d = '0' + d[4:]
    elif d.startswith('92') and len(d) >= 12:
        d = '0' + d[2:]
    return d


def r2(n):
    try:
        x = float(n)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(x):
        return 0.0
    return math.floor((x + sys.float_info.epsilon) * 100 + 0.5) / 100


def num(n, default=0.0):
    try:
        x = float(n)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def s(v, mx=200):
    return ('' if v is None else str(v)).strip()[:mx]


def uid():
    return str(uuid.uuid4())


def is_unique_error(e):
    code = getattr(e, 'pgcode', None)
    return code == '23505' or 'UNIQUE constraint failed' in str(e)

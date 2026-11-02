import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

from . import config

# ---- password hashing: scrypt (same format as the Node.js version, so old users keep working) ----

# New passwords: min 8 chars, upper, lower, digit, special
_PASS_SPECIAL = re.compile(r'''[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>/?`~]''')


def password_ok(pw):
    """Returns (True, None) or (False, error_code). Used when setting a new password."""
    pw = '' if pw is None else str(pw)
    if len(pw) < 8:
        return False, 'SHORT_PASS'
    if not re.search(r'[A-Z]', pw):
        return False, 'PASS_UPPER'
    if not re.search(r'[a-z]', pw):
        return False, 'PASS_LOWER'
    if not re.search(r'\d', pw):
        return False, 'PASS_DIGIT'
    if not _PASS_SPECIAL.search(pw):
        return False, 'PASS_SPECIAL'
    return True, None


PASS_MSGS = {
    'SHORT_PASS': 'Password needs at least 8 characters',
    'PASS_UPPER': 'Password needs at least one capital letter (A-Z)',
    'PASS_LOWER': 'Password needs at least one small letter (a-z)',
    'PASS_DIGIT': 'Password needs at least one number (0-9)',
    'PASS_SPECIAL': 'Password needs at least one special character (!@#$…)',
    'PASS_MATCH': 'Password and confirm password do not match',
}


def require_strong_password(pw):
    from .util import bad
    ok, code = password_ok(pw)
    if not ok:
        raise bad(code, PASS_MSGS.get(code, 'Password is not strong enough'))


def hash_password(pw):
    salt = os.urandom(16)
    h = hashlib.scrypt(str(pw).encode(), salt=salt, n=16384, r=8, p=1, dklen=64, maxmem=64 * 1024 * 1024)
    return 's1$' + salt.hex() + '$' + h.hex()


def verify_password(pw, stored):
    try:
        v, salt_hex, hash_hex = str(stored).split('$')
        if v != 's1':
            return False
        h = hashlib.scrypt(str(pw).encode(), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1, dklen=64, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(h, bytes.fromhex(hash_hex))
    except Exception:
        return False


# ---- signed login tokens (HMAC-SHA256) ----
_SECRET = None


def secret():
    global _SECRET
    if _SECRET:
        return _SECRET
    if config.get('SECRET'):
        _SECRET = config.get('SECRET')
        return _SECRET
    f = config.data_dir() / 'secret.key'
    if f.exists():
        _SECRET = f.read_text().strip()
    else:
        _SECRET = secrets.token_hex(48)
        f.write_text(_SECRET)
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
    return _SECRET


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def sign_token(payload, days=30):
    body = _b64(json.dumps({**payload, 'exp': int(time.time() * 1000) + days * 86400000}, separators=(',', ':')).encode())
    sig = _b64(hmac.new(secret().encode(), body.encode(), hashlib.sha256).digest())
    return body + '.' + sig


def read_token(tok):
    try:
        body, sig = str(tok).split('.')
        want = _b64(hmac.new(secret().encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            return None
        p = json.loads(_unb64(body))
        return p if p.get('exp', 0) > time.time() * 1000 else None
    except Exception:
        return None


# ---- login brute-force limiter (in memory, per worker) ----
_fails = {}
_lock = threading.Lock()
LIMIT, WINDOW = 8, 15 * 60


def check_limit(key):
    with _lock:
        f = _fails.get(key)
        return not (f and f[0] >= LIMIT and f[1] > time.time())


def record_fail(key):
    with _lock:
        f = _fails.get(key)
        if not f or f[1] < time.time():
            _fails[key] = [1, time.time() + WINDOW]
        else:
            f[0] += 1
        if len(_fails) > 5000:
            for k in [k for k, v in _fails.items() if v[1] < time.time()]:
                _fails.pop(k, None)


def clear_fails(key):
    with _lock:
        _fails.pop(key, None)

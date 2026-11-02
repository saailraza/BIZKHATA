"""Register, login, forgot password."""
from . import config, db, logic, security as sec
from .framework import api
from .util import HttpError, MOBILE_RE, add_days, bad, is_unique_error, norm_mobile, now_ms, s, uid, ymd
from datetime import datetime


TEST_MOBILE = '03000000000'          # the fixed test account (login name: biztest / password: Test@1234)
TEST_PASSWORD = 'Test@1234'


def test_user_on():
    return config.get('TEST_USER', '0') == '1'


def db_name_for(shop_id):
    return 'bk_' + shop_id.replace('-', '')


def mobile_taken(c, mobile, except_user_id=None):
    for u in c.query('SELECT id FROM users WHERE mobile = $1', [mobile]):
        if u['id'] != except_user_id:
            return True
    return bool(c.query('SELECT 1 FROM admins WHERE lower(login_id) = $1', [mobile]))


def create_shop(name, mobile, shop, password, status='trial', actor=None):
    """Creates a shop + its only user + its own separate database.
    Used by self-registration (status 'trial' = auto approved) and by the admin 'Add company'."""
    name, shop, mobile = s(name, 80), s(shop, 100), norm_mobile(mobile)
    password = '' if password is None else str(password)
    if not name or not shop or not password:
        raise bad('FIELDS', 'Please fill every field')
    if not MOBILE_RE.match(mobile):
        raise bad('BAD_MOBILE', 'Mobile number must be 11 digits and start with 03')
    sec.require_strong_password(password)
    if mobile_taken(db.master, mobile):
        raise bad('MOBILE_TAKEN', 'This mobile number is already registered')

    st = logic.get_settings()
    sid, uid_, now = uid(), uid(), now_ms()
    dbname = db_name_for(sid)
    trial_end = now + int(st['trial_days']) * 86400000
    try:
        with db.master.tx() as c:
            c.execute("""INSERT INTO shops (id, name, owner_name, status, registered_at, trial_ends_at, auto_suspended, monthly_fee, next_due_date, db_name)
                         VALUES ($1,$2,$3,$4,$5,$6,0,0,NULL,$7)""", [sid, shop, name, status, now, trial_end, dbname])
            c.execute('INSERT INTO users (id, shop_id, name, mobile, password_hash, active, created_at) VALUES ($1,$2,$3,$4,$5,1,$6)',
                      [uid_, sid, name, mobile, sec.hash_password(password), now])
            # first bill (default PKR 999) falls due on the day the free trial ends
            if status == 'trial' and float(st['monthly_fee']) > 0:
                logic.create_bill(c, sid, float(st['monthly_fee']), ymd(datetime.fromtimestamp(trial_end / 1000)),
                                  note='Monthly subscription (first month)', monthly=True, auto=True)
    except Exception as e:
        if is_unique_error(e):
            raise bad('MOBILE_TAKEN', 'This mobile number is already registered')
        raise
    try:
        db.create_shop_db(dbname)                      # the shop's own separate database
    except Exception:
        db.master.execute('DELETE FROM shops WHERE id = $1', [sid])
        raise
    logic.log_act(db.master, sid, actor or mobile, 'Registered',
                  ('Auto approved, %s day trial' % st['trial_days']) if status == 'trial' else 'Created by admin: ' + status)
    return {'shop_id': sid, 'user_id': uid_}


@api('/api/health')
def health(ctx):
    n = db.master.query('SELECT COUNT(*) AS c FROM admins')[0]['c']
    return {'ok': True, 'database': db.ENGINE, 'isolation': db.ISOLATION if db.ENGINE == 'postgres' else 'file', 'admins': int(n)}


@api('/api/public-config')
def public_config(ctx):
    """read by the website / Android app before login"""
    return {'playStore': config.get('PLAY_STORE_URL', ''), 'allowPay': config.get('APP_ALLOW_PAYMENT', '1') != '0'}


@api('/api/register', ['POST'])
def register(ctx):
    b = ctx.body
    r = create_shop(b.get('name'), b.get('mobile'), b.get('shop'), b.get('password'))
    return {'token': sec.sign_token({'r': 'shop', 'u': r['user_id']}), 'role': 'shop'}


@api('/api/login', ['POST'])
def login(ctx):
    raw, pw = s(ctx.body.get('id'), 120).lower(), str(ctx.body.get('password') or '')
    if not raw or not pw:
        raise bad('FIELDS', 'Enter your mobile number and password')
    if test_user_on() and raw == config.get('TEST_USER_LOGIN', 'biztest').lower():
        raw = TEST_MOBILE                # test account: "biztest" works like its mobile number
    import re
    is_phone = bool(re.fullmatch(r'[\d+\s-]+', raw))
    key = ctx.ip + '|' + raw
    if not sec.check_limit(key):
        raise HttpError(429, 'TOO_MANY', 'Too many wrong attempts. Try again in 15 minutes.')
    if not is_phone:
        lid = 'admin@bizease.com' if raw == 'admin' else raw
        a = db.master.query('SELECT * FROM admins WHERE lower(login_id) = $1', [lid])
        if a and sec.verify_password(pw, a[0]['password_hash']):
            sec.clear_fails(key)
            return {'token': sec.sign_token({'r': 'admin', 'u': a[0]['id']}, 7), 'role': 'admin'}
    else:
        u = db.master.query('SELECT * FROM users WHERE mobile = $1', [norm_mobile(raw)])
        if u and sec.verify_password(pw, u[0]['password_hash']):
            if not u[0]['active']:
                raise HttpError(403, 'INACTIVE', 'This ID is switched off')
            sec.clear_fails(key)
            logic.log_act(db.master, u[0]['shop_id'], u[0]['mobile'], 'Login')
            return {'token': sec.sign_token({'r': 'shop', 'u': u[0]['id']}), 'role': 'shop'}
    sec.record_fail(key)
    raise HttpError(401, 'BAD_LOGIN', 'Mobile number or password is not correct')


@api('/api/forgot', ['POST'])
def forgot(ctx):
    mobile, pw = norm_mobile(ctx.body.get('mobile')), str(ctx.body.get('password') or '')
    if not MOBILE_RE.match(mobile):
        raise bad('BAD_MOBILE', 'Mobile number must be 11 digits and start with 03')
    sec.require_strong_password(pw)
    u = db.master.query('SELECT * FROM users WHERE mobile = $1', [mobile])
    if not u:
        raise bad('NOT_REGISTERED', 'This mobile number is not registered')
    u = u[0]
    db.master.execute("UPDATE password_reset_requests SET status = 'rejected', resolved_at = $1 WHERE user_id = $2 AND status = 'pending'", [now_ms(), u['id']])
    db.master.execute("INSERT INTO password_reset_requests (id, user_id, shop_id, new_password_hash, status, created_at) VALUES ($1,$2,$3,$4,'pending',$5)",
                      [uid(), u['id'], u['shop_id'], sec.hash_password(pw), now_ms()])
    logic.log_act(db.master, u['shop_id'], mobile, 'Password reset requested')
    return {'ok': True}

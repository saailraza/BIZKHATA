"""Tiny helper layer on top of Flask: route decorator, login check, request context."""
from flask import jsonify, request

from . import config, db, logic, security
from .util import HttpError, now_ms

ROUTES = []


class Ctx:
    """what every route function receives"""
    pass


def api(rule, methods=('GET',), auth=None, blocked_ok=False):
    def deco(fn):
        ROUTES.append((rule, tuple(methods), auth, blocked_ok, fn))
        return fn
    return deco


def client_ip():
    if config.get('TRUST_PROXY', '0') == '1':
        fwd = request.headers.get('X-Forwarded-For', '')
        if fwd:
            return fwd.split(',')[0].strip()
    return request.remote_addr or ''


def authenticate(ctx, role, blocked_ok):
    h = request.headers.get('Authorization', '')
    tok = security.read_token(h[7:]) if h.startswith('Bearer ') else None
    if not tok or tok.get('r') != role:
        raise HttpError(401, 'AUTH', 'Please log in')
    m = db.master
    if role == 'admin':
        a = m.query('SELECT id, name, login_id FROM admins WHERE id = $1', [tok['u']])
        if not a:
            raise HttpError(401, 'AUTH', 'Please log in')
        ctx.admin = a[0]
        return
    u = m.query('SELECT * FROM users WHERE id = $1', [tok['u']])
    if not u or not u[0]['active']:
        raise HttpError(401, 'AUTH', 'Please log in')
    user = u[0]
    m.execute("UPDATE shops SET status = 'suspended', auto_suspended = 1 WHERE id = $1 AND status = 'trial' AND trial_ends_at < $2", [user['shop_id'], now_ms()])
    shop = m.query('SELECT * FROM shops WHERE id = $1', [user['shop_id']])[0]
    st = logic.get_settings()
    due = m.query("SELECT due_date FROM bills WHERE shop_id = $1 AND status = 'due'", [shop['id']])
    ctx.user, ctx.shop = user, shop
    ctx.blocked = logic.block_reason(shop, due, st)
    if ctx.blocked and not blocked_ok:
        raise HttpError(403, 'BLOCKED', 'Your account is blocked: ' + ctx.blocked)


def _wrap(fn, auth, blocked_ok):
    def view(**params):
        ctx = Ctx()
        ctx.params, ctx.query, ctx.ip = params, request.args.to_dict(), client_ip()
        body = request.get_json(silent=True, force=True) if request.method in ('POST', 'PUT') else None
        ctx.body = body if isinstance(body, dict) else {}
        if auth:
            authenticate(ctx, auth, blocked_ok)
        out = fn(ctx)
        return jsonify({'ok': True} if out is None else out)
    return view


def register(app):
    for i, (rule, methods, auth, blocked_ok, fn) in enumerate(ROUTES):
        app.add_url_rule(rule, endpoint='%s.%s.%d' % (fn.__module__, fn.__name__, i), view_func=_wrap(fn, auth, blocked_ok), methods=list(methods))


def sdb(ctx):
    """the shop's own separate database"""
    return db.shop_db(ctx.shop['db_name'])

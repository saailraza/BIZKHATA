"""Flask application: API + the web app files (public/)."""
import logging
import threading
import time

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from . import config, db, logic, security
from .framework import register
from .util import HttpError, is_unique_error, now_ms, uid
from . import routes_public, routes_shop, routes_admin   # noqa: F401  (importing registers the routes)

log = logging.getLogger('bizkhata')
PUBLIC = config.ROOT / 'public'
_tick_lock = threading.Lock()
_last_tick = 0.0


def ensure_first_admin():
    """creates the first admin once (login + password from .env)"""
    if int(db.master.query('SELECT COUNT(*) AS c FROM admins')[0]['c']) > 0:
        return
    login = config.get('ADMIN_LOGIN', 'admin@bizease.com').lower()
    pw = config.get('ADMIN_PASSWORD', '123456')
    try:
        db.master.execute('INSERT INTO admins (id, name, login_id, password_hash, created_at) VALUES ($1,$2,$3,$4,$5)',
                          [uid(), 'BIZEASE Admin', login, security.hash_password(pw), now_ms()])
        log.warning('First admin created: %s  (change the password after login)', login)
    except Exception as e:               # another worker did it at the same moment
        if not is_unique_error(e):
            raise


def ensure_test_user():
    """TEST_USER=1 in .env: a fixed test shop, login  biztest / 123456  (always active, never expires).
    Turn it OFF (TEST_USER=0) before real users arrive, and delete 'Test Shop' from the admin panel."""
    if not routes_public.test_user_on():
        return
    mob = routes_public.TEST_MOBILE
    rows = db.master.query('SELECT * FROM users WHERE mobile = $1', [mob])
    if not rows:
        routes_public.create_shop('Biz Test', mob, 'Test Shop', routes_public.TEST_PASSWORD, 'full', 'system')
        log.warning('Test user created: login biztest / password %s', routes_public.TEST_PASSWORD)
        return
    db.master.execute('UPDATE users SET password_hash = $1, active = 1 WHERE id = $2',
                      [security.hash_password(routes_public.TEST_PASSWORD), rows[0]['id']])
    db.master.execute("UPDATE shops SET status = 'full', auto_suspended = 0, next_due_date = NULL WHERE id = $1", [rows[0]['shop_id']])


def tick(force=False):
    """block shops whose free trial ended + create the monthly bills (runs at most once a minute per worker)"""
    global _last_tick
    if not force and time.time() - _last_tick < 60:
        return
    if not _tick_lock.acquire(blocking=False):
        return
    try:
        _last_tick = time.time()
        logic.refresh_statuses()
        logic.generate_bills()
    except Exception:
        log.exception('scheduled work failed')
    finally:
        _tick_lock.release()


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    db.init_master()
    ensure_first_admin()
    ensure_test_user()
    register(app)

    def _cors_allowed_origin():
        origin = request.headers.get('Origin', '')
        allowed = [x.strip() for x in config.get('CORS_ORIGINS', '').split(',') if x.strip()]
        if origin and (origin in allowed or '*' in allowed):
            return origin
        return None

    @app.before_request
    def _before():
        if request.path.startswith('/api/'):
            if request.method == 'OPTIONS' and _cors_allowed_origin():
                return ('', 204)
            tick()

    @app.after_request
    def _after(resp):
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        resp.headers.setdefault('Referrer-Policy', 'same-origin')
        if request.path.startswith('/api/'):
            resp.headers['Cache-Control'] = 'no-store'
            # CORS: allow a separate frontend origin (see CORS_ORIGINS in .env).
            # Same-origin (Flask serving public/) does not need this.
            origin = _cors_allowed_origin()
            if origin:
                resp.headers['Access-Control-Allow-Origin'] = origin
                resp.headers['Access-Control-Allow-Credentials'] = 'true'
                resp.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
                resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
                resp.headers['Vary'] = 'Origin'
        return resp

    @app.errorhandler(HttpError)
    def _http_error(e):
        return jsonify({'error': e.message, 'code': e.code, **e.extra}), e.status

    @app.errorhandler(HTTPException)
    def _http_exc(e):
        if request.path.startswith('/api/'):
            code = {404: 'NOT_FOUND', 405: 'METHOD', 413: 'TOO_BIG'}.get(e.code, 'ERROR')
            return jsonify({'error': e.name, 'code': code}), e.code
        return e

    @app.errorhandler(Exception)
    def _crash(e):
        log.exception('unhandled error on %s %s', request.method, request.path)
        return jsonify({'error': 'Server error', 'code': 'SERVER'}), 500

    @app.route('/.well-known/assetlinks.json')
    def assetlinks():
        """lets the Android app open this website without the browser bar (Trusted Web Activity)"""
        fps = [x.strip() for x in config.get('ANDROID_SHA256', '').split(',') if x.strip()]
        return jsonify([{'relation': ['delegate_permission/common.handle_all_urls'],
                         'target': {'namespace': 'android_app', 'package_name': config.get('ANDROID_PACKAGE', 'com.bizease.bizkhata'), 'sha256_cert_fingerprints': fps}}])

    @app.route('/', defaults={'p': ''})
    @app.route('/<path:p>')
    def web(p):
        if p.startswith('api/'):
            return jsonify({'error': 'Not found', 'code': 'NOT_FOUND'}), 404
        if p in ('privacy', 'delete-account'):
            p += '.html'
        f = (PUBLIC / p).resolve()
        if p and f.is_file() and PUBLIC.resolve() in f.parents:
            fresh = p in ('sw.js', 'manifest.webmanifest') or p.endswith('.html')
            resp = send_from_directory(PUBLIC, p, max_age=0 if fresh else 86400,
                                       mimetype='application/manifest+json' if p == 'manifest.webmanifest' else None)
            if fresh:
                resp.headers['Cache-Control'] = 'no-cache'
            return resp
        resp = send_from_directory(PUBLIC, 'index.html')
        resp.headers['Cache-Control'] = 'no-cache'
        return resp

    return app

"""python tests/app_test.py  -> Android app / PWA support: config, assetlinks, manifest, delete account"""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DB_ENGINE='sqlite', DATA_DIR=tmp, SECRET='t', ANDROID_SHA256='AA:BB:CC', ANDROID_PACKAGE='com.bizease.bizkhata', PLAY_STORE_URL='https://play.google.com/store/apps/details?id=com.bizease.bizkhata', APP_ALLOW_PAYMENT='0')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bizkhata.app import create_app
c = create_app().test_client(); ok = True
def check(n, cond):
    global ok; ok = ok and cond; print(('PASS ' if cond else 'FAIL ') + n)
def call(m, p, b=None, t=None):
    r = c.open(p, method=m, json=b, headers={'Authorization': 'Bearer ' + t} if t else {}); return r.status_code, r.get_json()
r = c.get('/.well-known/assetlinks.json'); j = r.get_json()
check('assetlinks.json', r.status_code == 200 and j[0]['target']['package_name'] == 'com.bizease.bizkhata' and j[0]['target']['sha256_cert_fingerprints'] == ['AA:BB:CC'])
r = c.get('/manifest.webmanifest'); check('manifest content-type', 'manifest+json' in r.content_type and r.get_json()['start_url'] == '/?app=1')
r = c.get('/sw.js'); check('service worker served, not cached', r.status_code == 200 and r.headers['Cache-Control'] == 'no-cache')
check('privacy page', c.get('/privacy').status_code == 200 and b'Privacy Policy' in c.get('/privacy').data)
check('delete-account page', c.get('/delete-account').status_code == 200)
check('offline page', c.get('/offline.html').status_code == 200)
check('icons exist', all(c.get('/assets/' + f).status_code == 200 for f in ['icon-192.png', 'icon-512.png', 'icon-maskable-512.png', 'apple-touch-icon.png']))
s, cfg = call('GET', '/api/public-config'); check('public config', cfg['playStore'].startswith('https://play.google.com') and cfg['allowPay'] is False)
T = call('POST', '/api/register', {'name': 'Ali', 'mobile': '03001234567', 'shop': 'Ali Store', 'password': 'Ali@1234'})[1]['token']
call('POST', '/api/entries/sales', {'name': 'Rice', 'type': 'cash', 'amount': 500, 'date': '2026-10-10'}, T)
check('wrong password cannot delete', call('POST', '/api/account/delete', {'password': 'nope'}, T)[0] == 401)
dbs = lambda: len([f for f in os.listdir(os.path.join(tmp, 'shops')) if f.endswith('.db')])
check('shop database exists', dbs() == 1)
check('delete account', call('POST', '/api/account/delete', {'password': 'Ali@1234'}, T)[0] == 200)
check('login no longer works', call('POST', '/api/login', {'id': '03001234567', 'password': 'Ali@1234'})[0] == 401)
check('its database is gone', dbs() == 0)
check('same mobile can register again', call('POST', '/api/register', {'name': 'Ali', 'mobile': '03001234567', 'shop': 'New', 'password': 'Ali@1234'})[0] == 200)
print('\nALL PASSED' if ok else '\nSOME FAILED'); sys.exit(0 if ok else 1)

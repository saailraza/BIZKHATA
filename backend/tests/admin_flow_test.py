"""python tests/admin_flow_test.py  -> admin side: payments, password reset, trial block, delete (SQLite, no PostgreSQL needed)"""
import os, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ.update(DB_ENGINE='sqlite', DATA_DIR=tmp, SECRET='t')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bizkhata.app import create_app
from bizkhata import db
app = create_app(); c = app.test_client(); ok = True
def call(m, p, b=None, t=None):
    r = c.open(p, method=m, json=b, headers={'Authorization': 'Bearer ' + t} if t else {}); return r.status_code, r.get_json()
def check(n, cond):
    global ok; ok = ok and cond; print(('PASS ' if cond else 'FAIL ') + n)
SLIP = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
A = call('POST', '/api/login', {'id': 'admin', 'password': '123456'})[1]['token']
T = call('POST', '/api/register', {'name': 'Ali', 'mobile': '03001234567', 'shop': 'Ali Store', 'password': 'Ali@1234'})[1]['token']
T2 = call('POST', '/api/register', {'name': 'Sara', 'mobile': '03211111111', 'shop': 'Sara Mart', 'password': 'Sara@1234'})[1]['token']
call('POST', '/api/entries/sales', {'name': 'Rice', 'type': 'cash', 'amount': 500, 'date': '2026-10-10'}, T)
check('each shop has its own database file', len([f for f in os.listdir(os.path.join(tmp, 'shops')) if f.endswith('.db')]) == 2)
check('shops never see each other', call('GET', '/api/report', t=T2)[1]['pl']['sales'] == 0 and call('GET', '/api/report', t=T)[1]['pl']['sales'] == 500)
b = call('GET', '/api/billing', t=T)[1]['bills'][0]
check('pay needs slip', call('POST', '/api/billing/pay', {'billId': b['id'], 'slip': 'x'}, T)[1]['code'] == 'SLIP')
check('pay ok', call('POST', '/api/billing/pay', {'billId': b['id'], 'slip': SLIP}, T)[0] == 200)
check('pay twice refused', call('POST', '/api/billing/pay', {'billId': b['id'], 'slip': SLIP}, T)[1]['code'] == 'PENDING')
ap = call('GET', '/api/admin/approvals', t=A)[1]
check('admin sees pending payment', len(ap['payments']) == 1 and ap['payments'][0]['amount'] == 999)
check('slip viewable', call('GET', '/api/admin/payments/%s/slip' % ap['payments'][0]['id'], t=A)[1]['slip'].startswith('data:image'))
check('approve ok', call('POST', '/api/admin/payments/%s/approve' % ap['payments'][0]['id'], t=A)[0] == 200)
me = call('GET', '/api/me', t=T)[1]
check('shop active + next due set', me['shop']['status'] == 'full' and me['shop']['nextDue'] and me['blocked'] is None)
# forgot password
check('forgot ok', call('POST', '/api/forgot', {'mobile': '03001234567', 'password': 'New@9999'})[0] == 200)
check('old password still works before approval', call('POST', '/api/login', {'id': '03001234567', 'password': 'Ali@1234'})[0] == 200)
rid = call('GET', '/api/admin/approvals', t=A)[1]['resets'][0]['id']
call('POST', '/api/admin/resets/%s/approve' % rid, t=A)
check('new password works after approval', call('POST', '/api/login', {'id': '0300 1234567', 'password': 'New@9999'})[0] == 200)
check('old password stops', call('POST', '/api/login', {'id': '03001234567', 'password': 'Ali@1234'})[0] == 401)
# trial expiry -> blocked, only billing open
m = db.master; m.execute('UPDATE shops SET trial_ends_at = $1 WHERE id = (SELECT shop_id FROM users WHERE mobile = $2)', [int(time.time() * 1000) - 1000, '03211111111'])
s, r = call('GET', '/api/report', t=T2)
check('trial ended -> blocked', s == 403 and r['code'] == 'BLOCKED')
check('billing still open when blocked', call('GET', '/api/billing', t=T2)[0] == 200)
check('/me tells why', call('GET', '/api/me', t=T2)[1]['blocked'] == 'trial_ended')
# settings
check('settings save', call('PUT', '/api/admin/settings', {'monthlyFee': 1200, 'bankDetails': 'HBL 123', 'whatsapp': '+92 308 4535456', 'trialDays': 7, 'graceDays': 5, 'adminName': 'Boss', 'adminLogin': 'admin@bizease.com'}, A)[0] == 200)
check('settings read', call('GET', '/api/admin/settings', t=A)[1]['bankDetails'] == 'HBL 123')
# admin add / plan / delete company
check('admin add company', call('POST', '/api/admin/shops', {'shop': 'Zed', 'name': 'Zed', 'mobile': '03451234567', 'password': 'Zed@1234', 'status': 'trial'}, A)[0] == 200)
shops = call('GET', '/api/admin/shops', t=A)[1]['shops']; zed = [x for x in shops if x['name'] == 'Zed'][0]
check('plan change', call('POST', '/api/admin/shops/%s/plan' % zed['id'], {'status': 'full', 'fee': 1500, 'nextDue': '2026-11-20', 'generateBill': True}, A)[0] == 200)
dbs = lambda: len([f for f in os.listdir(os.path.join(tmp, 'shops')) if f.endswith('.db')])
before = dbs()
check('delete company', call('DELETE', '/api/admin/shops/%s' % zed['id'], t=A)[0] == 200)
check('its database was removed too', dbs() == before - 1)
check('shop token cannot use admin API', call('GET', '/api/admin/shops', t=T)[0] == 401)
check('no token -> 401', call('GET', '/api/me')[0] == 401)
print('\nALL PASSED' if ok else '\nSOME FAILED'); sys.exit(0 if ok else 1)

"""python tests/smoke_test.py   -> runs the whole API against a temporary SQLite copy (no PostgreSQL needed)."""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(DB_ENGINE='sqlite', DATA_DIR=tmp, SECRET='test-secret')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bizkhata.app import create_app  # noqa: E402

app = create_app()
c = app.test_client()
ok = True


def call(method, path, body=None, token=None):
    h = {'Authorization': 'Bearer ' + token} if token else {}
    r = c.open(path, method=method, json=body, headers=h)
    return r.status_code, r.get_json()


def check(name, cond):
    global ok
    ok = ok and cond
    print(('PASS ' if cond else 'FAIL ') + name)


s, r = call('POST', '/api/register', {'name': 'Ali', 'mobile': '0412345678', 'shop': 'A', 'password': 'Ali@1234'})
check('mobile must start with 03', r['code'] == 'BAD_MOBILE')
s, r = call('POST', '/api/register', {'name': 'Ali', 'mobile': '03001234567', 'shop': 'Ali Store', 'password': '1234'})
check('weak password refused', r['code'] == 'SHORT_PASS')
s, r = call('POST', '/api/register', {'name': 'Ali', 'mobile': '0300-1234567', 'shop': 'Ali Store', 'password': 'Ali@1234'})
T = r['token']
check('register ok', s == 200)
s, r = call('POST', '/api/register', {'name': 'Bob', 'mobile': '03001234567', 'shop': 'B', 'password': 'Bob@1234'})
check('mobile unique', r['code'] == 'MOBILE_TAKEN')
s, r = call('GET', '/api/billing', token=T)
check('first bill is 999', len(r['bills']) == 1 and r['bills'][0]['amount'] == 999)
s, r = call('POST', '/api/entries/purchases', {'name': 'F', 'type': 'cash', 'amount': 100, 'date': '2026-10-10'}, T)
check('no cash -> purchase refused', r['code'] == 'NEG_CASH')
s, r = call('POST', '/api/entries/sales', {'name': 'Rice', 'type': 'cash', 'amount': 1000, 'date': '2026-10-10'}, T)
check('cash sale ok', s == 200)
s, r = call('POST', '/api/entries/sales', {'name': 'Oil', 'type': 'udhar', 'amount': 700, 'partyNew': 'Bilal', 'date': '2026-10-12'}, T)
s, r = call('GET', '/api/settlements?kind=customer', token=T)
pid = r['parties'][0]['id']
check('party balance 700', r['parties'][0]['balance'] == 700)
s, r = call('POST', '/api/settlements', {'partyId': pid, 'amount': 800, 'mode': 'cash', 'date': '2026-10-12'}, T)
check('cannot receive more than owed', r['code'] == 'NEG_PARTY')
s, r = call('POST', '/api/settlements', {'partyId': pid, 'amount': 300, 'mode': 'bank', 'date': '2026-10-12'}, T)
check('receive 300 to bank', s == 200)
s, r = call('GET', '/api/entries/sales', token=T)
rice = [x for x in r['rows'] if x['name'] == 'Rice'][0]
s, r = call('DELETE', '/api/entries/sales/' + rice['id'], token=T)
check('delete that makes cash negative is refused or ok', s in (200, 400))
s, r = call('GET', '/api/export', token=T)
check('excel export', s == 200 and r['filename'].endswith('.xlsx'))
exp = r['data']
s, r = call('POST', '/api/import', {'file': exp}, T)
check('backup import', s == 200 and r['total'] >= 1)
s, r = call('POST', '/api/login', {'id': 'admin', 'password': '123456'})
A = r['token']
check('admin login', r['role'] == 'admin')
s, r = call('GET', '/api/admin/shops', token=A)
check('admin sees the shop', r['counts']['total'] == 1)
s, r = call('GET', '/api/health')
check('health', r['ok'])
print('\nALL PASSED' if ok else '\nSOME TESTS FAILED')
sys.exit(0 if ok else 1)

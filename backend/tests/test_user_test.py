"""python tests/test_user_test.py  -> the fixed test account (biztest / Test@1234)"""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DB_ENGINE='sqlite', DATA_DIR=tmp, SECRET='t', TEST_USER='1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bizkhata.app import create_app
ok = True
def check(n, c):
    global ok; ok = ok and c; print(('PASS ' if c else 'FAIL ') + n)
def call(cl, m, p, b=None, t=None):
    r = cl.open(p, method=m, json=b, headers={'Authorization': 'Bearer ' + t} if t else {}); return r.status_code, r.get_json()
c = create_app().test_client()
s, r = call(c, 'POST', '/api/login', {'id': 'biztest', 'password': 'Test@1234'})
check('biztest / Test@1234 logs in', s == 200 and r['role'] == 'shop')
T = r['token']
me = call(c, 'GET', '/api/me', t=T)[1]
check('always active (never blocked)', me['shop']['status'] == 'full' and me['blocked'] is None and me['shop']['name'] == 'Test Shop')
check('works with the mobile number too', call(c, 'POST', '/api/login', {'id': '03000000000', 'password': 'Test@1234'})[0] == 200)
check('wrong password refused', call(c, 'POST', '/api/login', {'id': 'biztest', 'password': 'x'})[0] == 401)
check('can add entries', call(c, 'POST', '/api/entries/sales', {'name': 'Rice', 'type': 'cash', 'amount': 500, 'date': '2026-10-10'}, T)[0] == 200)
# a second "browser" / a restart of the server: same account, same data
c2 = create_app().test_client()
T2 = call(c2, 'POST', '/api/login', {'id': 'biztest', 'password': 'Test@1234'})[1]['token']
check('same account and same data after restart / other browser', call(c2, 'GET', '/api/report', t=T2)[1]['pl']['sales'] == 500)
os.environ['TEST_USER'] = '0'
check('real users cannot take the test mobile', call(c2, 'POST', '/api/register', {'name': 'X', 'mobile': '03000000000', 'shop': 'Y', 'password': 'Xyz@1234'})[1]['code'] == 'MOBILE_TAKEN')
check('switched off: the biztest name stops working', call(c2, 'POST', '/api/login', {'id': 'biztest', 'password': 'Test@1234'})[0] == 401)
print('\nALL PASSED' if ok else '\nSOME FAILED'); sys.exit(0 if ok else 1)

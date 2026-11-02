"""Trial, billing, grace period and blocking rules."""
from . import db
from .util import add_days, add_months, now_ms, today, uid, is_unique_error, days_between


def get_settings(c=None):
    return (c or db.master).query('SELECT * FROM app_settings WHERE id = 1')[0]


def log_act(c, shop_id, actor, action, detail=''):
    c.execute('INSERT INTO activity_log (id, shop_id, actor, action, detail, created_at) VALUES ($1,$2,$3,$4,$5,$6)',
              [uid(), shop_id, actor, action, str(detail)[:300], now_ms()])


def next_no(c, name, prefix, width):
    r = c.query('INSERT INTO counters (name, value) VALUES ($1, 1) ON CONFLICT (name) DO UPDATE SET value = counters.value + 1 RETURNING value', [name])
    return prefix + str(r[0]['value']).zfill(width)


def create_bill(c, shop_id, amount, due, note='Monthly subscription', monthly=True, auto=False):
    bid, no = uid(), next_no(c, 'bill', 'INV-', 4)
    c.execute("""INSERT INTO bills (id, shop_id, bill_no, amount, issue_date, due_date, status, note, is_monthly, is_auto, created_at)
                 VALUES ($1,$2,$3,$4,$5,$6,'due',$7,$8,$9,$10)""",
              [bid, shop_id, no, amount, today(), due, note, 1 if monthly else 0, 1 if auto else 0, now_ms()])
    return {'id': bid, 'no': no}


def refresh_statuses():
    """free trial over -> the ID is blocked"""
    return db.master.execute("UPDATE shops SET status = 'suspended', auto_suspended = 1 WHERE status = 'trial' AND trial_ends_at < $1", [now_ms()])


def block_reason(shop, due_bills, st):
    """None = the shop may use the app. Otherwise: trial_ended / suspended / pending / rejected / overdue"""
    if shop['status'] in ('pending', 'rejected'):
        return shop['status']
    if shop['status'] == 'suspended':
        return 'trial_ended' if shop['auto_suspended'] else 'suspended'
    if shop['status'] == 'trial' and shop['trial_ends_at'] < now_ms():
        return 'trial_ended'
    limit = add_days(today(), -int(st['grace_days']))
    if any(b['due_date'] < limit for b in due_bills):
        return 'overdue'
    return None


def generate_bills():
    """monthly bill, bill_advance_days before each due date (paid shops only)"""
    st = get_settings()
    limit = add_days(today(), int(st['bill_advance_days']))
    shops = db.master.query("SELECT * FROM shops WHERE status IN ('full','partial') AND next_due_date IS NOT NULL AND next_due_date <= $1", [limit])
    n = 0
    for s in shops:
        fee = float(s['monthly_fee']) if float(s['monthly_fee']) > 0 else float(st['monthly_fee'])
        if not fee > 0:
            continue
        if db.master.query('SELECT 1 FROM bills WHERE shop_id = $1 AND is_monthly = 1 AND due_date = $2', [s['id'], s['next_due_date']]):
            continue
        try:
            with db.master.tx() as c:
                create_bill(c, s['id'], fee, s['next_due_date'], auto=True)
            n += 1
        except Exception as e:           # another worker created it a moment ago
            if not is_unique_error(e):
                raise
    return n


def pay_bill(c, bill_id):
    """mark a bill paid and move the shop's next due date one month ahead"""
    rows = c.query('SELECT * FROM bills WHERE id = $1', [bill_id])
    if not rows or rows[0]['status'] == 'paid':
        return rows[0] if rows else None
    b = rows[0]
    c.execute("UPDATE bills SET status = 'paid', paid_at = $1 WHERE id = $2", [now_ms(), b['id']])
    shops = c.query('SELECT * FROM shops WHERE id = $1', [b['shop_id']])
    if shops and b['is_monthly']:
        n = add_months(b['due_date'], 1)
        if not shops[0]['next_due_date'] or shops[0]['next_due_date'] < n:
            c.execute('UPDATE shops SET next_due_date = $1 WHERE id = $2', [n, shops[0]['id']])
    return b


def shop_view(s, **extra):
    d = {
        'id': s['id'], 'name': s['name'], 'owner': s['owner_name'], 'status': s['status'], 'autoSuspended': bool(s['auto_suspended']),
        'registeredAt': s['registered_at'], 'trialEnds': s['trial_ends_at'],
        'daysLeft': max(0, -(-(s['trial_ends_at'] - now_ms()) // 86400000)),
        'fee': float(s['monthly_fee']) or 0, 'nextDue': s['next_due_date'] or '',
    }
    d.update(extra)
    return d

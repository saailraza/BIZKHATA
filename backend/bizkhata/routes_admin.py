"""Admin side: companies, approvals (payment slips, password resets, registrations), billing, settings."""
import re
from datetime import datetime

from . import db, logic, security as sec
from .framework import api
from .routes_public import create_shop, mobile_taken
from .util import HttpError, MOBILE_RE, bad, days_between, is_unique_error, norm_mobile, now_ms, r2, s, today

STATUSES = ('pending', 'trial', 'partial', 'full', 'suspended', 'rejected')


def summaries(status='', q=''):
    st = logic.get_settings()
    shops = db.master.query('SELECT s.*, u.mobile FROM shops s JOIN users u ON u.shop_id = s.id ORDER BY s.registered_at DESC')
    due = db.master.query("SELECT shop_id, due_date, amount FROM bills WHERE status = 'due'")
    q = (q or '').lower()
    allv = []
    for sh in shops:
        mine = [b for b in due if b['shop_id'] == sh['id']]
        reason = logic.block_reason(sh, mine, st)
        allv.append(logic.shop_view(sh, mobile=sh['mobile'], reason=reason, unpaid=r2(sum(float(b['amount']) for b in mine)), overdue=reason == 'overdue'))
    counts = {
        'total': len(allv), 'pending': sum(1 for x in allv if x['status'] == 'pending'),
        'trial': sum(1 for x in allv if x['status'] == 'trial' and not x['reason']),
        'partial': sum(1 for x in allv if x['status'] == 'partial'), 'full': sum(1 for x in allv if x['status'] == 'full'),
        'blocked': sum(1 for x in allv if x['reason'] and x['reason'] != 'pending'), 'unpaid': r2(sum(x['unpaid'] for x in allv)),
    }

    def keep(x):
        if status:
            ok = (x['reason'] and x['reason'] != 'pending') if status == 'blocked' else x['status'] == status
            if not ok:
                return False
        return not q or q in ' '.join([x['name'], x['owner'], x['mobile']]).lower()

    return [x for x in allv if keep(x)], counts


def pending_count():
    n = 0
    for t, cond in (('payment_requests', "status = 'pending'"), ('password_reset_requests', "status = 'pending'"), ('shops', "status = 'pending'")):
        n += int(db.master.query('SELECT COUNT(*) AS c FROM %s WHERE %s' % (t, cond))[0]['c'])
    return n


def get_shop(sid):
    r = db.master.query('SELECT * FROM shops WHERE id = $1', [sid])
    if not r:
        raise HttpError(404, 'NOT_FOUND', 'Shop not found')
    return r[0]


def date_of(ms):
    return datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d')


@api('/api/admin/counts', auth='admin')
def counts(ctx):
    return {'approvals': pending_count()}


# ---------------- companies ----------------
@api('/api/admin/shops', auth='admin')
def shops_list(ctx):
    lst, cnt = summaries(ctx.query.get('status', ''), ctx.query.get('q', ''))
    pays = db.master.query("""SELECT r.id, r.amount, r.created_at, s.name AS shop_name, b.bill_no FROM payment_requests r
        JOIN shops s ON s.id = r.shop_id JOIN bills b ON b.id = r.bill_id WHERE r.status = 'pending' ORDER BY r.created_at""")
    return {'shops': lst, 'counts': cnt, 'approvals': pending_count(),
            'payments': [{'id': p['id'], 'shop': p['shop_name'], 'bill': p['bill_no'], 'amount': float(p['amount']), 'at': p['created_at']} for p in pays]}


@api('/api/admin/shops/<sid>', auth='admin')
def shop_detail(ctx):
    sh = get_shop(ctx.params['sid'])
    u = db.master.query('SELECT * FROM users WHERE shop_id = $1', [sh['id']])[0]
    bills = db.master.query('SELECT * FROM bills WHERE shop_id = $1 ORDER BY due_date DESC', [sh['id']])
    log = db.master.query('SELECT actor, action, detail, created_at FROM activity_log WHERE shop_id = $1 ORDER BY created_at DESC LIMIT 80', [sh['id']])
    st = logic.get_settings()
    return {
        'shop': logic.shop_view(sh, mobile=u['mobile'], ownerName=u['name'], reason=logic.block_reason(sh, [b for b in bills if b['status'] == 'due'], st), dbName=sh['db_name']),
        'bills': [{'id': b['id'], 'no': b['bill_no'], 'amount': float(b['amount']), 'issue': b['issue_date'], 'due': b['due_date'], 'status': b['status'], 'note': b['note'],
                   'late': max(0, days_between(today(), b['due_date'])) if b['status'] == 'due' else 0} for b in bills],
        'log': [{'actor': l['actor'], 'action': l['action'], 'detail': l['detail'], 'at': l['created_at']} for l in log],
    }


@api('/api/admin/shops', ['POST'], auth='admin')
def shop_add(ctx):
    b = ctx.body
    status = b.get('status') if b.get('status') in STATUSES else 'trial'
    r = create_shop(b.get('name'), b.get('mobile'), b.get('shop'), b.get('password'), status, 'admin')
    return {'ok': True, 'id': r['shop_id']}


@api('/api/admin/shops/<sid>/plan', ['POST'], auth='admin')
def shop_plan(ctx):
    sh, b, st = get_shop(ctx.params['sid']), ctx.body, logic.get_settings()
    status = str(b.get('status') or '')
    if status not in STATUSES:
        raise bad('STATUS', 'Choose a status')
    fee = max(0.0, r2(b.get('fee')))
    paid = status in ('full', 'partial')
    due = (s(b.get('nextDue'), 10) or None) if paid else None
    if paid and fee > 0 and not due:
        raise bad('DUE', 'Choose the due date')
    trial_ends = sh['trial_ends_at']
    if status == 'trial' and sh['status'] != 'trial':
        try:
            days = max(1, int(float(b.get('trialDays') or 0))) or st['trial_days']
        except (TypeError, ValueError):
            days = st['trial_days']
        trial_ends = now_ms() + days * 86400000
    with db.master.tx() as c:
        c.execute('UPDATE shops SET status = $1, auto_suspended = $2, monthly_fee = $3, next_due_date = $4, trial_ends_at = $5 WHERE id = $6',
                  [status, (1 if sh['auto_suspended'] else 0) if status == 'suspended' else 0, fee, due, trial_ends, sh['id']])
        if paid and fee > 0 and due and b.get('generateBill'):
            if not c.query('SELECT 1 FROM bills WHERE shop_id = $1 AND is_monthly = 1 AND due_date = $2', [sh['id'], due]):
                logic.create_bill(c, sh['id'], fee, due)
        logic.log_act(c, sh['id'], 'admin', 'Company approved' if sh['status'] == 'pending' else 'Plan changed', '%s - fee %s' % (status, fee))
    return {'ok': True}


@api('/api/admin/shops/<sid>/block', ['POST'], auth='admin')
def shop_block(ctx):
    sh = get_shop(ctx.params['sid'])
    db.master.execute("UPDATE shops SET status = 'suspended', auto_suspended = 0 WHERE id = $1", [sh['id']])
    logic.log_act(db.master, sh['id'], 'admin', 'Company blocked')
    return {'ok': True}


@api('/api/admin/shops/<sid>/reject', ['POST'], auth='admin')
def shop_reject(ctx):
    sh = get_shop(ctx.params['sid'])
    db.master.execute("UPDATE shops SET status = 'rejected' WHERE id = $1", [sh['id']])
    logic.log_act(db.master, sh['id'], 'admin', 'Registration rejected')
    return {'ok': True}


@api('/api/admin/shops/<sid>', ['PUT'], auth='admin')
def shop_edit(ctx):
    sh = get_shop(ctx.params['sid'])
    u = db.master.query('SELECT * FROM users WHERE shop_id = $1', [sh['id']])[0]
    b = ctx.body
    name, owner, mobile, np = s(b.get('name'), 100), s(b.get('owner'), 80), norm_mobile(b.get('mobile')), str(b.get('password') or '')
    if not name or not owner:
        raise bad('FIELDS', 'Shop name and owner name are required')
    if not MOBILE_RE.match(mobile):
        raise bad('BAD_MOBILE', 'Mobile number must be 11 digits and start with 03')
    if np:
        sec.require_strong_password(np)
    if mobile_taken(db.master, mobile, u['id']):
        raise bad('MOBILE_TAKEN', 'This mobile number is already registered')
    try:
        with db.master.tx() as c:
            c.execute('UPDATE shops SET name = $1, owner_name = $2 WHERE id = $3', [name, owner, sh['id']])
            c.execute('UPDATE users SET name = $1, mobile = $2 WHERE id = $3', [owner, mobile, u['id']])
            if np:
                c.execute('UPDATE users SET password_hash = $1 WHERE id = $2', [sec.hash_password(np), u['id']])
            logic.log_act(c, sh['id'], 'admin', 'Company edited', 'password reset' if np else '')
    except Exception as e:
        if is_unique_error(e):
            raise bad('MOBILE_TAKEN', 'This mobile number is already registered')
        raise
    return {'ok': True}


@api('/api/admin/shops/<sid>', ['DELETE'], auth='admin')
def shop_delete(ctx):
    """deletes the shop AND its separate database"""
    sh = get_shop(ctx.params['sid'])
    db.master.execute('DELETE FROM shops WHERE id = $1', [sh['id']])
    db.drop_shop_db(sh['db_name'])
    return {'ok': True}


# ---------------- approvals ----------------
@api('/api/admin/approvals', auth='admin')
def approvals(ctx):
    pays = db.master.query("""SELECT r.id, r.amount, r.created_at, s.id AS shop_id, s.name AS shop_name, u.mobile, b.bill_no
        FROM payment_requests r JOIN shops s ON s.id = r.shop_id JOIN users u ON u.shop_id = s.id JOIN bills b ON b.id = r.bill_id
        WHERE r.status = 'pending' ORDER BY r.created_at""")
    resets = db.master.query("""SELECT r.id, r.created_at, s.id AS shop_id, s.name AS shop_name, u.mobile FROM password_reset_requests r
        JOIN users u ON u.id = r.user_id JOIN shops s ON s.id = r.shop_id WHERE r.status = 'pending' ORDER BY r.created_at""")
    regs = db.master.query("SELECT s.id, s.name, s.owner_name, s.registered_at, u.mobile FROM shops s JOIN users u ON u.shop_id = s.id WHERE s.status = 'pending' ORDER BY s.registered_at")
    hp = db.master.query("SELECT r.status, r.amount, r.resolved_at AS at, s.name AS shop_name FROM payment_requests r JOIN shops s ON s.id = r.shop_id WHERE r.status <> 'pending' ORDER BY r.resolved_at DESC LIMIT 10")
    hr = db.master.query("SELECT r.status, r.resolved_at AS at, s.name AS shop_name FROM password_reset_requests r JOIN shops s ON s.id = r.shop_id WHERE r.status <> 'pending' ORDER BY r.resolved_at DESC LIMIT 10")
    handled = [{'type': 'Payment', 'shop': r['shop_name'], 'detail': str(float(r['amount']) if float(r['amount']) % 1 else int(r['amount'])), 'status': r['status'], 'at': r['at']} for r in hp] + \
              [{'type': 'Password reset', 'shop': r['shop_name'], 'detail': '', 'status': r['status'], 'at': r['at']} for r in hr]
    handled.sort(key=lambda x: x['at'] or 0, reverse=True)
    return {
        'payments': [{'id': p['id'], 'shopId': p['shop_id'], 'shop': p['shop_name'], 'mobile': p['mobile'], 'bill': p['bill_no'], 'amount': float(p['amount']), 'at': p['created_at']} for p in pays],
        'resets': [{'id': r['id'], 'shopId': r['shop_id'], 'shop': r['shop_name'], 'mobile': r['mobile'], 'at': r['created_at']} for r in resets],
        'registrations': [{'id': r['id'], 'shop': r['name'], 'owner': r['owner_name'], 'mobile': r['mobile'], 'at': r['registered_at']} for r in regs],
        'handled': handled[:12],
    }


@api('/api/admin/payments/<pid>/slip', auth='admin')
def payment_slip(ctx):
    r = db.master.query('SELECT slip FROM payment_requests WHERE id = $1', [ctx.params['pid']])
    if not r:
        raise HttpError(404, 'NOT_FOUND', 'Not found')
    return {'slip': r[0]['slip']}


@api('/api/admin/payments/<pid>/approve', ['POST'], auth='admin')
def payment_approve(ctx):
    with db.master.tx() as c:
        r = c.query("SELECT * FROM payment_requests WHERE id = $1 AND status = 'pending'", [ctx.params['pid']])
        if not r:
            raise bad('HANDLED', 'Request not found or already handled')
        r = r[0]
        shop = c.query('SELECT * FROM shops WHERE id = $1', [r['shop_id']])[0]
        c.execute("UPDATE payment_requests SET status = 'approved', resolved_at = $1 WHERE id = $2", [now_ms(), r['id']])
        logic.pay_bill(c, r['bill_id'])
        c.execute("UPDATE shops SET status = 'full', auto_suspended = 0, monthly_fee = $1 WHERE id = $2",
                  [shop['monthly_fee'] if float(shop['monthly_fee']) > 0 else r['amount'], shop['id']])
        logic.log_act(c, shop['id'], 'admin', 'Payment approved', str(float(r['amount'])))
    return {'ok': True}


@api('/api/admin/payments/<pid>/reject', ['POST'], auth='admin')
def payment_reject(ctx):
    if not db.master.execute("UPDATE payment_requests SET status = 'rejected', resolved_at = $1 WHERE id = $2 AND status = 'pending'", [now_ms(), ctx.params['pid']]):
        raise bad('HANDLED', 'Request not found or already handled')
    return {'ok': True}


@api('/api/admin/resets/<rid>/approve', ['POST'], auth='admin')
def reset_approve(ctx):
    with db.master.tx() as c:
        r = c.query("SELECT * FROM password_reset_requests WHERE id = $1 AND status = 'pending'", [ctx.params['rid']])
        if not r:
            raise bad('HANDLED', 'Request not found or already handled')
        r = r[0]
        c.execute('UPDATE users SET password_hash = $1 WHERE id = $2', [r['new_password_hash'], r['user_id']])
        c.execute("UPDATE password_reset_requests SET status = 'approved', resolved_at = $1 WHERE id = $2", [now_ms(), r['id']])
        logic.log_act(c, r['shop_id'], 'admin', 'Password reset approved')
    return {'ok': True}


@api('/api/admin/resets/<rid>/reject', ['POST'], auth='admin')
def reset_reject(ctx):
    if not db.master.execute("UPDATE password_reset_requests SET status = 'rejected', resolved_at = $1 WHERE id = $2 AND status = 'pending'", [now_ms(), ctx.params['rid']]):
        raise bad('HANDLED', 'Request not found or already handled')
    return {'ok': True}


# ---------------- billing ----------------
@api('/api/admin/bills', auth='admin')
def bills_list(ctx):
    rows = db.master.query('SELECT b.*, s.name AS shop_name FROM bills b JOIN shops s ON s.id = b.shop_id ORDER BY b.due_date DESC, b.created_at DESC')
    t, st = today(), logic.get_settings()
    bills = [{'id': b['id'], 'no': b['bill_no'], 'shopId': b['shop_id'], 'shop': b['shop_name'], 'amount': float(b['amount']), 'issue': b['issue_date'], 'due': b['due_date'],
              'status': b['status'], 'note': b['note'], 'overdue': b['status'] == 'due' and b['due_date'] < t, 'paidAt': b['paid_at']} for b in rows]

    def total(f):
        return r2(sum(b['amount'] for b in bills if f(b)))

    f = ctx.query.get('status', '')
    if f == 'due':
        shown = [b for b in bills if b['status'] == 'due' and not b['overdue']]
    elif f == 'overdue':
        shown = [b for b in bills if b['overdue']]
    elif f == 'paid':
        shown = [b for b in bills if b['status'] == 'paid']
    else:
        shown = bills
    return {'stats': {'unpaid': total(lambda b: b['status'] == 'due'), 'overdue': total(lambda b: b['overdue']), 'received': total(lambda b: b['status'] == 'paid'), 'count': len(bills)},
            'bills': shown, 'shops': db.master.query('SELECT id, name, status FROM shops ORDER BY name'), 'graceDays': st['grace_days']}


@api('/api/admin/bills', ['POST'], auth='admin')
def bill_create(ctx):
    b = ctx.body
    sh, amount, due = get_shop(b.get('shopId')), r2(b.get('amount')), s(b.get('due'), 10)
    if not amount > 0:
        raise bad('AMOUNT', 'Enter the bill amount')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', due):
        raise bad('DUE', 'Choose the due date')
    try:
        with db.master.tx() as c:
            logic.create_bill(c, sh['id'], amount, due, s(b.get('note'), 120) or 'Monthly subscription', bool(b.get('monthly')), False)
    except Exception as e:
        if is_unique_error(e):
            raise bad('DUPLICATE', 'A monthly bill for this due date already exists')
        raise
    logic.log_act(db.master, sh['id'], 'admin', 'Bill created', '%s due %s' % (amount, due))
    return {'ok': True}


@api('/api/admin/bills/<bid>/pay', ['POST'], auth='admin')
def bill_mark_paid(ctx):
    with db.master.tx() as c:
        b = logic.pay_bill(c, ctx.params['bid'])
        if b:
            c.execute("UPDATE shops SET status = CASE WHEN status IN ('trial','suspended') THEN 'full' ELSE status END, auto_suspended = 0 WHERE id = $1", [b['shop_id']])
            logic.log_act(c, b['shop_id'], 'admin', 'Bill marked paid', b['bill_no'])
    return {'ok': True}


@api('/api/admin/bills/<bid>', ['DELETE'], auth='admin')
def bill_delete(ctx):
    db.master.execute('DELETE FROM bills WHERE id = $1', [ctx.params['bid']])
    return {'ok': True}


# ---------------- settings ----------------
@api('/api/admin/settings', auth='admin')
def settings_get(ctx):
    st = logic.get_settings()
    return {'monthlyFee': float(st['monthly_fee']), 'bankDetails': st['bank_details'], 'whatsapp': st['support_whatsapp'], 'trialDays': st['trial_days'],
            'graceDays': st['grace_days'], 'adminName': ctx.admin['name'], 'adminLogin': ctx.admin['login_id']}


@api('/api/admin/settings', ['PUT'], auth='admin')
def settings_put(ctx):
    b = ctx.body
    login, name, np = s(b.get('adminLogin'), 120).lower(), s(b.get('adminName'), 80), str(b.get('newPassword') or '')
    if not login or not name:
        raise bad('FIELDS', 'Name and login ID are required')
    if np:
        sec.require_strong_password(np)
    if re.fullmatch(r'[\d+\s-]+', login) and db.master.query('SELECT 1 FROM users WHERE mobile = $1', [norm_mobile(login)]):
        raise bad('MOBILE_TAKEN', 'A shop user already uses this login ID')

    def to_int(v, default, lo):
        try:
            return max(lo, int(float(v)))
        except (TypeError, ValueError):
            return default

    try:
        with db.master.tx() as c:
            c.execute('UPDATE app_settings SET monthly_fee = $1, bank_details = $2, support_whatsapp = $3, trial_days = $4, grace_days = $5 WHERE id = 1',
                      [max(0.0, r2(b.get('monthlyFee'))), s(b.get('bankDetails'), 600), re.sub(r'\D', '', s(b.get('whatsapp'), 20)),
                       to_int(b.get('trialDays'), 7, 1), to_int(b.get('graceDays'), 5, 0)])
            c.execute('UPDATE admins SET name = $1, login_id = $2 WHERE id = $3', [name, login, ctx.admin['id']])
            if np:
                c.execute('UPDATE admins SET password_hash = $1 WHERE id = $2', [sec.hash_password(np), ctx.admin['id']])
    except Exception as e:
        if is_unique_error(e):
            raise bad('MOBILE_TAKEN', 'This login ID is already used')
        raise
    return {'ok': True}

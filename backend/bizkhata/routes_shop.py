"""Shopkeeper side: entries, udhar received / paid, report, Excel export, backup import, billing."""
import base64
import re

from . import db, logic, security as sec, xlsx
from .framework import api, sdb
from .util import HttpError, add_days, bad, check_date, days_between, is_date, now_ms, r2, s, today, uid, ymd
from datetime import datetime

KINDS = {
    'sales':     {'table': 'sales',          'name': 'item_name',    'party': 'customer', 'udhar': True,  'sheet': 'Sale'},
    'purchases': {'table': 'purchases',      'name': 'item_name',    'party': 'supplier', 'udhar': True,  'sheet': 'Purchase'},
    'income':    {'table': 'other_income',   'name': 'detail',       'party': None,       'udhar': False, 'sheet': 'Other Income'},
    'expenses':  {'table': 'other_expenses', 'name': 'expense_type', 'party': None,       'udhar': False, 'sheet': 'Other Expenses'},
}
TYPE_LABEL = {'cash': 'Cash', 'bank': 'Bank', 'udhar': 'Udhar'}


def kind_of(k):
    if k not in KINDS:
        raise HttpError(404, 'NOT_FOUND', 'Unknown entry type')
    return KINDS[k]


def not_found():
    return HttpError(404, 'NOT_FOUND', 'Entry not found')


def name_key(x):
    return re.sub(r'\s+', ' ', x.lower())


# =====================================================================
# Balance rules, checked after EVERY add / edit / delete / import:
#   - cash balance and bank balance must never go below zero on any date
#   - a party's udhar balance must never go below zero on any date
# (on the same date, money coming in counts before money going out)
# =====================================================================
MONEY_EVENTS = """
  SELECT d, SUM(i) AS i, SUM(o) AS o FROM (
    SELECT entry_date AS d, amount AS i, 0 AS o FROM sales WHERE pay_type = $1
    UNION ALL SELECT entry_date, amount, 0 FROM other_income WHERE pay_type = $1
    UNION ALL SELECT x.entry_date, x.amount, 0 FROM settlements x JOIN parties p ON p.id = x.party_id WHERE p.kind = 'customer' AND x.mode = $1
    UNION ALL SELECT entry_date, 0, amount FROM purchases WHERE pay_type = $1
    UNION ALL SELECT entry_date, 0, amount FROM other_expenses WHERE pay_type = $1
    UNION ALL SELECT x.entry_date, 0, x.amount FROM settlements x JOIN parties p ON p.id = x.party_id WHERE p.kind = 'supplier' AND x.mode = $1
  ) t GROUP BY d ORDER BY d"""
PARTY_EVENTS = """
  SELECT t.party_id, p.name, t.d, SUM(t.i) AS i, SUM(t.o) AS o FROM (
    SELECT party_id, entry_date AS d, amount AS i, 0 AS o FROM sales WHERE party_id IS NOT NULL
    UNION ALL SELECT party_id, entry_date, amount, 0 FROM purchases WHERE party_id IS NOT NULL
    UNION ALL SELECT party_id, entry_date, 0, amount FROM settlements
  ) t JOIN parties p ON p.id = t.party_id GROUP BY t.party_id, p.name, t.d ORDER BY t.party_id, t.d"""


def assert_balances(c):
    for mode in ('cash', 'bank'):
        run = 0.0
        for r in c.query(MONEY_EVENTS, [mode]):
            run = r2(r2(run + float(r['i'])) - float(r['o']))
            if run < 0:
                raise bad('NEG_CASH' if mode == 'cash' else 'NEG_BANK', 'Not enough %s balance' % mode, date=r['d'], short=r2(-run))
    cur, run = None, 0.0
    for r in c.query(PARTY_EVENTS):
        if r['party_id'] != cur:
            cur, run = r['party_id'], 0.0
        run = r2(r2(run + float(r['i'])) - float(r['o']))
        if run < 0:
            raise bad('NEG_PARTY', 'Party balance would go below zero', date=r['d'], party=r['name'], short=r2(-run))


# ---------- reports ----------
def money(c, mode, to=None):
    d = ' AND entry_date <= $2' if to else ''
    dx = ' AND x.entry_date <= $2' if to else ''
    p = [mode, to] if to else [mode]
    r = c.query("""SELECT
        (SELECT COALESCE(SUM(amount),0) FROM sales          WHERE pay_type = $1%s)
      + (SELECT COALESCE(SUM(amount),0) FROM other_income   WHERE pay_type = $1%s)
      - (SELECT COALESCE(SUM(amount),0) FROM purchases      WHERE pay_type = $1%s)
      - (SELECT COALESCE(SUM(amount),0) FROM other_expenses WHERE pay_type = $1%s)
      + (SELECT COALESCE(SUM(CASE WHEN p.kind = 'customer' THEN x.amount ELSE -x.amount END),0)
           FROM settlements x JOIN parties p ON p.id = x.party_id WHERE x.mode = $1%s) AS v""" % (d, d, d, d, dx), p)
    return r2(r[0]['v'])


def party_bal_sql(to=None):
    d = ' AND entry_date <= $1' if to else ''
    return """SELECT p.id, p.name, p.kind,
        COALESCE(CASE WHEN p.kind = 'customer' THEN (SELECT SUM(amount) FROM sales WHERE party_id = p.id%s)
                      ELSE (SELECT SUM(amount) FROM purchases WHERE party_id = p.id%s) END, 0)
      - COALESCE((SELECT SUM(amount) FROM settlements WHERE party_id = p.id%s), 0) AS balance
      FROM parties p""" % (d, d, d)


def range_sql(frm, to, col='entry_date'):
    w, p = [], []
    if frm:
        p.append(frm)
        w.append('%s >= $%d' % (col, len(p)))
    if to:
        p.append(to)
        w.append('%s <= $%d' % (col, len(p)))
    return (' WHERE ' + ' AND '.join(w)) if w else '', p


def read_range(q):
    frm, to = str(q.get('from') or ''), str(q.get('to') or '')
    if (frm and not is_date(frm)) or (to and not is_date(to)):
        raise bad('BAD_DATE', 'Choose a valid date')
    if frm and to and frm > to:
        raise bad('BAD_RANGE', 'From date is after the To date')
    return frm, to


# ---------- parties / entries ----------
def resolve_party(c, k, b):
    pid = b.get('partyId')
    if pid and pid != '__new':
        p = c.query('SELECT id FROM parties WHERE id = $1 AND kind = $2', [pid, k['party']])
        if not p:
            raise bad('PARTY', 'Select the party name')
        return p[0]['id']
    pn = s(b.get('partyNew'), 100)
    if not pn:
        raise bad('PARTY', 'Select or type the party name')
    ex = c.query('SELECT id FROM parties WHERE kind = $1 AND name_key = $2', [k['party'], name_key(pn)])
    if ex:
        return ex[0]['id']
    nid = uid()
    c.execute('INSERT INTO parties (id, kind, name, name_key, created_at) VALUES ($1,$2,$3,$4,$5)', [nid, k['party'], pn, name_key(pn), now_ms()])
    return nid


def save_entry(sdbh, k, b, entry_id):
    """add (entry_id None) or edit one entry, then re-check all balances"""
    name, amount, typ, date = s(b.get('name'), 150), r2(b.get('amount')), str(b.get('type') or ''), check_date(b.get('date'))
    if not name:
        raise bad('NAME', 'Please fill in the name')
    if not amount > 0:
        raise bad('AMOUNT', 'Enter the amount')
    if typ not in (('cash', 'bank', 'udhar') if k['udhar'] else ('cash', 'bank')):
        raise bad('TYPE', 'Choose cash, bank or udhar')
    new_id = entry_id or uid()
    with sdbh.tx() as c:
        party_id = resolve_party(c, k, b) if typ == 'udhar' else None
        if entry_id:
            if k['udhar']:
                n = c.execute('UPDATE %s SET entry_date = $1, %s = $2, description = $3, pay_type = $4, amount = $5, party_id = $6 WHERE id = $7' % (k['table'], k['name']),
                              [date, name, s(b.get('desc'), 200), typ, amount, party_id, entry_id])
            else:
                n = c.execute('UPDATE %s SET entry_date = $1, %s = $2, pay_type = $3, amount = $4 WHERE id = $5' % (k['table'], k['name']), [date, name, typ, amount, entry_id])
            if not n:
                raise not_found()
        elif k['udhar']:
            c.execute('INSERT INTO %s (id, entry_date, %s, description, pay_type, amount, party_id, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)' % (k['table'], k['name']),
                      [new_id, date, name, s(b.get('desc'), 200), typ, amount, party_id, now_ms()])
        else:
            c.execute('INSERT INTO %s (id, entry_date, %s, pay_type, amount, created_at) VALUES ($1,$2,$3,$4,$5,$6)' % (k['table'], k['name']),
                      [new_id, date, name, typ, amount, now_ms()])
        assert_balances(c)
    return new_id


def save_settlement(sdbh, b, sid):
    amount, mode, date = r2(b.get('amount')), str(b.get('mode') or ''), check_date(b.get('date'))
    if not amount > 0:
        raise bad('AMOUNT', 'Enter the amount')
    if mode not in ('cash', 'bank'):
        raise bad('TYPE', 'Choose cash or bank')
    new_id = sid or uid()
    with sdbh.tx() as c:
        p = c.query('SELECT id FROM parties WHERE id = $1', [b.get('partyId')])
        if not p:
            raise bad('PARTY', 'Select the party name')
        if sid:
            if not c.execute('UPDATE settlements SET entry_date = $1, party_id = $2, amount = $3, mode = $4 WHERE id = $5', [date, p[0]['id'], amount, mode, sid]):
                raise not_found()
        else:
            c.execute('INSERT INTO settlements (id, entry_date, party_id, amount, mode, created_at) VALUES ($1,$2,$3,$4,$5,$6)', [new_id, date, p[0]['id'], amount, mode, now_ms()])
        assert_balances(c)
    return new_id


# ---------- billing helpers ----------
def fee_of(shop, st):
    return float(shop['monthly_fee']) if float(shop['monthly_fee']) > 0 else float(st['monthly_fee'])


def ensure_bill(shop, st):
    if shop['status'] not in ('trial', 'suspended'):
        return
    if db.master.query("SELECT 1 FROM bills WHERE shop_id = $1 AND status = 'due'", [shop['id']]):
        return
    fee = fee_of(shop, st)
    if not fee > 0:
        return
    due = ymd(datetime.fromtimestamp(shop['trial_ends_at'] / 1000)) if shop['status'] == 'trial' else today()
    try:
        with db.master.tx() as c:
            logic.create_bill(c, shop['id'], fee, due, 'Monthly subscription', True, False)
    except Exception:
        pass            # already exists


# ---------- Excel sheets (names = form names, used again by the backup import) ----------
HEAD = {
    'Sale':           ['Date', 'Item', 'Description', 'Type', 'Party', 'Amount'],
    'Purchase':       ['Date', 'Item', 'Description', 'Type', 'Party', 'Amount'],
    'Other Income':   ['Date', 'Detail', 'Type', 'Amount'],
    'Other Expenses': ['Date', 'Expense Type', 'Type', 'Amount'],
    'Udhar Received': ['Date', 'Party', 'Type', 'Amount'],
    'Udhar Paid':     ['Date', 'Party', 'Type', 'Amount'],
}


def build_sheets(ctx, frm, to):
    sh, sheets, cnt = sdb(ctx), [], {}
    where, params = range_sql(frm, to, 't.entry_date')
    for k in ('sales', 'purchases'):
        c = KINDS[k]
        rows = sh.query('SELECT t.entry_date, t.item_name, t.description, t.pay_type, p.name AS party, t.amount FROM %s t LEFT JOIN parties p ON p.id = t.party_id%s ORDER BY t.entry_date, t.created_at' % (c['table'], where), params)
        sheets.append({'name': c['sheet'], 'rows': [HEAD[c['sheet']]] + [[r['entry_date'], r['item_name'], r['description'], TYPE_LABEL[r['pay_type']], r['party'] or '', float(r['amount'])] for r in rows]})
        cnt[c['sheet']] = len(rows)
    for k in ('income', 'expenses'):
        c = KINDS[k]
        rows = sh.query('SELECT t.entry_date, t.%s AS nm, t.pay_type, t.amount FROM %s t%s ORDER BY t.entry_date, t.created_at' % (c['name'], c['table'], where), params)
        sheets.append({'name': c['sheet'], 'rows': [HEAD[c['sheet']]] + [[r['entry_date'], r['nm'], TYPE_LABEL[r['pay_type']], float(r['amount'])] for r in rows]})
        cnt[c['sheet']] = len(rows)
    for sheet, kind in (('Udhar Received', 'customer'), ('Udhar Paid', 'supplier')):
        p, w = [kind], ''
        if frm:
            p.append(frm)
            w += ' AND x.entry_date >= $%d' % len(p)
        if to:
            p.append(to)
            w += ' AND x.entry_date <= $%d' % len(p)
        rows = sh.query('SELECT x.entry_date, p.name, x.mode, x.amount FROM settlements x JOIN parties p ON p.id = x.party_id WHERE p.kind = $1%s ORDER BY x.entry_date, x.created_at' % w, p)
        sheets.append({'name': sheet, 'rows': [HEAD[sheet]] + [[r['entry_date'], r['name'], TYPE_LABEL[r['mode']], float(r['amount'])] for r in rows]})
        cnt[sheet] = len(rows)
    stock = r2(sh.query('SELECT value FROM stock WHERE id = 1')[0]['value'])
    sheets.append({'name': 'Info', 'rows': [['Field', 'Value'], ['App', 'BIZKHATA'], ['Shop', ctx.shop['name']], ['Exported on', today()], ['From', frm or 'All'], ['To', to or 'All'], ['Stock value', stock],
                                            ['Note', 'To import this file again keep the sheet names and column headings unchanged.']]})
    return sheets, cnt


TYPE_WORDS = {'cash': 'cash', 'کیش': 'cash', 'bank': 'bank', 'بینک': 'bank', 'udhar': 'udhar', 'ادھار': 'udhar', 'credit': 'udhar'}


def to_date(v):
    if isinstance(v, (int, float)) and 20000 < v < 80000:
        from datetime import date, timedelta
        return ymd(date(1899, 12, 30) + timedelta(days=round(v)))
    t = str('' if v is None else v).strip()
    if is_date(t):
        return t
    m = re.fullmatch(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})', t)
    if m:
        x = '%s-%s-%s' % (m.group(3), m.group(2).zfill(2), m.group(1).zfill(2))
        if is_date(x):
            return x
    m = re.fullmatch(r'(\d{4})[/.](\d{1,2})[/.](\d{1,2})', t)
    if m:
        x = '%s-%s-%s' % (m.group(1), m.group(2).zfill(2), m.group(3).zfill(2))
        if is_date(x):
            return x
    return None


def parse_sheet(rows_all, sheet):
    want = HEAD[sheet]
    hdr = [str(x).strip().lower() for x in (rows_all[0] if rows_all else [])]
    idx = [hdr.index(h.lower()) if h.lower() in hdr else -1 for h in want]
    if any(i < 0 for i in idx):
        raise bad('BAD_FILE', 'Sheet "%s": column headings are not as exported' % sheet)
    out = []
    for i, r in enumerate(rows_all[1:]):
        if all(x == '' or x is None for x in r):
            continue
        row = {h: (r[idx[j]] if idx[j] < len(r) else '') for j, h in enumerate(want)}
        where = 'Sheet "%s" row %d' % (sheet, i + 2)
        date = to_date(row['Date'])
        if not date:
            raise bad('BAD_FILE', where + ': invalid date')
        if date > today():
            raise bad('BAD_FILE', where + ': date is in the future')
        amount = r2(row['Amount'])
        if not amount > 0:
            raise bad('BAD_FILE', where + ': invalid amount')
        typ = TYPE_WORDS.get(str(row['Type']).strip().lower())
        if not typ:
            raise bad('BAD_FILE', where + ': type must be Cash, Bank or Udhar')
        o = {'date': date, 'amount': amount, 'type': typ}
        if sheet in ('Sale', 'Purchase'):
            o['name'], o['desc'], o['party'] = s(row['Item'], 150), s(row['Description'], 200), s(row['Party'], 100)
            if not o['name']:
                raise bad('BAD_FILE', where + ': item name is empty')
            if (typ == 'udhar') != bool(o['party']):
                raise bad('BAD_FILE', where + ': Udhar rows need a Party (and Cash/Bank rows must not have one)')
        elif sheet in ('Other Income', 'Other Expenses'):
            o['name'] = s(row[want[1]], 150)
            if not o['name']:
                raise bad('BAD_FILE', where + ': name is empty')
            if typ == 'udhar':
                raise bad('BAD_FILE', where + ': type must be Cash or Bank')
        else:
            o['party'] = s(row['Party'], 100)
            if not o['party']:
                raise bad('BAD_FILE', where + ': party is empty')
            if typ == 'udhar':
                raise bad('BAD_FILE', where + ': type must be Cash or Bank')
        out.append(o)
    return out


# ======================================================================== routes
@api('/api/me', auth='shop', blocked_ok=True)
def me(ctx):
    st = logic.get_settings()
    bills = db.master.query("SELECT * FROM bills WHERE shop_id = $1 AND status = 'due' ORDER BY due_date", [ctx.shop['id']])
    first = bills[0] if bills else None
    return {
        'user': {'name': ctx.user['name'], 'mobile': ctx.user['mobile']}, 'shop': logic.shop_view(ctx.shop), 'blocked': ctx.blocked,
        'graceDays': st['grace_days'], 'support': st['support_whatsapp'],
        'bill': {'no': first['bill_no'], 'amount': float(first['amount']), 'due': first['due_date'], 'late': max(0, days_between(today(), first['due_date']))} if first else None,
    }


@api('/api/entries/<kind>', auth='shop')
def entries_list(ctx):
    k, sh = kind_of(ctx.params['kind']), sdb(ctx)
    if k['udhar']:
        sel = ("SELECT t.id, t.entry_date, t.%s AS name, t.description AS descr, t.pay_type AS type, t.amount, t.party_id, p.name AS party_name "
               "FROM %s t LEFT JOIN parties p ON p.id = t.party_id ORDER BY t.entry_date DESC, t.created_at DESC LIMIT 50") % (k['name'], k['table'])
    else:
        sel = ("SELECT t.id, t.entry_date, t.%s AS name, '' AS descr, t.pay_type AS type, t.amount, NULL AS party_id, NULL AS party_name "
               "FROM %s t ORDER BY t.entry_date DESC, t.created_at DESC LIMIT 50") % (k['name'], k['table'])
    rows = [{'id': r['id'], 'date': r['entry_date'], 'name': r['name'], 'desc': r['descr'], 'type': r['type'], 'amount': float(r['amount']),
             'partyId': r['party_id'], 'partyName': r['party_name']} for r in sh.query(sel)]
    td = sh.query('SELECT COALESCE(SUM(amount),0) AS v FROM %s WHERE entry_date = $1' % k['table'], [today()])[0]['v']
    parties = sh.query('SELECT id, name FROM parties WHERE kind = $1 ORDER BY name', [k['party']]) if k['udhar'] else []
    return {'rows': rows, 'today': r2(td), 'parties': parties}


@api('/api/entries/<kind>', ['POST'], auth='shop')
def entries_add(ctx):
    return {'ok': True, 'id': save_entry(sdb(ctx), kind_of(ctx.params['kind']), ctx.body, None)}


@api('/api/entries/<kind>/<eid>', ['PUT'], auth='shop')
def entries_edit(ctx):
    return {'ok': True, 'id': save_entry(sdb(ctx), kind_of(ctx.params['kind']), ctx.body, ctx.params['eid'])}


@api('/api/entries/<kind>/<eid>', ['DELETE'], auth='shop')
def entries_delete(ctx):
    k = kind_of(ctx.params['kind'])
    with sdb(ctx).tx() as c:
        if not c.execute('DELETE FROM %s WHERE id = $1' % k['table'], [ctx.params['eid']]):
            raise not_found()
        assert_balances(c)
    return {'ok': True}


# ---- udhar received (customers) / udhar paid (suppliers) ----
@api('/api/settlements', auth='shop')
def settle_list(ctx):
    kind = 'supplier' if ctx.query.get('kind') == 'supplier' else 'customer'
    sh = sdb(ctx)
    rows = [{'id': r['id'], 'date': r['entry_date'], 'partyId': r['party_id'], 'partyName': r['name'], 'mode': r['mode'], 'amount': float(r['amount'])}
            for r in sh.query("""SELECT x.id, x.entry_date, x.party_id, p.name, x.mode, x.amount FROM settlements x JOIN parties p ON p.id = x.party_id
                                 WHERE p.kind = $1 ORDER BY x.entry_date DESC, x.created_at DESC LIMIT 50""", [kind])]
    parties = [{'id': p['id'], 'name': p['name'], 'balance': r2(p['balance'])} for p in sh.query(party_bal_sql() + ' WHERE p.kind = $1 ORDER BY p.name', [kind])]
    return {'rows': rows, 'parties': parties, 'cash': money(sh, 'cash'), 'bank': money(sh, 'bank')}


@api('/api/settlements', ['POST'], auth='shop')
def settle_add(ctx):
    return {'ok': True, 'id': save_settlement(sdb(ctx), ctx.body, None)}


@api('/api/settlements/<sid>', ['PUT'], auth='shop')
def settle_edit(ctx):
    return {'ok': True, 'id': save_settlement(sdb(ctx), ctx.body, ctx.params['sid'])}


@api('/api/settlements/<sid>', ['DELETE'], auth='shop')
def settle_delete(ctx):
    with sdb(ctx).tx() as c:
        if not c.execute('DELETE FROM settlements WHERE id = $1', [ctx.params['sid']]):
            raise not_found()
        assert_balances(c)
    return {'ok': True}


# ---- report: date filter (P/L for from..to, balances as on the To date) ----
@api('/api/report', auth='shop')
def report(ctx):
    sh = sdb(ctx)
    frm, to = read_range(ctx.query)
    where, params = range_sql(frm, to)

    def total(t):
        return r2(sh.query('SELECT COALESCE(SUM(amount),0) AS v FROM %s%s' % (t, where), params)[0]['v'])

    sales, purch, oi, oe = total('sales'), total('purchases'), total('other_income'), total('other_expenses')
    stock = r2(sh.query('SELECT value FROM stock WHERE id = 1')[0]['value'])
    parties = [{'id': p['id'], 'name': p['name'], 'kind': p['kind'], 'balance': r2(p['balance'])}
               for p in sh.query(party_bal_sql(to) + ' ORDER BY p.name', [to] if to else [])]
    customers = sorted([p for p in parties if p['kind'] == 'customer'], key=lambda p: -p['balance'])
    suppliers = sorted([p for p in parties if p['kind'] == 'supplier'], key=lambda p: -p['balance'])
    gross = r2(sales - purch + stock)
    return {
        'from': frm, 'to': to, 'cash': money(sh, 'cash', to or None), 'bank': money(sh, 'bank', to or None),
        'receivable': r2(sum(p['balance'] for p in customers)), 'payable': r2(sum(p['balance'] for p in suppliers)),
        'stock': stock, 'pl': {'sales': sales, 'purchases': purch, 'stock': stock, 'gross': gross, 'otherIncome': oi, 'otherExpenses': oe, 'net': r2(gross + oi - oe)},
        'customers': customers, 'suppliers': suppliers,
    }


@api('/api/stock', ['PUT'], auth='shop')
def stock_set(ctx):
    v = max(0.0, r2(ctx.body.get('value')))
    sdb(ctx).execute('UPDATE stock SET value = $1, updated_at = $2 WHERE id = 1', [v, now_ms()])
    return {'ok': True, 'value': v}


@api('/api/party/<pid>', auth='shop')
def party_statement(ctx):
    sh = sdb(ctx)
    rows = sh.query(party_bal_sql() + ' WHERE p.id = $1', [ctx.params['pid']])
    if not rows:
        raise HttpError(404, 'NOT_FOUND', 'Party not found')
    p = rows[0]
    tbl = 'sales' if p['kind'] == 'customer' else 'purchases'
    given = [{'date': r['entry_date'], 'name': r['name'], 'amount': float(r['amount']), 'at': r['created_at'], 'settle': False}
             for r in sh.query('SELECT entry_date, item_name AS name, amount, created_at FROM %s WHERE party_id = $1' % tbl, [p['id']])]
    paid = [{'date': r['entry_date'], 'name': '', 'amount': float(r['amount']), 'at': r['created_at'], 'settle': True}
            for r in sh.query('SELECT entry_date, amount, created_at FROM settlements WHERE party_id = $1', [p['id']])]
    lines = sorted(given + paid, key=lambda x: (x['date'], x['at']), reverse=True)
    return {'party': {'id': p['id'], 'name': p['name'], 'kind': p['kind']}, 'balance': r2(p['balance']), 'lines': lines}


# ---- Excel export (Report) and backup export / import ----
@api('/api/export', auth='shop')
def export(ctx):
    frm, to = read_range(ctx.query)
    sheets, cnt = build_sheets(ctx, frm, to)
    safe = re.sub(r'[^A-Za-z0-9]+', '_', ctx.shop['name']).strip('_')[:30] or 'shop'
    backup = bool(ctx.query.get('backup'))
    logic.log_act(db.master, ctx.shop['id'], ctx.user['mobile'], 'Backup exported' if backup else 'Excel exported', '%s to %s' % (frm or 'All', to or 'All'))
    return {'filename': 'BIZKHATA_%s_%s_%s.xlsx' % ('Backup' if backup else 'Entries', safe, today()),
            'data': base64.b64encode(xlsx.write_xlsx(sheets)).decode(), 'counts': cnt}


@api('/api/import', ['POST'], auth='shop')
def import_backup(ctx):
    sh = sdb(ctx)
    try:
        book = xlsx.read_xlsx(base64.b64decode(str(ctx.body.get('file') or '')))
    except Exception:
        raise bad('BAD_FILE', 'This is not a valid Excel (.xlsx) file')
    info = book.get('Info')
    if info:
        app = next((r for r in info if r and str(r[0]).strip().lower() == 'app'), None)
        if app and (len(app) < 2 or str(app[1]).strip().upper() != 'BIZKHATA'):
            raise bad('BAD_FILE', 'This file was not exported from BIZKHATA')
    if not any(n in book for n in HEAD):
        raise bad('BAD_FILE', 'No BIZKHATA sheets found in this file')
    data = {n: (parse_sheet(book[n], n) if n in book else []) for n in HEAD}
    stock = None
    if info:
        r = next((x for x in info if x and str(x[0]).strip().lower() == 'stock value'), None)
        if r and len(r) > 1:
            try:
                if float(r[1]) >= 0:
                    stock = r2(r[1])
            except (TypeError, ValueError):
                pass
    total = sum(len(v) for v in data.values())
    if not total:
        raise bad('BAD_FILE', 'The file has no entries')

    with sh.tx() as c:
        for t in ('settlements', 'sales', 'purchases', 'other_income', 'other_expenses', 'parties'):
            c.execute('DELETE FROM ' + t)
        pmap, seq = {}, [now_ms()]

        def nxt():
            seq[0] += 1
            return seq[0]

        def party(kind, name):
            key = kind + '|' + name_key(name)
            if key not in pmap:
                pid = uid()
                pmap[key] = pid
                c.execute('INSERT INTO parties (id, kind, name, name_key, created_at) VALUES ($1,$2,$3,$4,$5)', [pid, kind, name, name_key(name), nxt()])
            return pmap[key]

        for sheet, table, kind in (('Sale', 'sales', 'customer'), ('Purchase', 'purchases', 'supplier')):
            for r in data[sheet]:
                c.execute('INSERT INTO %s (id, entry_date, item_name, description, pay_type, amount, party_id, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)' % table,
                          [uid(), r['date'], r['name'], r['desc'], r['type'], r['amount'], party(kind, r['party']) if r['type'] == 'udhar' else None, nxt()])
        for r in data['Other Income']:
            c.execute('INSERT INTO other_income (id, entry_date, detail, pay_type, amount, created_at) VALUES ($1,$2,$3,$4,$5,$6)', [uid(), r['date'], r['name'], r['type'], r['amount'], nxt()])
        for r in data['Other Expenses']:
            c.execute('INSERT INTO other_expenses (id, entry_date, expense_type, pay_type, amount, created_at) VALUES ($1,$2,$3,$4,$5,$6)', [uid(), r['date'], r['name'], r['type'], r['amount'], nxt()])
        for sheet, kind in (('Udhar Received', 'customer'), ('Udhar Paid', 'supplier')):
            for r in data[sheet]:
                c.execute('INSERT INTO settlements (id, entry_date, party_id, amount, mode, created_at) VALUES ($1,$2,$3,$4,$5,$6)', [uid(), r['date'], party(kind, r['party']), r['amount'], r['type'], nxt()])
        if stock is not None:
            c.execute('UPDATE stock SET value = $1, updated_at = $2 WHERE id = 1', [stock, now_ms()])
        assert_balances(c)               # a backup that would give a negative balance is refused, nothing changes
    logic.log_act(db.master, ctx.shop['id'], ctx.user['mobile'], 'Backup imported', '%d entries' % total)
    return {'ok': True, 'total': total, 'counts': {k: len(v) for k, v in data.items()}}


# ---- billing (also open while the shop is blocked) ----
@api('/api/billing', auth='shop', blocked_ok=True)
def billing(ctx):
    st, shop = logic.get_settings(), ctx.shop
    ensure_bill(shop, st)
    bills = db.master.query('SELECT * FROM bills WHERE shop_id = $1 ORDER BY due_date DESC LIMIT 24', [shop['id']])
    reqs = db.master.query('SELECT bill_id, status FROM payment_requests WHERE shop_id = $1 ORDER BY created_at DESC LIMIT 20', [shop['id']])
    pending = {r['bill_id'] for r in reqs if r['status'] == 'pending'}
    rejected = {r['bill_id'] for r in reqs if r['status'] == 'rejected'}
    return {
        'shop': logic.shop_view(shop), 'blocked': ctx.blocked, 'fee': fee_of(shop, st), 'bank': st['bank_details'], 'support': st['support_whatsapp'], 'graceDays': st['grace_days'],
        'bills': [{'id': b['id'], 'no': b['bill_no'], 'amount': float(b['amount']), 'due': b['due_date'], 'status': b['status'], 'note': b['note'],
                   'late': max(0, days_between(today(), b['due_date'])) if b['status'] == 'due' else 0,
                   'pending': b['id'] in pending, 'rejected': b['id'] not in pending and b['id'] in rejected and b['status'] == 'due'} for b in bills],
    }


@api('/api/billing/pay', ['POST'], auth='shop', blocked_ok=True)
def billing_pay(ctx):
    slip = str(ctx.body.get('slip') or '')
    if not re.fullmatch(r'data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+', slip) or len(slip) > 4_000_000:
        raise bad('SLIP', 'Please upload the bank slip image')
    rows = db.master.query("SELECT * FROM bills WHERE id = $1 AND shop_id = $2 AND status = 'due'", [str(ctx.body.get('billId') or ''), ctx.shop['id']])
    if not rows:
        raise bad('NO_BILL', 'This bill is not pending')
    bill = rows[0]
    if db.master.query("SELECT 1 FROM payment_requests WHERE bill_id = $1 AND status = 'pending'", [bill['id']]):
        raise bad('PENDING', 'Your payment is already with the admin')
    with db.master.tx() as c:
        c.execute("INSERT INTO payment_requests (id, shop_id, bill_id, amount, slip, status, created_at) VALUES ($1,$2,$3,$4,$5,'pending',$6)",
                  [uid(), ctx.shop['id'], bill['id'], bill['amount'], slip, now_ms()])
        logic.log_act(c, ctx.shop['id'], ctx.user['mobile'], 'Payment slip sent', '%s %s' % (bill['bill_no'], bill['amount']))
    return {'ok': True}


# ---- delete my account (required by Google Play): removes the shop, its user, bills and its separate database ----
@api('/api/account/delete', ['POST'], auth='shop', blocked_ok=True)
def account_delete(ctx):
    if not sec.verify_password(str(ctx.body.get('password') or ''), ctx.user['password_hash']):
        raise HttpError(401, 'BAD_LOGIN', 'Password is not correct')
    db.master.execute('DELETE FROM shops WHERE id = $1', [ctx.shop['id']])       # users, bills, slips, requests and log go with it
    db.drop_shop_db(ctx.shop['db_name'])
    return {'ok': True}

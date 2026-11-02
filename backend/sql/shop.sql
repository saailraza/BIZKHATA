-- BIZKHATA per-shop database. Every shop gets its OWN copy of these tables in its OWN database,
-- so one shop's data can never be mixed with another's.
-- Portable SQL: runs unchanged on PostgreSQL and on SQLite.
CREATE TABLE IF NOT EXISTS parties (
  id         TEXT PRIMARY KEY,
  kind       TEXT NOT NULL CHECK (kind IN ('customer','supplier')),
  name       TEXT NOT NULL,
  name_key   TEXT NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE (kind, name_key)
);

CREATE TABLE IF NOT EXISTS sales (
  id          TEXT PRIMARY KEY,
  entry_date  TEXT NOT NULL,
  item_name   TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  pay_type    TEXT NOT NULL CHECK (pay_type IN ('cash','bank','udhar')),
  amount      NUMERIC(14,2) NOT NULL CHECK (amount > 0),
  party_id    TEXT REFERENCES parties(id),
  created_at  BIGINT NOT NULL,
  CHECK ((pay_type = 'udhar') = (party_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS purchases (
  id          TEXT PRIMARY KEY,
  entry_date  TEXT NOT NULL,
  item_name   TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  pay_type    TEXT NOT NULL CHECK (pay_type IN ('cash','bank','udhar')),
  amount      NUMERIC(14,2) NOT NULL CHECK (amount > 0),
  party_id    TEXT REFERENCES parties(id),
  created_at  BIGINT NOT NULL,
  CHECK ((pay_type = 'udhar') = (party_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS other_income (
  id         TEXT PRIMARY KEY,
  entry_date TEXT NOT NULL,
  detail     TEXT NOT NULL,
  pay_type   TEXT NOT NULL CHECK (pay_type IN ('cash','bank')),
  amount     NUMERIC(14,2) NOT NULL CHECK (amount > 0),
  created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS other_expenses (
  id           TEXT PRIMARY KEY,
  entry_date   TEXT NOT NULL,
  expense_type TEXT NOT NULL,
  pay_type     TEXT NOT NULL CHECK (pay_type IN ('cash','bank')),
  amount       NUMERIC(14,2) NOT NULL CHECK (amount > 0),
  created_at   BIGINT NOT NULL
);

-- Udhar settlements: customer = money received, supplier = money paid
CREATE TABLE IF NOT EXISTS settlements (
  id         TEXT PRIMARY KEY,
  entry_date TEXT NOT NULL,
  party_id   TEXT NOT NULL REFERENCES parties(id),
  amount     NUMERIC(14,2) NOT NULL CHECK (amount > 0),
  mode       TEXT NOT NULL CHECK (mode IN ('cash','bank')),
  created_at BIGINT NOT NULL
);

-- The single "available stock" figure used in profit / loss
CREATE TABLE IF NOT EXISTS stock (
  id         INTEGER PRIMARY KEY CHECK (id = 1),
  value      NUMERIC(14,2) NOT NULL DEFAULT 0,
  updated_at BIGINT NOT NULL DEFAULT 0
);
INSERT INTO stock (id, value, updated_at) VALUES (1, 0, 0) ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS sales_date_ix     ON sales (entry_date);
CREATE INDEX IF NOT EXISTS purchases_date_ix ON purchases (entry_date);
CREATE INDEX IF NOT EXISTS income_date_ix    ON other_income (entry_date);
CREATE INDEX IF NOT EXISTS expenses_date_ix  ON other_expenses (entry_date);
CREATE INDEX IF NOT EXISTS settle_party_ix   ON settlements (party_id);
CREATE INDEX IF NOT EXISTS sales_party_ix    ON sales (party_id);
CREATE INDEX IF NOT EXISTS purch_party_ix    ON purchases (party_id);

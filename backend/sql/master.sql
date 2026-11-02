-- BIZKHATA master database: admins, shop list, users, billing, requests.
-- Portable SQL: runs unchanged on PostgreSQL and on SQLite.
CREATE TABLE IF NOT EXISTS app_settings (
  id                INTEGER PRIMARY KEY CHECK (id = 1),
  monthly_fee       NUMERIC(12,2) NOT NULL DEFAULT 999,
  bank_details      TEXT NOT NULL DEFAULT '',
  support_whatsapp  TEXT NOT NULL DEFAULT '',
  trial_days        INTEGER NOT NULL DEFAULT 7,
  grace_days        INTEGER NOT NULL DEFAULT 5,
  bill_advance_days INTEGER NOT NULL DEFAULT 7
);
INSERT INTO app_settings (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS counters (
  name  TEXT PRIMARY KEY,
  value BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS admins (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  login_id      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at    BIGINT NOT NULL
);

-- One row per shop. db_name = the shop's own separate database.
CREATE TABLE IF NOT EXISTS shops (
  id             TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  owner_name     TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'trial'
                 CHECK (status IN ('pending','trial','partial','full','suspended','rejected')),
  registered_at  BIGINT NOT NULL,
  trial_ends_at  BIGINT NOT NULL,
  auto_suspended INTEGER NOT NULL DEFAULT 0,
  monthly_fee    NUMERIC(12,2) NOT NULL DEFAULT 0,
  next_due_date  TEXT,
  db_name        TEXT NOT NULL UNIQUE
);

-- Exactly one user per shop. Mobile number is the username and is unique everywhere.
CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  shop_id       TEXT NOT NULL UNIQUE REFERENCES shops(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  mobile        TEXT NOT NULL UNIQUE CHECK (length(mobile) = 11 AND substr(mobile, 1, 2) = '03'),
  password_hash TEXT NOT NULL,
  active        INTEGER NOT NULL DEFAULT 1,
  created_at    BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS bills (
  id         TEXT PRIMARY KEY,
  shop_id    TEXT NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
  bill_no    TEXT NOT NULL UNIQUE,
  amount     NUMERIC(12,2) NOT NULL CHECK (amount > 0),
  issue_date TEXT NOT NULL,
  due_date   TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'due' CHECK (status IN ('due','paid')),
  paid_at    BIGINT,
  note       TEXT NOT NULL DEFAULT 'Monthly subscription',
  is_monthly INTEGER NOT NULL DEFAULT 1,
  is_auto    INTEGER NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS bills_one_monthly ON bills (shop_id, due_date) WHERE is_monthly = 1;
CREATE INDEX IF NOT EXISTS bills_status_ix ON bills (status, due_date);

-- Bank slip uploaded by the shopkeeper (image stored as a data URL)
CREATE TABLE IF NOT EXISTS payment_requests (
  id          TEXT PRIMARY KEY,
  shop_id     TEXT NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
  bill_id     TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  amount      NUMERIC(12,2) NOT NULL,
  slip        TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  created_at  BIGINT NOT NULL,
  resolved_at BIGINT
);
CREATE INDEX IF NOT EXISTS payment_requests_ix ON payment_requests (status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS payment_requests_one_pending ON payment_requests (bill_id) WHERE status = 'pending';

-- "Forgot password": becomes active only after the admin approves
CREATE TABLE IF NOT EXISTS password_reset_requests (
  id                TEXT PRIMARY KEY,
  user_id           TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  shop_id           TEXT NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
  new_password_hash TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  created_at        BIGINT NOT NULL,
  resolved_at       BIGINT
);
CREATE INDEX IF NOT EXISTS password_reset_ix ON password_reset_requests (status, created_at);

CREATE TABLE IF NOT EXISTS activity_log (
  id         TEXT PRIMARY KEY,
  shop_id    TEXT REFERENCES shops(id) ON DELETE CASCADE,
  actor      TEXT NOT NULL,
  action     TEXT NOT NULL,
  detail     TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS activity_log_ix ON activity_log (shop_id, created_at);

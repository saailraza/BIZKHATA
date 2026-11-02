"""
Database layer.

  DB_ENGINE=postgres  (live)   one MASTER database  +  one SEPARATE DATABASE for every shop (bk_<shop id>)
                               SHOP_ISOLATION=schema  -> for hosts that do not allow CREATE DATABASE:
                               every shop then gets its own SCHEMA (bk_<shop id>) inside the master database
  DB_ENGINE=sqlite    (test)   one master file + one separate file for every shop

All SQL in the project uses $1, $2 ... placeholders; this module converts them for the driver.
"""
import contextlib
import re
import sqlite3
import threading
import time
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from . import config

ENGINE = config.get('DB_ENGINE', 'postgres').lower()
ISOLATION = config.get('SHOP_ISOLATION', 'database').lower()
SQL_DIR = config.ROOT / 'sql'
MAX_OPEN_SHOPS = int(config.get('MAX_OPEN_SHOPS', '10'))

_PARAM = re.compile(r'\$(\d+)')
_NAME = re.compile(r'^[a-z0-9_]{3,63}$')


def read_sql(name):
    return (SQL_DIR / name).read_text(encoding='utf-8')


def _safe(name):
    if not _NAME.match(name):
        raise ValueError('bad database name')
    return name


def _q(ident):
    return '"' + str(ident).replace('"', '""') + '"'


# ===================================================================== PostgreSQL
class PgTx:
    def __init__(self, cur):
        self.cur = cur

    @staticmethod
    def _conv(sql, params):
        sql = sql.replace('%', '%%')
        return _PARAM.sub(lambda m: '%(p' + m.group(1) + ')s', sql), {'p%d' % (i + 1): v for i, v in enumerate(params)}

    def query(self, sql, params=()):
        q, p = self._conv(sql, params)
        self.cur.execute(q, p)
        return list(self.cur.fetchall()) if self.cur.description else []

    def execute(self, sql, params=()):
        q, p = self._conv(sql, params)
        self.cur.execute(q, p)
        return self.cur.rowcount


class PgDB:
    def __init__(self, pool, schema=None, owns_pool=True):
        self.pool, self.schema, self.owns_pool = pool, schema, owns_pool

    @contextlib.contextmanager
    def tx(self):
        from psycopg2.extras import RealDictCursor
        conn = self.pool.getconn()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            if self.schema:
                cur.execute('SET LOCAL search_path TO %s, public' % _q(self.schema))
            yield PgTx(cur)
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self.pool.putconn(conn)

    def query(self, sql, params=()):
        with self.tx() as t:
            return t.query(sql, params)

    def execute(self, sql, params=()):
        with self.tx() as t:
            return t.execute(sql, params)

    def script(self, sql):
        """run several statements that have no parameters (the CREATE TABLE files)"""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            if self.schema:
                cur.execute('SET LOCAL search_path TO %s, public' % _q(self.schema))
            cur.execute(sql)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            self.pool.putconn(conn)

    def close(self):
        if self.owns_pool:
            try:
                self.pool.closeall()
            except Exception:
                pass


class PgEngine:
    def __init__(self):
        import psycopg2
        import psycopg2.extensions
        import psycopg2.pool
        self.pg, self.pool_mod = psycopg2, psycopg2.pool
        # numeric -> float (not Decimal)
        dec = psycopg2.extensions.new_type(psycopg2.extensions.DECIMAL.values, 'DEC2FLOAT', lambda v, c: float(v) if v is not None else None)
        psycopg2.extensions.register_type(dec)
        # Render / Heroku often give postgres:// — psycopg2 wants postgresql://
        self.url = config.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/bizkhata_master')
        if self.url.startswith('postgres://'):
            self.url = 'postgresql://' + self.url[len('postgres://'):]
        self.master_name = unquote(urlsplit(self.url).path.lstrip('/')) or 'bizkhata_master'

    def url_for(self, dbname):
        u = urlsplit(self.url)
        return urlunsplit((u.scheme, u.netloc, '/' + quote(dbname), u.query, ''))

    def _pool(self, dbname, maxconn):
        return self.pool_mod.ThreadedConnectionPool(1, maxconn, self.url_for(dbname))

    def _admin(self):
        conn = self.pg.connect(self.url_for('postgres'))
        conn.autocommit = True
        return conn

    def _db_exists(self, cur, name):
        cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (name,))
        return cur.fetchone() is not None

    def open_master(self):
        try:
            pool = self._pool(self.master_name, int(config.get('DB_POOL_MASTER', '6')))
        except self.pg.OperationalError:
            # the master database does not exist yet: create it (needs the CREATEDB right)
            conn = self._admin()
            try:
                cur = conn.cursor()
                if not self._db_exists(cur, self.master_name):
                    cur.execute('CREATE DATABASE ' + _q(_safe(self.master_name)))
            finally:
                conn.close()
            pool = self._pool(self.master_name, int(config.get('DB_POOL_MASTER', '6')))
        db = PgDB(pool)
        db.script(read_sql('master.sql'))
        return db

    def create_shop(self, name, master):
        _safe(name)
        if ISOLATION == 'schema':
            master.script('CREATE SCHEMA IF NOT EXISTS ' + _q(name))
            return
        last = None
        for i in range(1, 5):           # CREATE DATABASE can briefly clash when two shops register at once
            try:
                conn = self._admin()
                try:
                    cur = conn.cursor()
                    if not self._db_exists(cur, name):
                        cur.execute('CREATE DATABASE ' + _q(name))
                finally:
                    conn.close()
                return
            except Exception as e:
                last = e
                time.sleep(0.3 * i)
        raise last

    def open_shop(self, name, master):
        _safe(name)
        if ISOLATION == 'schema':
            return PgDB(master.pool, schema=name, owns_pool=False)
        return PgDB(self._pool(name, int(config.get('DB_POOL_SHOP', '2'))))

    def drop_shop(self, name, master):
        _safe(name)
        if ISOLATION == 'schema':
            master.script('DROP SCHEMA IF EXISTS ' + _q(name) + ' CASCADE')
            return
        conn = self._admin()
        try:
            cur = conn.cursor()
            try:
                cur.execute('DROP DATABASE IF EXISTS ' + _q(name) + ' WITH (FORCE)')
            except self.pg.Error:       # PostgreSQL older than 13
                cur.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s', (name,))
                cur.execute('DROP DATABASE IF EXISTS ' + _q(name))
        finally:
            conn.close()


# ===================================================================== SQLite (testing)
def _dict_factory(cur, row):
    return {d[0]: row[i] for i, d in enumerate(cur.description)}


class SqliteTx:
    def __init__(self, conn):
        self.conn = conn

    def query(self, sql, params=()):
        cur = self.conn.execute(_PARAM.sub(r'?\1', sql), tuple(params))
        return cur.fetchall() if cur.description else []

    def execute(self, sql, params=()):
        return self.conn.execute(_PARAM.sub(r'?\1', sql), tuple(params)).rowcount


class SqliteDB:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = _dict_factory
        self.conn.execute('PRAGMA journal_mode = WAL')
        self.conn.execute('PRAGMA foreign_keys = ON')
        self.lock = threading.RLock()
        self.path = path

    @contextlib.contextmanager
    def tx(self):
        with self.lock:
            self.conn.execute('BEGIN')
            try:
                yield SqliteTx(self.conn)
                self.conn.execute('COMMIT')
            except BaseException:
                try:
                    self.conn.execute('ROLLBACK')
                except Exception:
                    pass
                raise

    def query(self, sql, params=()):
        with self.tx() as t:
            return t.query(sql, params)

    def execute(self, sql, params=()):
        with self.tx() as t:
            return t.execute(sql, params)

    def script(self, sql):
        with self.lock:
            self.conn.executescript(sql)

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


class SqliteEngine:
    def _file(self, name):
        return config.data_dir() / 'shops' / (_safe(name) + '.db')

    def open_master(self):
        db = SqliteDB(config.data_dir() / 'master.db')
        db.script(read_sql('master.sql'))
        return db

    def create_shop(self, name, master):
        SqliteDB(self._file(name)).close()

    def open_shop(self, name, master):
        return SqliteDB(self._file(name))

    def drop_shop(self, name, master):
        f = self._file(name)
        for ext in ('', '-wal', '-shm'):
            try:
                (f.parent / (f.name + ext)).unlink()
            except FileNotFoundError:
                pass


# ===================================================================== public API
_engine = None
_master = None
_lock = threading.RLock()
_shops = {}          # name -> [db, last_used]
_schema_ready = set()


def _eng():
    global _engine
    if _engine is None:
        _engine = SqliteEngine() if ENGINE == 'sqlite' else PgEngine()
    return _engine


class _MasterProxy:
    """`db.master.query(...)` works anywhere after init_master()"""
    def __getattr__(self, item):
        if _master is None:
            raise RuntimeError('database not initialised')
        return getattr(_master, item)


master = _MasterProxy()


def init_master():
    global _master
    with _lock:
        if _master is None:
            _master = _eng().open_master()
    return _master


def shop_db(name):
    with _lock:
        e = _shops.get(name)
        if e is None:
            db = _eng().open_shop(name, _master)
            if name not in _schema_ready:
                db.script(read_sql('shop.sql'))
                _schema_ready.add(name)
            e = _shops[name] = [db, time.time()]
            if len(_shops) > MAX_OPEN_SHOPS:          # close the least recently used shop connections
                old = min((k for k in _shops if k != name), key=lambda k: _shops[k][1], default=None)
                if old:
                    _shops.pop(old)[0].close()
        e[1] = time.time()
        return e[0]


def create_shop_db(name):
    with _lock:
        _eng().create_shop(name, _master)
    return shop_db(name)


def drop_shop_db(name):
    with _lock:
        e = _shops.pop(name, None)
        if e:
            e[0].close()
        _schema_ready.discard(name)
        _eng().drop_shop(name, _master)


def close_all():
    global _master
    with _lock:
        for e in _shops.values():
            e[0].close()
        _shops.clear()
        if _master is not None:
            _master.close()
            _master = None

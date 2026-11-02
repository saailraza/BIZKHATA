"""python scripts/setup_db.py   ->  creates the master database + tables + first admin, then exits."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bizkhata import db  # noqa: E402
from bizkhata.app import ensure_first_admin  # noqa: E402

try:
    db.init_master()
    ensure_first_admin()
    print('Setup finished (%s).' % db.ENGINE)
except Exception as e:
    print('Setup failed:', e)
    print('Check that PostgreSQL is running, DATABASE_URL in .env is correct and the user may create databases (ALTER USER <user> CREATEDB;)')
    sys.exit(1)
finally:
    db.close_all()

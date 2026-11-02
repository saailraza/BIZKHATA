"""Optional: run from cron every 10 minutes  (*/10 * * * * python /path/scripts/cron_tick.py)
The app already does this by itself while it is being used; cron keeps it exact when nobody is online."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bizkhata import db, logic  # noqa: E402

db.init_master()
print('blocked:', logic.refresh_statuses(), ' bills created:', logic.generate_bills())
db.close_all()

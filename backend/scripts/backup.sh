#!/bin/sh
# Nightly backup of the master database AND every shop database.
# crontab -e   ->   30 2 * * * /opt/bizkhata/scripts/backup.sh
# Needs a ~/.pgpass file (or PGPASSWORD) for the database user.
set -e
DEST=${BACKUP_DIR:-/var/backups/bizkhata}
USER=${PGUSER:-bizkhata}
HOST=${PGHOST:-localhost}
KEEP_DAYS=${KEEP_DAYS:-14}
STAMP=$(date +%F)
mkdir -p "$DEST/$STAMP"
for DB in $(psql -h "$HOST" -U "$USER" -At -d postgres -c "SELECT datname FROM pg_database WHERE datname = 'bizkhata_master' OR datname LIKE 'bk\_%'"); do
  pg_dump -h "$HOST" -U "$USER" -Fc "$DB" > "$DEST/$STAMP/$DB.dump"
done
find "$DEST" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +
echo "Backup finished: $DEST/$STAMP"
# restore one database:  createdb NAME && pg_restore -d NAME NAME.dump

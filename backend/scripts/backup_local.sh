#!/bin/sh
# Nightly backup run by root on the same server: master database + EVERY shop database, 14 days kept.
set -e
DEST=${BACKUP_DIR:-/var/backups/bizkhata}
KEEP_DAYS=${KEEP_DAYS:-14}
STAMP=$(date +%F)
mkdir -p "$DEST/$STAMP"
chmod 700 "$DEST"
for DB in $(sudo -u postgres psql -At -c "SELECT datname FROM pg_database WHERE datname = 'bizkhata_master' OR datname LIKE 'bk\_%'"); do
  sudo -u postgres pg_dump -Fc "$DB" > "$DEST/$STAMP/$DB.dump"
done
find "$DEST" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +
echo "$(date) backup finished: $DEST/$STAMP"
# restore one shop:   sudo -u postgres createdb NAME && sudo -u postgres pg_restore -d NAME NAME.dump

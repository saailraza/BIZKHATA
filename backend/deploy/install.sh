#!/usr/bin/env bash
# =====================================================================
#  BIZKHATA one-command installer for a fresh Ubuntu 22.04 / 24.04 server (Hostinger VPS etc.)
#
#    sudo bash deploy/install.sh  khata.bizeasesolutions.online  you@example.com
#
#  It installs PostgreSQL + Nginx + Python, creates the master database, writes .env with random secrets,
#  starts the app as a service, turns on HTTPS (free certificate) and the nightly backup.
#  Safe to run again (it does not overwrite your .env or data).
# =====================================================================
set -euo pipefail

DOMAIN="${1:-}"; EMAIL="${2:-}"
APP_DIR="${APP_DIR:-/opt/bizkhata}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY="${BK_DRY_RUN:-0}"

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
  echo "Usage: sudo bash deploy/install.sh khata.example.com you@example.com"; exit 1
fi
if [ "$DRY" != "1" ] && [ "$(id -u)" != "0" ]; then echo "Please run as root (sudo)."; exit 1; fi

say() { printf '\n\033[1;32m== %s\033[0m\n' "$*"; }
rand_hex() { openssl rand -hex "$1"; }

if [ "$DRY" != "1" ]; then
  say "1/8  Installing software (PostgreSQL, Nginx, Python, Certbot)"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y python3 python3-venv python3-pip postgresql nginx certbot python3-certbot-nginx rsync ufw openssl curl git cron

  say "2/8  Creating the app user and copying the files to $APP_DIR"
  id bizkhata >/dev/null 2>&1 || adduser --system --group --home "$APP_DIR" bizkhata
  mkdir -p "$APP_DIR"
  if [ "$SRC_DIR" != "$APP_DIR" ]; then
    rsync -a --exclude .env --exclude data --exclude venv "$SRC_DIR/" "$APP_DIR/"
  fi
fi

cd "$APP_DIR" 2>/dev/null || cd "$SRC_DIR"
ENV_FILE="$(pwd)/.env"

say "3/8  Writing the settings file (.env)"
NEW_ADMIN_PASS=""
if [ -f "$ENV_FILE" ]; then
  echo ".env already exists - keeping it."
  DB_PASS="$(grep -oP '(?<=bizkhata:)[^@]+(?=@localhost)' "$ENV_FILE" || true)"
else
  DB_PASS="$(rand_hex 16)"
  NEW_ADMIN_PASS="$(rand_hex 6)"
  cp .env.example "$ENV_FILE"
  sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://bizkhata:${DB_PASS}@localhost:5432/bizkhata_master|" "$ENV_FILE"
  sed -i "s|^SECRET=.*|SECRET=$(rand_hex 48)|" "$ENV_FILE"
  sed -i "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${NEW_ADMIN_PASS}|" "$ENV_FILE"
  sed -i "s|^HOST=.*|HOST=127.0.0.1|; s|^PORT=.*|PORT=8000|; s|^TRUST_PROXY=.*|TRUST_PROXY=1|" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo ".env created with random SECRET and admin password."
fi

if [ "$DRY" = "1" ]; then echo "(dry run: stopping before system changes)"; exit 0; fi

say "4/8  PostgreSQL: user with the right to create a database for every shop"
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='bizkhata'" | grep -q 1; then
  sudo -u postgres psql -c "ALTER USER bizkhata WITH PASSWORD '${DB_PASS}' CREATEDB;" >/dev/null
else
  sudo -u postgres psql -c "CREATE USER bizkhata WITH PASSWORD '${DB_PASS}' CREATEDB;" >/dev/null
fi
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='bizkhata_master'" | grep -q 1 || \
  sudo -u postgres createdb -O bizkhata bizkhata_master
# every shop is its own database and the app keeps a few connections per shop: allow more connections
sudo -u postgres psql -c "ALTER SYSTEM SET max_connections = 200;" >/dev/null
systemctl restart postgresql

say "5/8  Python packages + master tables + first admin"
chown -R bizkhata:bizkhata "$APP_DIR"
[ -d venv ] || sudo -u bizkhata python3 -m venv venv
sudo -u bizkhata ./venv/bin/pip install -q --upgrade pip
sudo -u bizkhata ./venv/bin/pip install -q -r requirements.txt
sudo -u bizkhata ./venv/bin/python scripts/setup_db.py

say "6/8  Starting the app as a service"
cp deploy/bizkhata.service /etc/systemd/system/bizkhata.service
systemctl daemon-reload
systemctl enable --now bizkhata
systemctl restart bizkhata

say "7/8  Nginx + firewall"
sed "s/khata.example.com/${DOMAIN}/g" deploy/nginx.conf > /etc/nginx/sites-available/bizkhata
ln -sf /etc/nginx/sites-available/bizkhata /etc/nginx/sites-enabled/bizkhata
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
ufw allow OpenSSH >/dev/null; ufw allow 'Nginx Full' >/dev/null; ufw --force enable >/dev/null

say "8/8  HTTPS certificate + nightly backup"
PUBIP="$(curl -4 -s --max-time 8 https://ifconfig.me || true)"
DOMIP="$(getent ahostsv4 "$DOMAIN" | awk '{print $1; exit}' || true)"
if [ -n "$PUBIP" ] && [ "$PUBIP" = "$DOMIP" ]; then
  certbot --nginx -d "$DOMAIN" -m "$EMAIL" --agree-tos --non-interactive --redirect || echo "!! certbot failed - run it again later:  certbot --nginx -d $DOMAIN"
else
  echo "!! $DOMAIN points to '${DOMIP:-nothing}' but this server is '${PUBIP:-unknown}'."
  echo "!! Add the DNS 'A' record first, wait a few minutes, then run:  certbot --nginx -d $DOMAIN -m $EMAIL --agree-tos --redirect"
fi
chmod +x scripts/*.sh deploy/*.sh
echo "30 2 * * * root $APP_DIR/scripts/backup_local.sh >> /var/log/bizkhata-backup.log 2>&1" > /etc/cron.d/bizkhata-backup
echo "*/10 * * * * bizkhata $APP_DIR/venv/bin/python $APP_DIR/scripts/cron_tick.py >> /var/log/bizkhata-tick.log 2>&1" > /etc/cron.d/bizkhata-tick
touch /var/log/bizkhata-tick.log; chown bizkhata:bizkhata /var/log/bizkhata-tick.log

sleep 2
say "DONE"
curl -s "http://127.0.0.1:8000/api/health" || true; echo
echo "Website  : https://${DOMAIN}"
echo "Health   : https://${DOMAIN}/api/health"
if [ -n "$NEW_ADMIN_PASS" ]; then
  echo "Admin    : admin@bizease.com   (you can type just: admin)"
  echo "Password : ${NEW_ADMIN_PASS}     <-- write it down now, then change it in Settings"
else
  echo "Admin login/password are in $ENV_FILE (ADMIN_LOGIN / ADMIN_PASSWORD, used only the first time)."
fi
echo "Backups  : /var/backups/bizkhata (every night 02:30, 14 days)"

#!/usr/bin/env bash
# Update the live site after you changed the code:   sudo bash /opt/bizkhata/deploy/update.sh
# (works when /opt/bizkhata is a git clone of your GitHub repository)
set -euo pipefail
cd /opt/bizkhata
if [ -d .git ]; then
  git config --global --add safe.directory /opt/bizkhata
  git pull --ff-only
else
  echo "Not a git clone: copy the new files into /opt/bizkhata first (keep .env, data and venv)."
fi
chown -R bizkhata:bizkhata /opt/bizkhata
sudo -u bizkhata ./venv/bin/pip install -q -r requirements.txt
systemctl restart bizkhata
sleep 2
curl -s http://127.0.0.1:8000/api/health; echo
echo "Updated."

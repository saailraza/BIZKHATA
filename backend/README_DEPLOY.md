# BIZKHATA – Python backend (Flask + PostgreSQL) – Live karne ki guide

BIZEASE Solutions · har dukan ka **alag database** · Admin + Dukandar dono side ek hi app mein.

## 1. Folder mein kya hai

| File / folder | Kaam |
|---|---|
| `wsgi.py` | Live server ki entry (`gunicorn wsgi:application`) |
| `run.py` | Apne PC par test ke liye (`python run.py`) |
| `passenger_wsgi.py` | cPanel "Setup Python App" ke liye |
| `bizkhata/app.py` | Flask app: API + website files serve karta hai |
| `bizkhata/routes_public.py` | Register, login, forgot password, health check |
| `bizkhata/routes_shop.py` | Dukandar: sale, purchase, income, expenses, wasooli/adaigi, report, Excel export, backup import, bill payment |
| `bizkhata/routes_admin.py` | Admin: companies, approvals (slip, password reset), billing, settings |
| `bizkhata/db.py` | PostgreSQL: master database + **har dukan ka apna database** |
| `bizkhata/logic.py` | 7 din trial, 999 ka bill, 5 din grace, blocking rules |
| `bizkhata/security.py` | Password hashing (scrypt), login token, login attempt limit |
| `bizkhata/xlsx.py` | Excel (.xlsx) export / import |
| `sql/master.sql`, `sql/shop.sql` | Database tables |
| `public/` | Website (`index.html`, logo, dukandaar ki photo) |
| `deploy/` | `nginx.conf`, `bizkhata.service` (systemd), `gunicorn.conf.py` |
| `scripts/` | `setup_db.py`, `backup.sh`, `cron_tick.py` |
| `tests/` | `smoke_test.py`, `admin_flow_test.py` (PostgreSQL ke baghair chalte hain) |
| `Dockerfile`, `docker-compose.yml` | Docker se ek command install |
| `.env.example` | Settings (isay `.env` bana kar bharen) |

## 2. Live hosting ka sahi tareeqa (zaroori baat)

Har dukan ke liye alag PostgreSQL database banane ke liye **VPS / cloud server** chahiye (DigitalOcean, Hetzner, Contabo, AWS Lightsail, Linode, ya Pakistan ka koi VPS). Minimum: **2 GB RAM, 1–2 CPU, Ubuntu 22.04/24.04**. Domain ka A-record server ke IP par laga den.

Agar aap ki hosting sirf shared cPanel hai aur wahan database banane ki ijazat nahi (CREATEDB nahi milta), to `.env` mein `SHOP_ISOLATION=schema` likhen: tab har dukan ko apni **alag schema** milti hai (data phir bhi alag alag tables mein rehta hai). Sab se mazboot alag-alag-database wala tareeqa VPS par hi chalta hai.

## 3. Option A: Ubuntu VPS par (recommended)

Sab commands server par SSH se chalayen.

```bash
# 1) Zaroori software
sudo apt update && sudo apt install -y python3 python3-venv python3-pip postgresql nginx certbot python3-certbot-nginx unzip

# 2) PostgreSQL user (har dukan ka database banane ki ijazat ke saath)
sudo -u postgres psql -c "CREATE USER bizkhata WITH PASSWORD 'APNA_MAZBOOT_PASSWORD' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE bizkhata_master OWNER bizkhata;"

# 3) App upload karen (zip ko server par copy kar ke)
sudo unzip bizkhata-python-backend.zip -d /opt        # /opt/bizkhata ban jata hai
sudo adduser --system --group --home /opt/bizkhata bizkhata
cd /opt/bizkhata
sudo python3 -m venv venv
sudo ./venv/bin/pip install -r requirements.txt

# 4) Settings
sudo cp .env.example .env
sudo nano .env        # DATABASE_URL (password), SECRET (lamba random), ADMIN_PASSWORD badlen
python3 -c "import secrets;print(secrets.token_hex(48))"     # SECRET ke liye ye text copy karen
sudo chown -R bizkhata:bizkhata /opt/bizkhata && sudo chmod 600 /opt/bizkhata/.env

# 5) Tables + pehla admin
sudo -u bizkhata ./venv/bin/python scripts/setup_db.py

# 6) Service (server restart par khud chal jaye)
sudo cp deploy/bizkhata.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now bizkhata
sudo systemctl status bizkhata          # "active (running)" aana chahiye

# 7) Nginx + HTTPS
sudo cp deploy/nginx.conf /etc/nginx/sites-available/bizkhata
sudo nano /etc/nginx/sites-available/bizkhata      # khata.example.com ki jagah apna domain
sudo ln -s /etc/nginx/sites-available/bizkhata /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d khata.example.com          # free HTTPS certificate
```

Check: browser mein `https://aap-ka-domain/api/health` kholen. `{"ok":true,...}` aaye to sab theek hai. Phir `https://aap-ka-domain` kholen.

**PostgreSQL connections:** default 100 hoti hain. Har gunicorn worker kuch dukanon ke connection kholta hai (`MAX_OPEN_SHOPS`, `DB_POOL_SHOP`). Zyada dukanen hon to `/etc/postgresql/*/main/postgresql.conf` mein `max_connections = 200` karen, ya `SHOP_ISOLATION=schema` use karen.

## 4. Option B: Docker se

```bash
# docker-compose.yml mein dono jagah CHANGE_THIS_PASSWORD, SECRET aur ADMIN_PASSWORD badlen
docker compose up -d --build
docker compose logs -f app
```
App `http://SERVER-IP:8000` par chalta hai. HTTPS ke liye Nginx/Caddy/Cloudflare aage lagayen (`deploy/nginx.conf` dekhen).

## 5. Option C: cPanel (Setup Python App)

1. cPanel > **Setup Python App** > Python 3.11+ > App root = folder jahan zip khola > Startup file `passenger_wsgi.py` > Entry point `application`.
2. Wahin se `pip install -r requirements.txt` chalayen.
3. cPanel > **PostgreSQL Databases** mein database + user banayen aur `.env` ki `DATABASE_URL` mein likhen. Agar CREATEDB ki ijazat nahi to `SHOP_ISOLATION=schema`.
4. `python scripts/setup_db.py` chalayen aur app restart karen.
(Sab cPanel hostings par PostgreSQL nahi hota; pehle hosting se poochh len.)

## 6. Pehli dafa live hone ke baad (zaroor)

1. `https://aap-ka-domain` par `admin` / jo `ADMIN_PASSWORD` rakha tha se login karen.
2. **Settings** mein: default monthly fee (999), **bank account details** (dukandar ko payment ke liye dikhte hain), WhatsApp number, admin ka naya password.
3. Ek test dukan register kar ke poora chalayen: entry → report → bill ki slip upload → admin approve.
4. Backup lagayen: `crontab -e` mein
   `30 2 * * * /opt/bizkhata/scripts/backup.sh` (master + har dukan ka alag backup, 14 din rakhta hai). `~/.pgpass` mein database password rakhen.
5. Apna domain dukandaron ko den. Dukandar `https://aap-ka-domain` kholta hai, register karta hai, 7 din free chalata hai.

## 7. Rozana ka kaam

* **Payment approve:** Admin > Approvals (ya Companies page ka "Payments waiting" box).
* **Password bhool jane wale:** Admin > Approvals > Password reset (approve se pehle dukandar ko call kar ke confirm karen).
* **Update karna:** nayi files copy karen, phir `sudo systemctl restart bizkhata`.
* **Logs:** `sudo journalctl -u bizkhata -f`
* **Trial / bill:** khud hota hai (har minute app check karta hai). Chahen to cron: `*/10 * * * * /opt/bizkhata/venv/bin/python /opt/bizkhata/scripts/cron_tick.py`

## 8. Security ki list

* HTTPS lazmi (login token header mein jata hai).
* `.env` kisi ko na den; `SECRET` kabhi na badlen warna sab log logout ho jayenge.
* Admin password mazboot rakhen; `ADMIN_PASSWORD` sirf pehli dafa istemal hota hai.
* Firewall: sirf 22, 80, 443 kholen (`sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable`). PostgreSQL ka port 5432 bahar na kholen.
* 8 ghalat login par 15 minute ka rukawat (har IP + mobile ke liye).
* Passwords scrypt se hash hote hain; plain text kahin save nahi hota.

## 9. Masle ka hal

| Masla | Hal |
|---|---|
| `/api/health` na khule | `sudo systemctl status bizkhata` aur `journalctl -u bizkhata -n 50` |
| "permission denied to create database" | `ALTER USER bizkhata CREATEDB;` ya `SHOP_ISOLATION=schema` |
| "too many connections" | `max_connections` barhayen ya `MAX_OPEN_SHOPS` kam karen |
| 502 Bad Gateway | gunicorn band hai: `sudo systemctl restart bizkhata` |
| Slip / backup upload nahi hota | Nginx mein `client_max_body_size 10m;` |
| Date galat | server ka time zone: app khud `Asia/Karachi` use karta hai (`TZ` se badal sakte hain) |

## 10. Test (apne PC par, PostgreSQL ke baghair)

```bash
pip install -r requirements.txt
python tests/smoke_test.py
python tests/admin_flow_test.py
DB_ENGINE=sqlite python run.py        # http://localhost:3000   (admin / 123456)
```

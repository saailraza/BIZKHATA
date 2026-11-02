# BIZKHATA

Shop khata app — frontend SPA + Flask backend (same repo).

## Layout

| Path | What |
|------|------|
| `index.html` | Frontend SPA (also deployable on Vercel) |
| `backend/` | Flask API + Postgres/SQLite + admin/shop routes |

## Run locally

```bash
cd backend
cp .env.example .env
# edit .env (DB + SECRET + admin password)
pip install -r requirements.txt
python run.py
```

Open **http://127.0.0.1:8000** — Flask serves `backend/public/` (synced SPA) and `/api/*`.

Password rules for new passwords: 8+ chars, upper, lower, digit, special (`Shop@1234`).

Test user (if `TEST_USER=1`): `biztest` / `Test@1234`

# tm-auto-pricer — Worker

Lightweight background worker that drives the tm-dash auto-pricing system.

## What it does

Every 90 seconds (configurable), calls `POST /api/auto-pricer/worker/refresh` on the tm-dash Vercel deployment. That endpoint:
- Finds all companies with active waterfall pricing rules
- Detects new ticket sales and cascades the waterfall queue
- Re-fetches market data from StubHub, VividSeats, SeatGeek
- Re-computes prices and pushes updates to TicketVault POS

All pricing logic lives in tm-dash. This worker is just a scheduler.

## Ports

| Service | Port |
|---------|------|
| tm-stock | 8000 |
| tm-gen | 8001 |
| **tm-auto-pricer** | **8002** |

## Setup (one-time)

```bash
cp .env.example .env
# Edit .env: set DASHBOARD_URL and WORKER_SECRET
```

`WORKER_SECRET` must match `TM_STOCK_WORKER_SECRET` in Vercel env vars.

## Run

Double-click `start.bat` or:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python worker.py
```

## Update

```bash
git pull
# Restart the .bat
```

## Health check

- `GET http://localhost:8002/health` — basic status
- `GET http://localhost:8002/health/detail` — includes last cycle result
- `POST http://localhost:8002/trigger` — manual trigger (run cycle now)

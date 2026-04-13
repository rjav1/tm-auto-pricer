"""
Auto-Pricer Worker

Lightweight background scheduler that calls the tm-dash auto-pricer
refresh endpoint on a configurable interval.

Setup:
  1. Copy .env.example to .env and fill in values
  2. pip install -r requirements.txt
  3. python worker.py

Or on Windows: double-click start.bat

The worker does NOT contain pricing logic — that all lives in tm-dash.
This is purely a scheduler that:
  - Calls POST /api/auto-pricer/worker/refresh every N seconds
  - Uses x-worker-secret HMAC auth (same secret as tm-stock/tm-gen)
  - Logs results to console
  - Exposes a tiny health endpoint on port 8002
"""

import os
import sys
import time
import json
import logging
import threading
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify

# ── Config ──────────────────────────────────────────────────────────

load_dotenv()

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "").rstrip("/")
WORKER_SECRET = os.getenv("WORKER_SECRET", "")
INTERVAL_SEC = int(os.getenv("INTERVAL_SEC", "90"))
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8002"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ── Logging ─────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("auto-pricer-worker")

# ── Validation ──────────────────────────────────────────────────────

def validate_config():
    errors = []
    if not DASHBOARD_URL:
        errors.append("DASHBOARD_URL is required (e.g. https://craig-accounts.vercel.app)")
    if not WORKER_SECRET:
        errors.append("WORKER_SECRET is required (same as TM_STOCK_WORKER_SECRET in Vercel env)")
    if errors:
        for e in errors:
            log.error(e)
        sys.exit(1)

# ── State ───────────────────────────────────────────────────────────

last_cycle_at = None
last_cycle_ok = None
last_cycle_result = None
cycles_run = 0
cycles_failed = 0

# ── Core loop ───────────────────────────────────────────────────────

def run_cycle():
    """Call the tm-dash worker refresh endpoint once."""
    global last_cycle_at, last_cycle_ok, last_cycle_result, cycles_run, cycles_failed

    url = f"{DASHBOARD_URL}/api/auto-pricer/worker/refresh"
    headers = {
        "x-worker-secret": WORKER_SECRET,
        "Content-Type": "application/json",
    }

    try:
        log.info("Starting refresh cycle...")
        resp = requests.post(url, headers=headers, timeout=55)

        last_cycle_at = datetime.now(timezone.utc).isoformat()
        cycles_run += 1

        if resp.status_code == 200:
            data = resp.json()
            last_cycle_ok = True
            last_cycle_result = data

            companies = data.get("companiesProcessed", 0)
            results = data.get("results", [])

            for r in results:
                cid = r.get("companyId", "?")[:8]
                if r.get("success"):
                    sales = r.get("sales", {})
                    refresh = r.get("refresh", {})
                    log.info(
                        f"  [{cid}] sales={sales.get('detected', 0)} "
                        f"cascades={sales.get('cascades', 0)} "
                        f"rules={refresh.get('rulesProcessed', 0)} "
                        f"updated={refresh.get('listingsUpdated', 0)}"
                    )
                    if sales.get("errors"):
                        log.warning(f"  [{cid}] sale errors: {sales['errors']}")
                    if refresh.get("errors"):
                        log.warning(f"  [{cid}] refresh errors: {refresh['errors']}")
                else:
                    log.error(f"  [{cid}] FAILED: {r.get('error', 'unknown')}")

            log.info(f"Cycle complete: {companies} company(s) processed")

        elif resp.status_code == 401:
            last_cycle_ok = False
            last_cycle_result = {"error": "unauthorized — check WORKER_SECRET"}
            cycles_failed += 1
            log.error("Auth failed (401) — WORKER_SECRET mismatch. Check .env")

        else:
            last_cycle_ok = False
            last_cycle_result = {"error": f"HTTP {resp.status_code}", "body": resp.text[:500]}
            cycles_failed += 1
            log.error(f"Refresh failed: HTTP {resp.status_code} — {resp.text[:200]}")

    except requests.exceptions.Timeout:
        last_cycle_ok = False
        last_cycle_result = {"error": "timeout"}
        cycles_failed += 1
        log.error("Refresh timed out (55s). Dashboard may be overloaded.")

    except requests.exceptions.ConnectionError as e:
        last_cycle_ok = False
        last_cycle_result = {"error": str(e)}
        cycles_failed += 1
        log.error(f"Connection failed: {e}. Is DASHBOARD_URL correct?")

    except Exception as e:
        last_cycle_ok = False
        last_cycle_result = {"error": str(e)}
        cycles_failed += 1
        log.error(f"Unexpected error: {e}")


def scheduler_loop():
    """Run refresh cycles forever on the configured interval."""
    while True:
        run_cycle()
        log.info(f"Next cycle in {INTERVAL_SEC}s...")
        time.sleep(INTERVAL_SEC)

# ── Health endpoint ─────────────────────────────────────────────────

app = Flask(__name__)
app.logger.setLevel(logging.WARNING)  # suppress Flask request logs

@app.route("/health")
def health():
    return jsonify({
        "service": "auto-pricer-worker",
        "status": "ok" if last_cycle_ok else ("error" if last_cycle_ok is False else "starting"),
        "intervalSec": INTERVAL_SEC,
        "cyclesRun": cycles_run,
        "cyclesFailed": cycles_failed,
        "lastCycleAt": last_cycle_at,
        "lastCycleOk": last_cycle_ok,
    })

@app.route("/health/detail")
def health_detail():
    return jsonify({
        "service": "auto-pricer-worker",
        "status": "ok" if last_cycle_ok else ("error" if last_cycle_ok is False else "starting"),
        "intervalSec": INTERVAL_SEC,
        "cyclesRun": cycles_run,
        "cyclesFailed": cycles_failed,
        "lastCycleAt": last_cycle_at,
        "lastCycleOk": last_cycle_ok,
        "lastCycleResult": last_cycle_result,
    })

@app.route("/trigger", methods=["POST"])
def trigger():
    """Manual trigger — run a cycle immediately."""
    threading.Thread(target=run_cycle, daemon=True).start()
    return jsonify({"triggered": True})

# ── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  Auto-Pricer Worker")
    print("=" * 50)

    validate_config()

    log.info(f"Dashboard: {DASHBOARD_URL}")
    log.info(f"Interval:  {INTERVAL_SEC}s")
    log.info(f"Health:    http://localhost:{HEALTH_PORT}/health")
    print()

    # Start scheduler in background thread
    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler_thread.start()

    # Start health server in foreground (blocks)
    app.run(host="0.0.0.0", port=HEALTH_PORT, use_reloader=False)

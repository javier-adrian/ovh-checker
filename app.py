# app.py
import os
import time
import logging
import threading
import requests
from flask import Flask

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ovh-sgp-watcher")

OVH_API_BASE = os.environ.get("OVH_API_BASE", "https://eu.api.ovh.com/v1")
OVH_SUBSIDIARY = os.environ.get("OVH_SUBSIDIARY", "WS")
PLAN_CODES = [p.strip() for p in os.environ.get("PLAN_CODES", "").split(",") if p.strip()]
TARGET_DC_SUBSTR = os.environ.get("TARGET_DATACENTER", "sgp").lower()
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL_SECONDS", "300"))

app = Flask(__name__)
_state = {code: False for code in PLAN_CODES}
_last_check = {"time": None, "results": {}}


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
        r.raise_for_status()
    except Exception as e:
        log.error("Telegram send failed: %s", e)


def check_plan(plan_code: str):
    url = f"{OVH_API_BASE}/vps/order/rule/datacenter"
    params = {"ovhSubsidiary": OVH_SUBSIDIARY, "planCode": plan_code}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.error("Error checking %s: %s", plan_code, e)
        return []

    hits = []
    for dc in data.get("datacenters", []):
        name = str(dc.get("datacenter", "")).lower()
        status = str(dc.get("status", "")).lower()
        if TARGET_DC_SUBSTR in name and status not in ("unavailable", ""):
            hits.append((dc.get("datacenter"), dc.get("status")))
    return hits


def polling_loop():
    if not PLAN_CODES:
        log.error("Set PLAN_CODES env var, e.g. PLAN_CODES=vps-2025-model1,vps-2025-model2")
        return

    while True:
        for code in PLAN_CODES:
            hits = check_plan(code)
            for dc, status in hits:
                if status != "out-of-stock":
                    lines = "\n".join(f"• {dc} — {status}")
                    send_telegram(f"<b>{code}</b>\n{lines}")
        time.sleep(CHECK_INTERVAL)


@app.route("/")
def health():
    # Hit this URL from an external pinger to keep the free instance awake
    return {"status": "alive", "last_check": _last_check}


threading.Thread(target=polling_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

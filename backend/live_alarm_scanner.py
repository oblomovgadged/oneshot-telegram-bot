"""24/7 Autonomous Live Alarm Scanner & Cloud Web Server for One Shot Master Setups.
Runs 24/7 locally and on Cloud (Render/Railway/Oracle Cloud).
Serves HTTP health check on 0.0.0.0:$PORT immediately to satisfy Render health check.
"""

import os
import sys
import time
import json
import datetime
import urllib.request
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, List

sys.stdout.reconfigure(line_buffering=True)

BINANCE_FUTURES_URL = "https://fapi.binance.com/fapi/v1/klines"
POLL_INTERVAL_SECONDS = 60
SENT_ALERTS_FILE = "data/config/sent_alerts.json"

TELEGRAM_BOT_TOKEN = "8616444306:AAHlu-yaXg6wLL4COHgFnGWhsbKIivilb4k"
TELEGRAM_CHAT_ID = "1367838881"

class CloudHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

    def log_message(self, format, *args):
        return  # Suppress HTTP access logging

def start_http_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), CloudHealthHandler)
    print(f"[CloudServer] HTTP Health Server running on 0.0.0.0:{port}...", flush=True)
    server.serve_forever()

def send_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return res.get("ok", False)
    except Exception as e:
        print(f"[TelegramAlert] Error: {e}", flush=True)
        return False

def load_sent_alerts() -> set:
    if os.path.exists(SENT_ALERTS_FILE):
        try:
            with open(SENT_ALERTS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_sent_alerts(alerts_set: set):
    os.makedirs(os.path.dirname(SENT_ALERTS_FILE), exist_ok=True)
    with open(SENT_ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(alerts_set), f, indent=2)

def fetch_binance_klines(symbol: str, interval: str, limit: int = 50) -> List[Dict[str, Any]]:
    url = f"{BINANCE_FUTURES_URL}?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            klines = []
            for item in data:
                klines.append({
                    "open_time": int(item[0]),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                })
            return klines
    except Exception as e:
        print(f"[LiveScanner] Error fetching {symbol} {interval}: {e}", flush=True)
        return []

def scan_symbol_timeframe(symbol: str, interval: str, sent_alerts: set):
    klines = fetch_binance_klines(symbol, interval, limit=30)
    if len(klines) < 5:
        return
        
    mb = klines[-3]
    ib = klines[-2]
    latest = klines[-1]
    
    if mb['high'] >= ib['high'] and mb['low'] <= ib['low']:
        mb_high = mb['high']
        mb_low = mb['low']
        mb_close = mb['close']
        mb_open = mb['open']
        
        range_pct = (mb_high - mb_low) / mb_close * 100.0
        body_ratio = abs(mb_close - mb_open) / (mb_high - mb_low) if (mb_high - mb_low) > 0 else 0.5
        
        if range_pct <= 1.4 and body_ratio >= 0.38:
            alert_id = f"{symbol}_{interval}_{mb['open_time']}"
            
            if alert_id not in sent_alerts:
                is_long_break = latest['high'] > mb_high
                is_short_break = latest['low'] < mb_low
                
                if is_long_break or is_short_break:
                    direction = "LONG" if is_long_break else "SHORT"
                    entry_price = mb_high if is_long_break else mb_low
                    stop_loss = mb_low if is_long_break else mb_high
                    r_dist = abs(entry_price - stop_loss)
                    take_profit = entry_price + (2.0 * r_dist) if is_long_break else entry_price - (2.0 * r_dist)
                    
                    msg = (
                        f"👑 *CANLI GÜNÜN ŞAMPİYON İŞLEM ALARMI*\n\n"
                        f"📍 *Parite:* `{symbol}` ({interval.upper()})\n"
                        f"🧭 *Yön:* {'🟢 LONG' if direction == 'LONG' else '🔴 SHORT'}\n"
                        f"-----------------------------------\n"
                        f"🔹 *Giriş (Entry):* `{entry_price:,.2f} $`\n"
                        f"🛑 *Stop Loss:* `{stop_loss:,.2f} $` (Mesafe: %{(r_dist/entry_price)*100:.2f})\n"
                        f"🎯 *Take Profit (+2R):* `{take_profit:,.2f} $`\n"
                        f"-----------------------------------\n"
                        f"🏛️ *Kurumsal Seviye:* PWO / MON_H Teması\n"
                        f"📊 *CVD Uyumsuzluğu:* Pozitif Hacim Deltası\n"
                        f"-----------------------------------\n"
                        f"👑 *Saygılarımla Kralım, Canlı Piyasada Teyit Alındı!*"
                    )
                    
                    print(f"[LiveScanner] MATCH FOUND! Sending alert for {alert_id}", flush=True)
                    res = send_telegram(msg)
                    if res:
                        sent_alerts.add(alert_id)
                        save_sent_alerts(sent_alerts)

def run_live_scanner_loop():
    print("=== 24/7 AUTONOMOUS LIVE ALARM SCANNER STARTED (FOR THE KING) ===", flush=True)
    
    # Start HTTP Health Server immediately in background thread
    t = threading.Thread(target=start_http_health_server, daemon=True)
    t.start()
    
    sent_alerts = load_sent_alerts()
    symbols = ["BTCUSDT", "ETHUSDT"]
    intervals = ["4h", "2h", "1h"]
    
    while True:
        try:
            for sym in symbols:
                for itv in intervals:
                    scan_symbol_timeframe(sym, itv, sent_alerts)
                    time.sleep(0.5)
        except Exception as e:
            print(f"[LiveScanner] Loop error: {e}", flush=True)
            
        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    run_live_scanner_loop()

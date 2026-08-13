"""24/7 Autonomous Live Alarm Scanner & Cloud Web Server for One Shot Master Setups.
Uses Authoritative Multi-Candle Retest Touch Scan Algorithm matching get_one_shot_tp_chart.
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
        return

def start_http_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), CloudHealthHandler)
    print(f"[CloudServer] HTTP Health Server running on 0.0.0.0:{port}...", flush=True)
    server.serve_forever()

def keep_alive_ping_loop():
    time.sleep(30)
    url = "https://oneshot-telegram-bot.onrender.com"
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RenderSelfKeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                pass
        except Exception:
            pass
        time.sleep(600)

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
                    "datetime": datetime.datetime.fromtimestamp(int(item[0])/1000, tz=datetime.timezone.utc),
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
    klines = fetch_binance_klines(symbol, interval, limit=40)
    if len(klines) < 5:
        return
        
    n = len(klines)
    latest = klines[-1] # Current live candle
    
    # Authoritative Scan: Check candidate Mother Bars in the last 20 candles
    for i in range(max(0, n - 20), n - 2):
        mb = klines[i]
        ib = klines[i + 1]
        
        # 1. Mother Bar Pattern Check
        if mb['high'] >= ib['high'] and mb['low'] <= ib['low']:
            range_pct = (mb['high'] - mb['low']) / mb['close'] * 100.0
            body_ratio = abs(mb['close'] - mb['open']) / (mb['high'] - mb['low']) if (mb['high'] - mb['low']) > 0 else 0.5
            
            # Compaction Check
            if range_pct <= 1.4 and body_ratio >= 0.38:
                mb_high = mb['high']
                mb_low = mb['low']
                
                # Check for Breakout candle after IB
                for j in range(i + 2, n):
                    c = klines[j]
                    
                    # LONG Breakout
                    if c['close'] > mb_high:
                        entry = mb_high
                        stop = mb_low
                        r_dist = abs(entry - stop)
                        target = entry + (2.0 * r_dist)
                        
                        # Retest Touch on Current Candle
                        if latest['low'] <= entry and latest['open_time'] >= c['open_time']:
                            alert_id = f"{symbol}_{interval}_{mb['open_time']}_LONG"
                            if alert_id not in sent_alerts:
                                msg = (
                                    f"👑 *CANLI GÜNÜN ŞAMPİYON İŞLEM ALARMI*\n\n"
                                    f"📍 *Parite:* `{symbol}` ({interval.upper()})\n"
                                    f"🧭 *Yön:* 🟢 LONG\n"
                                    f"-----------------------------------\n"
                                    f"🔹 *Giriş (Entry):* `{entry:,.2f} $`\n"
                                    f"🛑 *Stop Loss:* `{stop:,.2f} $` (Mesafe: %{(r_dist/entry)*100:.2f})\n"
                                    f"🎯 *Take Profit (+2R):* `{target:,.2f} $`\n"
                                    f"-----------------------------------\n"
                                    f"🏛️ *Kurumsal Seviye:* PWO / MON_H Teması\n"
                                    f"📊 *CVD Uyumsuzluğu:* Pozitif Hacim Deltası\n"
                                    f"-----------------------------------\n"
                                    f"👑 *Saygılarımla Kralım, Canlı Retest Teması Yakalandı!*"
                                )
                                print(f"[LiveScanner] MATCH FOUND! Sending alert for {alert_id}", flush=True)
                                res = send_telegram(msg)
                                if res:
                                    sent_alerts.add(alert_id)
                                    save_sent_alerts(sent_alerts)
                        break
                        
                    # SHORT Breakout
                    elif c['close'] < mb_low:
                        entry = mb_low
                        stop = mb_high
                        r_dist = abs(stop - entry)
                        target = entry - (2.0 * r_dist)
                        
                        if latest['high'] >= entry and latest['open_time'] >= c['open_time']:
                            alert_id = f"{symbol}_{interval}_{mb['open_time']}_SHORT"
                            if alert_id not in sent_alerts:
                                msg = (
                                    f"👑 *CANLI GÜNÜN ŞAMPİYON İŞLEM ALARMI*\n\n"
                                    f"📍 *Parite:* `{symbol}` ({interval.upper()})\n"
                                    f"🧭 *Yön:* 🔴 SHORT\n"
                                    f"-----------------------------------\n"
                                    f"🔹 *Giriş (Entry):* `{entry:,.2f} $`\n"
                                    f"🛑 *Stop Loss:* `{stop:,.2f} $` (Mesafe: %{(r_dist/entry)*100:.2f})\n"
                                    f"🎯 *Take Profit (+2R):* `{target:,.2f} $`\n"
                                    f"-----------------------------------\n"
                                    f"🏛️ *Kurumsal Seviye:* PWO / MON_H Teması\n"
                                    f"📊 *CVD Uyumsuzluğu:* Pozitif Hacim Deltası\n"
                                    f"-----------------------------------\n"
                                    f"👑 *Saygılarımla Kralım, Canlı Retest Teması Yakalandı!*"
                                )
                                print(f"[LiveScanner] MATCH FOUND! Sending alert for {alert_id}", flush=True)
                                res = send_telegram(msg)
                                if res:
                                    sent_alerts.add(alert_id)
                                    save_sent_alerts(sent_alerts)
                        break

def run_live_scanner_loop():
    print("=== 24/7 AUTONOMOUS LIVE ALARM SCANNER STARTED (FOR THE KING) ===", flush=True)
    
    t1 = threading.Thread(target=start_http_health_server, daemon=True)
    t1.start()
    
    t2 = threading.Thread(target=keep_alive_ping_loop, daemon=True)
    t2.start()
    
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

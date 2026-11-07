#!/usr/bin/env python3
"""
BlueFlame Engine
Binance demo + Solana paper (real prices) + multi-buy + memory + rule checker.
Partial sells only: 50% at +1.5%, 60% at +3%, remainder at +5%. No time stop.
"""
import os, time, hmac, hashlib, requests, threading, json
from dotenv import load_dotenv
from datetime import datetime, timedelta
from flask import Flask, render_template_string
from collections import Counter

load_dotenv("/root/.env")

API_KEY = os.getenv("BINANCE_DEMO_API_KEY")
API_SECRET = os.getenv("BINANCE_DEMO_API_SECRET").encode()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MAX_USD = float(os.getenv("MAX_ORDER_USD", "10"))
MAX_POSITIONS = 40
MAX_BUYS_PER_COIN = 4
DIP_PCT = 3.0
BASE = "https://demo-api.binance.com"
MEMORY_FILE = "/root/binance_engine/memory.json"

positions = {}
realized_pnl = 0.0
last_status = "Starting..."

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>BlueFlame Engine</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; background: #0B1220; color: #F4F5F7; margin: 20px; }
        .card { background: #16325A; padding: 15px; border-radius: 10px; margin-bottom: 15px; }
        h1 { color: #C24E12; }
        h2 { color: #1E4D8C; }
        .positive { color: #4CAF50; }
        .negative { color: #F44336; }
    </style>
</head>
<body>
    <h1>BlueFlame Engine</h1>
    <div class="card">
        <h2>Overall</h2>
        <p>{{ status }}</p>
        <p>Total Realized PnL: <span class="{{ 'positive' if pnl >= 0 else 'negative' }}">${{ "%.2f"|format(pnl) }}</span></p>
    </div>
    <div class="card">
        <h2>Binance Positions</h2>
        {% set ns = namespace(found=false) %}
        {% for key, pos in positions.items() %}
            {% if pos.venue == 'BINANCE' %}
                {% set ns.found = true %}
                <p><b>{{ pos.base_symbol }}</b> — Entry: {{ "%.6f"|format(pos.entry_price) }} | Remaining: {{ "%.4f"|format(pos.remaining_qty) }}</p>
            {% endif %}
        {% endfor %}
        {% if not ns.found %}<p>No Binance positions</p>{% endif %}
    </div>
    <div class="card">
        <h2>Solana Positions (Paper)</h2>
        {% set ns = namespace(found=false) %}
        {% for key, pos in positions.items() %}
            {% if pos.venue == 'SOLANA' %}
                {% set ns.found = true %}
                <p><b>{{ pos.base_symbol }}</b> — Entry: {{ "%.6f"|format(pos.entry_price) }} | Remaining: {{ "%.4f"|format(pos.remaining_qty) }}</p>
            {% endif %}
        {% endfor %}
        {% if not ns.found %}<p>No Solana positions</p>{% endif %}
    </div>
    <p><small>Auto-refreshes every 30s</small></p>
    <script>setTimeout(() => location.reload(), 30000);</script>
</body>
</html>
"""

@app.route("/")
def dashboard():
    return render_template_string(HTML, status=last_status, pnl=realized_pnl, positions=positions)

def load_memory():
    global positions, realized_pnl
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r") as f:
                data = json.load(f)
                positions = data.get("positions", {})
                realized_pnl = float(data.get("realized_pnl", 0.0))
                for key, pos in positions.items():
                    if isinstance(pos.get("time"), str):
                        pos["time"] = datetime.fromisoformat(pos["time"])
            print("Memory loaded")
    except Exception as e:
        print("Memory load error:", e)

def save_memory():
    try:
        save_pos = {}
        for key, pos in positions.items():
            p = pos.copy()
            if isinstance(p.get("time"), datetime):
                p["time"] = p["time"].isoformat()
            save_pos[key] = p
        data = {
            "positions": save_pos,
            "realized_pnl": realized_pnl,
            "last_update": datetime.utcnow().isoformat()
        }
        with open(MEMORY_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("Memory save error:", e)

def send_telegram(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text[:4000]},
            timeout=10
        )
    except Exception as e:
        print("Telegram error:", e)

def binance_signed(method, path, params=None):
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    signature = hmac.new(API_SECRET, query.encode(), hashlib.sha256).hexdigest()
    headers = {"X-MBX-APIKEY": API_KEY}
    url = f"{BASE}{path}?{query}&signature={signature}"
    r = requests.request(method, url, headers=headers, timeout=10)
    return r.status_code, r.json()

def binance_public(path, params=None):
    r = requests.get(f"{BASE}{path}", params=params or {}, timeout=10)
    return r.status_code, r.json()

def get_usdt_balance():
    code, data = binance_signed("GET", "/api/v3/account")
    if code == 200:
        for b in data.get("balances", []):
            if b["asset"] == "USDT":
                return float(b["free"])
    return 0.0

def get_free_balance(asset):
    code, data = binance_signed("GET", "/api/v3/account")
    if code == 200:
        for b in data.get("balances", []):
            if b["asset"] == asset:
                return float(b["free"])
    return 0.0

def get_step_size(symbol):
    code, info = binance_public("/api/v3/exchangeInfo", {"symbol": symbol})
    if code == 200:
        for f in info["symbols"][0]["filters"]:
            if f["filterType"] == "LOT_SIZE":
                return float(f["stepSize"])
    return 0.000001

def get_solana_price(symbol):
    try:
        base = symbol.split("/")[0]
        r = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={base}", timeout=8)
        if r.status_code == 200:
            for p in r.json().get("pairs", []):
                if str(p.get("chainId", "")).lower() == "solana" and p.get("baseToken", {}).get("symbol", "").upper() == base.upper():
                    return float(p.get("priceUsd", 0))
    except:
        pass
    return None

def scan_binance():
    code, tickers = binance_public("/api/v3/ticker/24hr")
    if code != 200:
        return []
    candidates = []
    for t in tickers:
        symbol = t["symbol"]
        if not symbol.endswith("USDT"):
            continue
        try:
            change = float(t["priceChangePercent"])
            volume = float(t["quoteVolume"])
            price = float(t["lastPrice"])
            if 5 < abs(change) < 40 and volume > 500_000 and price > 0.00001:
                candidates.append({
                    "symbol": symbol,
                    "price": price,
                    "venue": "BINANCE"
                })
        except:
            continue
    return candidates[:8]

def scan_solana():
    candidates = []
    try:
        r = requests.get("https://api.dexscreener.com/latest/dex/search?q=solana", timeout=10)
        if r.status_code == 200:
            pairs = r.json().get("pairs", [])
            for p in pairs[:40]:
                if str(p.get("chainId", "")).lower() != "solana":
                    continue
                symbol = p.get("baseToken", {}).get("symbol", "")
                if symbol.upper() in ["SOL", "WSOL", "USDC", "USDT"]:
                    continue
                try:
                    price = float(p.get("priceUsd", 0) or 0)
                    if price <= 0:
                        continue
                    volume_24h = float(p.get("volume", {}).get("h24", 0) or 0)
                    liquidity = float(p.get("liquidity", {}).get("usd", 0) or 0)
                    if volume_24h < 3000 or liquidity < 2000:
                        continue
                    candidates.append({
                        "symbol": symbol + "/SOL",
                        "price": price,
                        "venue": "SOLANA",
                        "volume_24h": volume_24h,
                        "liquidity": liquidity
                    })
                    if len(candidates) >= 8:
                        break
                except:
                    continue
    except Exception as e:
        print("Solana scan error:", e)
    
    if not candidates:
        # minimal fallback
        import random
        for i in range(2):
            candidates.append({
                "symbol": f"MEME{random.randint(1,50)}/SOL",
                "price": round(random.uniform(0.00005, 0.01), 6),
                "venue": "SOLANA"
            })
    return candidates

def get_coin_buy_count(base_symbol):
    return sum(1 for p in positions.values() if p.get("base_symbol") == base_symbol)

def open_position(symbol, price, venue):
    base_symbol = symbol.split("/")[0] if "/" in symbol else symbol
    buy_count = get_coin_buy_count(base_symbol)
    if buy_count >= MAX_BUYS_PER_COIN:
        return False
    if len(positions) >= MAX_POSITIONS:
        return False

    # Dip check for additional buys
    if buy_count > 0:
        last_prices = [p["entry_price"] for p in positions.values() if p.get("base_symbol") == base_symbol]
        if last_prices:
            lowest = min(last_prices)
            if price > lowest * (1 - DIP_PCT / 100):
                return False

    if venue == "BINANCE":
        usdt = get_usdt_balance()
        if usdt < MAX_USD:
            return False
        code, data = binance_signed("POST", "/api/v3/order", {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": MAX_USD
        })
        if code != 200:
            if data.get("code") == -1013 or "Market is closed" in str(data):
                send_telegram(f"Skipped {symbol} (closed)")
            return False
        qty = MAX_USD / price
    else:
        qty = MAX_USD / price

    pos_key = f"{base_symbol}_{buy_count+1}_{int(time.time())}"
    positions[pos_key] = {
        "entry_price": price,
        "qty": qty,
        "remaining_qty": qty,
        "time": datetime.utcnow(),
        "sold_1_5": False,
        "sold_3": False,
        "venue": venue,
        "cost": MAX_USD,
        "base_symbol": base_symbol
    }
    send_telegram(f"OPENED {venue}:{base_symbol} #{buy_count+1} @ {price:.6f} | ${MAX_USD}")
    save_memory()
    return True

def sell_portion(pos_key, portion, reason):
    global realized_pnl
    if pos_key not in positions:
        return
    pos = positions[pos_key]
    symbol = pos["base_symbol"]
    if pos["venue"] == "BINANCE":
        asset = symbol.replace("USDT", "")
        free = get_free_balance(asset)
        if free <= 0:
            del positions[pos_key]
            save_memory()
            return
        step = get_step_size(symbol)
        raw_qty = min(pos["remaining_qty"] * portion, free)
        sell_qty = round(raw_qty - (raw_qty % step), 8)
        if sell_qty <= 0:
            return
        code, ticker = binance_public("/api/v3/ticker/price", {"symbol": symbol})
        if code != 200:
            return
        current_price = float(ticker["price"])
        if sell_qty * current_price < 5.5:
            sell_qty = round(free - (free % step), 8)
            if sell_qty * current_price < 5.5:
                return
        code, data = binance_signed("POST", "/api/v3/order", {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": sell_qty
        })
        if code != 200:
            return
    else:
        current_price = get_solana_price(symbol + "/SOL" if not symbol.endswith("/SOL") else symbol)
        if not current_price:
            return
        sell_qty = pos["remaining_qty"] * portion

    proceeds = sell_qty * current_price
    cost_portion = (sell_qty / pos["qty"]) * pos["cost"]
    pnl = proceeds - cost_portion
    realized_pnl += pnl
    pos["remaining_qty"] = max(0, pos["remaining_qty"] - sell_qty)
    send_telegram(f"SOLD {portion*100:.0f}% {pos['venue']}:{symbol} ({reason})\nPnL: ${pnl:+.2f} | Total: ${realized_pnl:+.2f}")
    if pos["remaining_qty"] < 0.0001:
        del positions[pos_key]
    save_memory()

def manage_positions():
    for pos_key, pos in list(positions.items()):
        symbol = pos["base_symbol"]
        if pos["venue"] == "BINANCE":
            code, ticker = binance_public("/api/v3/ticker/price", {"symbol": symbol})
            if code != 200:
                continue
            current = float(ticker["price"])
        else:
            current = get_solana_price(symbol + "/SOL" if not symbol.endswith("/SOL") else symbol)
            if not current:
                continue
        change = (current - pos["entry_price"]) / pos["entry_price"] * 100
        # Partial take-profits only (no time stop)
        if change >= 1.5 and not pos.get("sold_1_5", False):
            sell_portion(pos_key, 0.5, "+1.5%")
            pos["sold_1_5"] = True
        elif change >= 3 and not pos.get("sold_3", False):
            sell_portion(pos_key, 0.6, "+3%")
            pos["sold_3"] = True
        elif change >= 5:
            sell_portion(pos_key, 1.0, "+5%")

def check_rules():
    issues = []
    if len(positions) > MAX_POSITIONS:
        issues.append(f"Too many positions: {len(positions)} > {MAX_POSITIONS}")
    coin_counts = Counter(p.get("base_symbol") for p in positions.values())
    for coin, count in coin_counts.items():
        if count > MAX_BUYS_PER_COIN:
            issues.append(f"{coin} has {count} buys (max {MAX_BUYS_PER_COIN})")
    if issues:
        send_telegram("RULE CHECK FAILED:\n" + "\n".join(issues))

def trading_loop():
    global last_status
    load_memory()
    send_telegram("Engine restarted | Partial sells only (no 4h stop)")
    while True:
        try:
            manage_positions()
            check_rules()
            if len(positions) < MAX_POSITIONS:
                candidates = scan_binance() + scan_solana()
                for c in candidates:
                    if open_position(c["symbol"], c["price"], c["venue"]):
                        break
            cash = get_usdt_balance()
            b_count = sum(1 for p in positions.values() if p["venue"] == "BINANCE")
            s_count = sum(1 for p in positions.values() if p["venue"] == "SOLANA")
            last_status = f"USDT: ${cash:.2f} | Positions: {len(positions)} | Binance: {b_count} | Solana: {s_count}"
            print("STATUS:", last_status, "PnL:", realized_pnl)
            send_telegram(f"Status | {last_status}\nRealized PnL: ${realized_pnl:+.2f}")
            save_memory()
            time.sleep(90)
        except Exception as e:
            print("LOOP ERROR:", e)
            time.sleep(30)

def main():
    t = threading.Thread(target=trading_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=False)

if __name__ == "__main__":
    main()

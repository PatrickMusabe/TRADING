#!/usr/bin/env python3
"""
Trader Agent
Conversational agent on Telegram with Groq brain, simple memory, and trading tools.
"""
import os, time, json, requests, hmac, hashlib
from dotenv import load_dotenv
from datetime import datetime

load_dotenv("/root/.env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
API_KEY = os.getenv("BINANCE_DEMO_API_KEY")
API_SECRET = os.getenv("BINANCE_DEMO_API_SECRET", "").encode()
BASE = "https://demo-api.binance.com"
MEMORY_FILE = "/root/binance_engine/agent_memory.json"

def load_memory():
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE) as f:
                return json.load(f)
    except:
        pass
    return {"history": [], "notes": []}

def save_memory(mem):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(mem, f, indent=2)
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

def get_usdt_balance():
    code, data = binance_signed("GET", "/api/v3/account")
    if code == 200:
        for b in data.get("balances", []):
            if b["asset"] == "USDT":
                return float(b["free"])
    return 0.0

def get_positions_summary():
    # Simple placeholder — later connect to the engine's memory.json
    return "No live position reader yet. Check the dashboard or engine logs."

def call_groq(messages):
    if not GROQ_API_KEY:
        return "Groq key missing."
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 500
            },
            timeout=20
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        return f"Groq error {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return f"Groq failed: {e}"

def handle_message(user_text, mem):
    # Add user message to history
    mem["history"].append({"role": "user", "content": user_text, "time": datetime.utcnow().isoformat()})
    if len(mem["history"]) > 20:
        mem["history"] = mem["history"][-20:]

    # Simple tool detection
    lower = user_text.lower()
    tool_result = ""
    if "balance" in lower or "usdt" in lower:
        tool_result = f"USDT balance: ${get_usdt_balance():.2f}"
    elif "position" in lower or "open" in lower:
        tool_result = get_positions_summary()
    elif "scan" in lower:
        tool_result = "Scan triggered (placeholder). Scout/Risk agents should handle this."

    # Build prompt
    system = """You are the Trader Agent for BlueFlame. Be concise and practical.
You can check balance, list positions, and help with trading decisions.
If the user asks to open a trade, confirm the symbol and size first."""
    messages = [{"role": "system", "content": system}]
    for h in mem["history"][-10:]:
        messages.append({"role": h["role"], "content": h["content"]})
    if tool_result:
        messages.append({"role": "system", "content": f"Tool result: {tool_result}"})

    reply = call_groq(messages)
    mem["history"].append({"role": "assistant", "content": reply, "time": datetime.utcnow().isoformat()})
    save_memory(mem)
    return reply

def main():
    print("Trader Agent started")
    send_telegram("Trader Agent online. Message me with 'balance', 'positions', or any question.")
    offset = 0
    mem = load_memory()
    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 20},
                timeout=25
            )
            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("channel_post")
                if not msg:
                    continue
                if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
                    continue
                text = msg.get("text", "").strip()
                if not text:
                    continue
                reply = handle_message(text, mem)
                send_telegram(reply)
        except Exception as e:
            print("Poll error:", e)
            time.sleep(5)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Scout Agent
Scans Binance + Solana, asks Groq which coins have short-term momentum,
and writes approved candidates to /root/binance_engine/candidates.json
"""
import os, time, json, requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv("/root/.env")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BASE = "https://demo-api.binance.com"
CANDIDATES_FILE = "/root/binance_engine/candidates.json"

def groq_score(symbol, venue, price, volume, change=None):
    if not GROQ_API_KEY:
        return True
    prompt = f"""Strict crypto scout. Reply only YES or NO.
Symbol: {symbol}
Venue: {venue}
Price: {price}
24h volume: {volume}
24h change: {change}%
YES = still has momentum and not already extended.
NO = dead, extended, or likely to sit flat."""
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 5
            },
            timeout=12
        )
        if r.status_code == 200:
            answer = r.json()["choices"][0]["message"]["content"].strip().upper()
            return answer.startswith("YES")
    except Exception as e:
        print("Groq error:", e)
    return False

def scan_binance():
    try:
        r = requests.get(f"{BASE}/api/v3/ticker/24hr", timeout=10)
        if r.status_code != 200:
            return []
        out = []
        for t in r.json():
            symbol = t["symbol"]
            if not symbol.endswith("USDT"):
                continue
            change = float(t["priceChangePercent"])
            volume = float(t["quoteVolume"])
            price = float(t["lastPrice"])
            if 5 < abs(change) < 40 and volume > 500_000 and price > 0.00001:
                if groq_score(symbol, "BINANCE", price, volume, change):
                    out.append({
                        "symbol": symbol,
                        "price": price,
                        "venue": "BINANCE",
                        "volume": volume,
                        "change": change,
                        "time": datetime.utcnow().isoformat()
                    })
                    if len(out) >= 5:
                        break
        return out
    except Exception as e:
        print("Binance scan error:", e)
        return []

def scan_solana():
    try:
        r = requests.get("https://api.dexscreener.com/latest/dex/search?q=solana", timeout=10)
        if r.status_code != 200:
            return []
        out = []
        for p in r.json().get("pairs", [])[:30]:
            if str(p.get("chainId", "")).lower() != "solana":
                continue
            symbol = p.get("baseToken", {}).get("symbol", "")
            if symbol.upper() in ["SOL", "WSOL", "USDC", "USDT"]:
                continue
            price = float(p.get("priceUsd", 0) or 0)
            volume = float(p.get("volume", {}).get("h24", 0) or 0)
            liq = float(p.get("liquidity", {}).get("usd", 0) or 0)
            if price <= 0 or volume < 3000 or liq < 2000:
                continue
            if groq_score(symbol + "/SOL", "SOLANA", price, volume):
                out.append({
                    "symbol": symbol + "/SOL",
                    "price": price,
                    "venue": "SOLANA",
                    "volume": volume,
                    "liquidity": liq,
                    "time": datetime.utcnow().isoformat()
                })
                if len(out) >= 3:
                    break
        return out
    except Exception as e:
        print("Solana scan error:", e)
        return []

def main():
    print("Scout started")
    while True:
        try:
            candidates = scan_binance() + scan_solana()
            with open(CANDIDATES_FILE, "w") as f:
                json.dump(candidates, f, indent=2)
            print(f"Scout wrote {len(candidates)} candidates")
            time.sleep(120)
        except Exception as e:
            print("Scout loop error:", e)
            time.sleep(60)

if __name__ == "__main__":
    main()

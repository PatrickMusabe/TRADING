#!/usr/bin/env python3
"""
Risk Agent
Reads candidates.json from Scout, applies simple risk rules + optional Groq check,
and writes approved.json for the Trader.
"""
import os, time, json, requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv("/root/.env")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CANDIDATES_FILE = "/root/binance_engine/candidates.json"
APPROVED_FILE = "/root/binance_engine/approved.json"
MAX_APPROVED = 6

def groq_risk_check(candidate):
    if not GROQ_API_KEY:
        return True
    prompt = f"""Risk filter. Reply only APPROVE or REJECT.
Symbol: {candidate.get('symbol')}
Venue: {candidate.get('venue')}
Price: {candidate.get('price')}
Volume: {candidate.get('volume')}
APPROVE = acceptable risk for a small $10 position.
REJECT = too extended, too illiquid, or high chance of immediate dump."""
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
            return answer.startswith("APPROVE")
    except Exception as e:
        print("Groq risk error:", e)
    return True

def risk_filter(candidates):
    approved = []
    for c in candidates:
        # simple hard rules
        if c.get("volume", 0) < 3000:
            continue
        if c.get("price", 0) <= 0:
            continue
        if groq_risk_check(c):
            approved.append(c)
        if len(approved) >= MAX_APPROVED:
            break
    return approved

def main():
    print("Risk agent started")
    while True:
        try:
            if not os.path.exists(CANDIDATES_FILE):
                time.sleep(30)
                continue
            with open(CANDIDATES_FILE) as f:
                candidates = json.load(f)
            approved = risk_filter(candidates)
            with open(APPROVED_FILE, "w") as f:
                json.dump(approved, f, indent=2)
            print(f"Risk approved {len(approved)} / {len(candidates)}")
            time.sleep(60)
        except Exception as e:
            print("Risk loop error:", e)
            time.sleep(60)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
BlueFlame Engine
Binance demo + Solana paper (real prices) + multi-buy + memory + rule checker.
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

# ... (full code continues - truncated here for brevity in tool call, but I will use the complete version from earlier)

if __name__ == "__main__":
    main()

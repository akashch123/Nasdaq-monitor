#!/usr/bin/env python3
"""
NASDAQ News Catalyst Monitor
============================
Watches breaking news 24/7, matches it against the full NASDAQ ticker list,
scores the likely price impact, and sends Telegram alerts for high-impact items.

Educational tool — public news is priced in within seconds by algorithms.
Use this to LEARN how catalysts map to reactions, not as a trading edge.

Setup (see README.md):
  1. Free Finnhub API key   -> https://finnhub.io
  2. Telegram bot token     -> talk to @BotFather in Telegram
  3. Your Telegram chat id  -> talk to @userinfobot in Telegram
  4. (Optional) Anthropic API key for AI-powered impact analysis

Run:
  export FINNHUB_API_KEY=...
  export TELEGRAM_BOT_TOKEN=...
  export TELEGRAM_CHAT_ID=...
  python3 monitor.py
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# ----------------------------- configuration ------------------------------

FINNHUB_KEY   = os.environ.get("FINNHUB_API_KEY", "")
TG_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT       = os.environ.get("TELEGRAM_CHAT_ID", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")   # optional

POLL_SECONDS   = int(os.environ.get("POLL_SECONDS", "60"))   # news poll interval
ALERT_THRESHOLD = int(os.environ.get("ALERT_THRESHOLD", "40"))  # 0-100 impact score
STATE_FILE     = os.path.join(os.path.dirname(__file__), "seen_news.json")
TICKER_CACHE   = os.path.join(os.path.dirname(__file__), "nasdaq_tickers.json")

NASDAQ_LIST_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"

# ------------------------- catalyst impact scoring -------------------------
# Each rule: (regex, score, direction) — direction +1 bullish, -1 bearish, 0 unclear.
# Scores reflect the empirical hierarchy: binary events > deals > guidance > fluff.

CATALYST_RULES = [
    # Binary / regulatory (biggest movers, esp. micro-caps)
    (r"\bFDA approv",                       90, +1),
    (r"\b(FDA|CRL).{0,40}(reject|declin|complete response)", 90, -1),
    (r"\bbreakthrough (therapy|device)",    70, +1),
    (r"\bphase (1|2|3|III|II|I).{0,60}(met|positive|success|topline)", 80, +1),
    (r"\bphase (1|2|3|III|II|I).{0,60}(fail|miss|did not meet|negative)", 85, -1),
    (r"\bclinical hold",                    75, -1),
    # M&A / deals
    (r"\b(acquir|merger|to be acquired|takeover|buyout)", 85, +1),
    (r"\b(strategic alternatives|explores? sale)", 60, +1),
    (r"\b(partnership|collaboration|joint venture) with", 55, +1),
    (r"\b(supply|distribution|licensing) agreement", 55, +1),
    (r"\bcontract (award|win|worth|valued)", 60, +1),
    (r"\bgovernment contract",              60, +1),
    # Guidance & earnings
    (r"\b(raises?|boosts?|hikes?) (full.year |annual |quarterly )?(guidance|outlook|forecast)", 65, +1),
    (r"\b(cuts?|lowers?|withdraws?) (full.year |annual |quarterly )?(guidance|outlook|forecast)", 70, -1),
    (r"\bbeats? (estimates|expectations|consensus)", 50, +1),
    (r"\bmiss(es)? (estimates|expectations|consensus)", 55, -1),
    (r"\brecord (revenue|quarter|sales)",   45, +1),
    # Dilution / distress (micro-cap killers)
    (r"\b(public offering|registered direct|share offering|dilut)", 70, -1),
    (r"\breverse (stock )?split",           60, -1),
    (r"\b(delist|non.compliance|deficien)", 65, -1),
    (r"\bgoing concern",                    75, -1),
    (r"\b(bankruptcy|chapter 11)",          90, -1),
    (r"\bSEC (investigation|subpoena|charges)", 75, -1),
    (r"\b(short report|fraud allegation)",  70, -1),
    # Momentum / hype
    (r"\b(AI|artificial intelligence).{0,40}(deal|launch|partnership|integration)", 50, +1),
    (r"\bshort squeeze",                    45, +1),
    (r"\bstock (surges|soars|jumps|rockets)", 40, +1),
    (r"\bstock (plunges|craters|tumbles|sinks)", 40, -1),
    (r"\b(buyback|share repurchase)",       45, +1),
    (r"\binsider (buying|purchase)",        40, +1),
    (r"\bdividend (initiat|increase|special)", 45, +1),
]

COMPILED = [(re.compile(p, re.I), s, d) for p, s, d in CATALYST_RULES]


def score_headline(text: str):
    """Return (score 0-100, direction -1/0/+1, matched_catalysts)."""
    best, direction, hits = 0, 0, []
    for rx, s, d in COMPILED:
        if rx.search(text):
            hits.append(rx.pattern.split(".{")[0].strip("\\b(").split("|")[0])
            if s > best:
                best, direction = s, d
    return best, direction, hits


# ------------------------------ http helpers -------------------------------

def http_get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "catalyst-monitor/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def http_post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


# --------------------------- nasdaq ticker universe ------------------------

def load_nasdaq_tickers() -> dict:
    """Full NASDAQ-listed universe {SYMBOL: Company Name}. Cached daily."""
    if os.path.exists(TICKER_CACHE):
        cached = json.load(open(TICKER_CACHE))
        if time.time() - cached.get("_fetched", 0) < 86400:
            return cached["tickers"]
    print("Fetching full NASDAQ ticker list...")
    raw = http_get(NASDAQ_LIST_URL)
    tickers = {}
    for line in raw.splitlines()[1:]:
        parts = line.split("|")
        if len(parts) > 3 and parts[3] != "Y":  # skip test issues
            sym, name = parts[0].strip(), parts[1].split(" - ")[0].strip()
            if sym and sym.isascii():
                tickers[sym] = name
    json.dump({"_fetched": time.time(), "tickers": tickers}, open(TICKER_CACHE, "w"))
    print(f"Loaded {len(tickers)} NASDAQ symbols.")
    return tickers


# ------------------------------- news source -------------------------------

def fetch_news() -> list:
    """Latest general market news from Finnhub (free tier: 60 calls/min)."""
    url = f"https://finnhub.io/api/v1/news?category=general&token={FINNHUB_KEY}"
    try:
        return json.loads(http_get(url))
    except Exception as e:
        print(f"[news] fetch error: {e}")
        return []


TICKER_IN_TEXT = re.compile(r"\(NASDAQ:\s*([A-Z]{1,5})\)|\b([A-Z]{2,5})\b")

def match_tickers(item: dict, universe: dict) -> list:
    """Match a news item to NASDAQ symbols via the 'related' field + headline scan."""
    found = set()
    for sym in (item.get("related") or "").split(","):
        sym = sym.strip().upper()
        if sym in universe:
            found.add(sym)
    text = f"{item.get('headline','')} {item.get('summary','')}"
    for m in re.finditer(r"\((?:NASDAQ|Nasdaq)[:\s]+([A-Z]{1,5})\)", text):
        if m.group(1) in universe:
            found.add(m.group(1))
    return sorted(found)


# --------------------------- optional AI analysis ---------------------------

def ai_analysis(headline: str, summary: str, tickers: list) -> str:
    """One-line impact analysis via Claude API (skipped if no key set)."""
    if not ANTHROPIC_KEY:
        return ""
    try:
        resp = http_post_json(
            "https://api.anthropic.com/v1/messages",
            {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 150,
                "messages": [{
                    "role": "user",
                    "content": (
                        "You are a market analyst. In ONE sentence (max 30 words), assess the likely "
                        "1-day stock impact of this news — direction, rough magnitude (small/medium/large), "
                        "and the key risk. No hedging boilerplate.\n\n"
                        f"Tickers: {', '.join(tickers)}\nHeadline: {headline}\nSummary: {summary[:500]}"
                    ),
                }],
            },
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"},
        )
        return resp["content"][0]["text"].strip()
    except Exception as e:
        return f"(AI analysis unavailable: {e})"


# ------------------------------ notifications -------------------------------

def send_telegram(text: str):
    if not (TG_TOKEN and TG_CHAT):
        print("--- ALERT (Telegram not configured) ---\n" + text + "\n")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        http_post_json(url, {"chat_id": TG_CHAT, "text": text,
                             "parse_mode": "HTML", "disable_web_page_preview": True})
    except Exception as e:
        print(f"[telegram] send error: {e}")


def format_alert(item, tickers, universe, score, direction, hits, ai_note):
    arrow = "🟢 BULLISH" if direction > 0 else "🔴 BEARISH" if direction < 0 else "⚪ UNCLEAR"
    names = ", ".join(f"{t} ({universe.get(t, '?')[:30]})" for t in tickers[:4])
    ts = datetime.fromtimestamp(item.get("datetime", time.time()), tz=timezone.utc)
    lines = [
        f"<b>⚡ CATALYST ALERT — impact {score}/100 {arrow}</b>",
        f"<b>Tickers:</b> {names}",
        f"<b>Catalyst type:</b> {', '.join(hits[:3]) or 'n/a'}",
        f"<b>Headline:</b> {item.get('headline','')[:200]}",
        f"<b>Time:</b> {ts:%Y-%m-%d %H:%M} UTC  <b>Source:</b> {item.get('source','?')}",
    ]
    if ai_note:
        lines.append(f"<b>AI read:</b> {ai_note}")
    if item.get("url"):
        lines.append(item["url"])
    lines.append("<i>Educational alert — already priced in by algos. Not investment advice.</i>")
    return "\n".join(lines)


# --------------------------------- main loop --------------------------------

def load_seen() -> set:
    if os.path.exists(STATE_FILE):
        return set(json.load(open(STATE_FILE)))
    return set()


def save_seen(seen: set):
    json.dump(list(seen)[-5000:], open(STATE_FILE, "w"))


def scan_once(universe: dict, seen: set) -> int:
    """One scan pass. Returns number of alerts sent."""
    items = fetch_news()
    new_alerts = 0
    for item in items:
        nid = str(item.get("id") or item.get("url"))
        if nid in seen:
            continue
        seen.add(nid)
        text = f"{item.get('headline','')} {item.get('summary','')}"
        tickers = match_tickers(item, universe)
        if not tickers:
            continue
        score, direction, hits = score_headline(text)
        if score >= ALERT_THRESHOLD:
            ai_note = ai_analysis(item.get("headline", ""), item.get("summary", ""), tickers)
            send_telegram(format_alert(item, tickers, universe, score, direction, hits, ai_note))
            new_alerts += 1
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] scanned {len(items)} items -> {new_alerts} alert(s)")
    return new_alerts


def main():
    if not FINNHUB_KEY:
        sys.exit("Missing FINNHUB_API_KEY — get a free key at https://finnhub.io and export it.")
    universe = load_nasdaq_tickers()
    seen = load_seen()
    run_once = os.environ.get("RUN_ONCE") == "1"   # set by GitHub Actions
    if run_once:
        scan_once(universe, seen)
        save_seen(seen)
        return
    print(f"Monitoring {len(universe)} NASDAQ stocks | poll every {POLL_SECONDS}s | "
          f"alert threshold {ALERT_THRESHOLD}/100 | Ctrl+C to stop.")
    while True:
        scan_once(universe, seen)
        save_seen(seen)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")

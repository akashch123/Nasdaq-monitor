# NASDAQ News Catalyst Monitor

Watches breaking market news around the clock, matches every story against the
full NASDAQ ticker list (~3,500 symbols, auto-downloaded and refreshed daily),
scores the likely price impact from 0–100, and pushes a Telegram alert to your
phone when something crosses your threshold.

## What one alert looks like

    ⚡ CATALYST ALERT — impact 90/100 🟢 BULLISH
    Tickers: XBIO (Xenetic Biosciences)
    Catalyst type: FDA approv
    Headline: Xenetic receives FDA approval for...
    Time: 2026-07-10 13:42 UTC  Source: PR Newswire
    AI read: Large positive move likely; micro-cap float means extreme volatility.
    https://...

## Setup — 10 minutes, all free

1. **Finnhub key (news feed):** sign up at finnhub.io → copy your API key.
   Free tier allows 60 calls/min; this script uses ~1/min.
2. **Telegram bot (notifications):** in Telegram, message **@BotFather** →
   `/newbot` → follow prompts → copy the bot token. Then message
   **@userinfobot** to get your numeric chat id. Finally, open a chat with
   your new bot and press Start (bots can't message you first).
3. **Optional AI analysis:** set `ANTHROPIC_API_KEY` and each alert gets a
   one-line impact read from Claude (costs a fraction of a cent per alert).

## Run

```bash
export FINNHUB_API_KEY=your_key
export TELEGRAM_BOT_TOKEN=123456:ABC...
export TELEGRAM_CHAT_ID=987654321
# optional: export ANTHROPIC_API_KEY=sk-ant-...
python3 monitor.py
```

No pip installs needed — standard library only.

Tuning via environment variables:

| Variable          | Default | Meaning                                   |
|-------------------|---------|-------------------------------------------|
| `POLL_SECONDS`    | 60      | How often to poll the news feed            |
| `ALERT_THRESHOLD` | 40      | Minimum impact score (0–100) to alert      |

Raise the threshold to 60+ if you only want the big binary events
(FDA decisions, M&A, trial results, bankruptcies).

## Running it truly 24/7

- **Your PC:** just leave it running (`nohup python3 monitor.py &` on
  Linux/Mac, or a background task on Windows).
- **Free cloud:** a GitHub Actions workflow on a 5-minute schedule, or any
  $0–5/month VPS. (Vercel's free cron only fires once per day, so it isn't
  suitable for this.)

## How the impact score works

A rule engine ranks catalysts by their empirical punch: binary regulatory
events (FDA approvals/rejections, trial results, bankruptcy) score 75–90;
M&A and takeover interest 60–85; guidance changes 65–70; contracts and
partnerships 55–60; dilutive offerings and delisting notices 60–75 bearish;
generic hype 40–50. The direction flag (bullish/bearish) comes from the same
rules. It's deliberately transparent so you can study *why* something scored
high — open `monitor.py` and read `CATALYST_RULES`.

## Honest limitations — read this

- By the time news hits any public feed, algorithmic traders have already
  repriced the stock, typically within **seconds**. This tool makes you
  *informed*, not *early*. Its real value is training your pattern
  recognition: catalyst type → reaction size.
- Keyword scoring is crude. "FDA approval" in a headline about a *competitor*
  still fires. The optional AI read helps filter these.
- Free news feeds carry a short delay and don't include every micro-cap PR.
- Nothing here is investment advice.

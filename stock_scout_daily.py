import requests
import time
from datetime import datetime

# ── Config ────────────────────────────────────────────────
TG_TOKEN = "8830612937:AAEBbvq2qKCmc02fmLKCEit-td74EHewThE"
TG_CHAT  = "7530502151"
AV_KEY   = "JU72PLHVYXR5SHTV"

WATCHLIST = [
    ("INTC", "Intel",           "Technology"),
    ("PFE",  "Pfizer",          "Healthcare"),
    ("VZ",   "Verizon",         "Telecom"),
    ("T",    "AT&T",            "Telecom"),
    ("WBA",  "Walgreens",       "Consumer"),
    ("CVS",  "CVS Health",      "Healthcare"),
    ("MRK",  "Merck",           "Healthcare"),
    ("BMY",  "Bristol-Myers",   "Healthcare"),
    ("USB",  "US Bancorp",      "Finance"),
    ("WFC",  "Wells Fargo",     "Finance"),
    ("GE",   "GE Aerospace",    "Industrials"),
    ("F",    "Ford",            "Consumer"),
    ("GM",   "General Motors",  "Consumer"),
    ("PARA", "Paramount",       "Media"),
    ("BAC",  "Bank of America", "Finance"),
    ("OXY",  "Occidental",      "Energy"),
    ("DVN",  "Devon Energy",    "Energy"),
    ("KHC",  "Kraft Heinz",     "Consumer"),
    ("BIIB", "Biogen",          "Healthcare"),
    ("DIS",  "Disney",          "Media"),
]
# ──────────────────────────────────────────────────────────


def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"})
    time.sleep(1)


def fetch_daily(ticker):
    url = (
        f"https://www.alphavantage.co/query"
        f"?function=TIME_SERIES_DAILY&symbol={ticker}"
        f"&outputsize=compact&apikey={AV_KEY}"
    )
    r = requests.get(url, timeout=10)
    d = r.json()
    ts = d.get("Time Series (Daily)")
    if not ts:
        return None
    keys = sorted(ts.keys(), reverse=True)[:14]
    return [
        {
            "date":   k,
            "open":   float(ts[k]["1. open"]),
            "high":   float(ts[k]["2. high"]),
            "low":    float(ts[k]["3. low"]),
            "close":  float(ts[k]["4. close"]),
            "volume": int(ts[k]["5. volume"]),
        }
        for k in keys
    ]


def calc_rsi(candles, period=14):
    if len(candles) < period + 1:
        return None
    closes = [c["close"] for c in reversed(candles)]
    gains = losses = 0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses += abs(diff)
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def detect_engulfing(candles):
    if len(candles) < 2:
        return None
    prev, curr = candles[1], candles[0]
    prev_body = abs(prev["close"] - prev["open"])
    curr_body = abs(curr["close"] - curr["open"])
    if curr_body < prev_body * 0.8:
        return None
    if (curr["close"] > curr["open"] and prev["close"] < prev["open"]
            and curr["open"] <= prev["close"] and curr["close"] >= prev["open"]):
        return "🟢 Bullish Engulfing"
    if (curr["close"] < curr["open"] and prev["close"] > prev["open"]
            and curr["open"] >= prev["close"] and curr["close"] <= prev["open"]):
        return "🔴 Bearish Engulfing"
    return None


def detect_trend(candles):
    if len(candles) < 3:
        return None
    c0, c1, c2 = candles[0], candles[1], candles[2]
    if c2["close"] > c1["close"] and c1["close"] < c0["close"]:
        return "🚀 Trend Reversal ↑ (Bearish → Bullish)"
    if c2["close"] < c1["close"] and c1["close"] > c0["close"]:
        return "🔻 Trend Reversal ↓ (Bullish → Bearish)"
    return None


def detect_volume_spike(candles):
    if len(candles) < 6:
        return None
    avg_vol = sum(c["volume"] for c in candles[1:6]) / 5
    ratio = candles[0]["volume"] / avg_vol
    if ratio > 1.8:
        return f"📊 Volume Spike ({ratio:.1f}x average)"
    return None


def reversal_score(signals):
    score = 0
    for s in signals:
        if "Engulfing" in s:  score += 35
        if "Reversal"  in s:  score += 30
        if "RSI"       in s:  score += 20
        if "Volume"    in s:  score += 15
    return min(score, 100)


def run_daily_report():
    print(f"[{datetime.now()}] Starting daily report...")
    date_str = datetime.now().strftime("%d %b %Y")

    send_telegram(f"📋 <b>Stock Scout — Daily Report</b>\n📅 {date_str}\n🕙 Scanning 20 beaten down stocks...\nResults incoming ⏳")

    alerts, clean = [], []

    for ticker, name, sector in WATCHLIST:
        try:
            candles = fetch_daily(ticker)
            if not candles:
                print(f"  {ticker}: no data")
                time.sleep(1.5)
                continue

            signals = []
            eng   = detect_engulfing(candles)
            trend = detect_trend(candles)
            rsi   = calc_rsi(candles)
            vol   = detect_volume_spike(candles)

            if eng:   signals.append(eng)
            if trend: signals.append(trend)
            if rsi is not None and rsi < 30:
                signals.append(f"📉 RSI Oversold ({rsi})")
            if vol:   signals.append(vol)

            latest  = candles[0]
            prev_cl = candles[1]["close"]
            chg     = round(((latest["close"] - prev_cl) / prev_cl) * 100, 2)
            score   = reversal_score(signals)

            entry = {
                "ticker": ticker, "name": name, "sector": sector,
                "close": latest["close"], "chg": chg,
                "rsi": rsi, "score": score, "signals": signals,
            }
            if signals:
                alerts.append(entry)
            else:
                clean.append(entry)

            print(f"  {ticker}: score={score} signals={signals}")
            time.sleep(1.5)

        except Exception as e:
            print(f"  {ticker}: error — {e}")
            time.sleep(1.5)

    # Send signals report
    if alerts:
        alerts.sort(key=lambda x: x["score"], reverse=True)
        msg = f"🔥 <b>Reversal Signals — {date_str}</b>\n\n"
        for a in alerts:
            arrow = "📈" if a["chg"] >= 0 else "📉"
            msg += f"<b>{a['ticker']}</b> — {a['name']} ({a['sector']})\n"
            msg += f"{arrow} ${a['close']:.2f}  {a['chg']:+.2f}%  RSI:{a['rsi'] if a['rsi'] else '—'}  Score:{a['score']}/100\n"
            for s in a["signals"]:
                msg += f"  {s}\n"
            msg += "\n"
        send_telegram(msg)
    else:
        send_telegram(f"😴 <b>No Signals Today — {date_str}</b>\nAll 20 stocks scanned. No reversal patterns detected.")

    # Send full watchlist summary
    all_stocks = alerts + clean
    summary = f"📊 <b>Full Watchlist — {date_str}</b>\n\n"
    for a in all_stocks:
        arrow = "🟢" if a["chg"] >= 0 else "🔴"
        summary += f"{arrow} <b>{a['ticker']}</b> ${a['close']:.2f} ({a['chg']:+.2f}%)  RSI:{a['rsi'] if a['rsi'] else '—'}\n"
    send_telegram(summary)

    print(f"[{datetime.now()}] Done. {len(alerts)} signals found.")


if __name__ == "__main__":
    run_daily_report()

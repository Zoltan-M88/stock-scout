import requests
import time
import json
import os
from datetime import datetime

TG_TOKEN = "8830612937:AAEBbvq2qKCmc02fmLKCEit-td74EHewThE"
TG_CHAT = "7530502151"
BALANCE = 500.0
RISK_PER_TRADE = 0.01
STOP_LOSS = 0.02
TAKE_PROFIT = 0.04
BREAK_EVEN_AT = 0.01
TRAIL_PERCENT = 0.015
MAX_TRADES = 2
SCAN_INTERVAL = 300
TRADE_START_HOUR = 8
TRADE_END_HOUR = 20
LAST_TRADE_TIME = {}
MEMORY_FILE = "bot_memory.json"
LEARN_EVERY = 10  # retrain weights every 10 trades

PAIRS = [
    "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "AVAXUSDT", "ADAUSDT", "DOTUSDT", "LINKUSDT",
    "SUIUSDT", "LTCUSDT", "ATOMUSDT", "HYPEUSDT",
    "MATICUSDT", "NEARUSDT"
]

# Signal weights — bot adjusts these automatically
DEFAULT_WEIGHTS = {
    "RSI Oversold":     3.0,
    "RSI Low":          2.0,
    "RSI Mild":         1.0,
    "EMA Cross 5m":     1.0,
    "Engulfing 5m":     2.0,
    "Engulfing 1H":     3.0,
    "Hammer 1H":        2.0,
    "Double Bottom 1H": 3.0,
    "Support Bounce":   2.0,
    "Pullback Entry":   2.0,
    "HH/HL Structure":  1.0,
    "Volume Confirmed": 1.0,
    "1H Bullish":       1.0,
    "4H Bullish":       2.0,
}

open_trades = {}
trade_history = []
total_pnl = 0.0

# ── Memory / Learning ─────────────────────────────────────
def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r") as f:
                data = json.load(f)
                return data
        except:
            pass
    return {
        "weights": DEFAULT_WEIGHTS.copy(),
        "signal_stats": {},
        "pair_stats": {},
        "hour_stats": {},
        "trade_log": [],
        "total_trades": 0,
        "min_score": 10.0
    }

def save_memory(mem):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(mem, f, indent=2)
    except:
        pass

def learn_from_trades(mem):
    log = mem["trade_log"]
    if len(log) < LEARN_EVERY:
        return mem

    tg(f"🧠 <b>Bot Learning...</b>\nAnalysing last {len(log)} trades...")

    # Update signal stats
    for entry in log:
        signals = entry.get("signals", [])
        won = entry.get("pnl", 0) > 0
        hour = entry.get("hour", 12)
        pair = entry.get("pair", "")

        for sig in signals:
            sig_key = sig.split("(")[0].strip()  # remove RSI values
            if sig_key not in mem["signal_stats"]:
                mem["signal_stats"][sig_key] = {"wins": 0, "losses": 0}
            if won:
                mem["signal_stats"][sig_key]["wins"] += 1
            else:
                mem["signal_stats"][sig_key]["losses"] += 1

        # Hour stats
        h = str(hour)
        if h not in mem["hour_stats"]:
            mem["hour_stats"][h] = {"wins": 0, "losses": 0}
        if won:
            mem["hour_stats"][h]["wins"] += 1
        else:
            mem["hour_stats"][h]["losses"] += 1

        # Pair stats
        if pair not in mem["pair_stats"]:
            mem["pair_stats"][pair] = {"wins": 0, "losses": 0}
        if won:
            mem["pair_stats"][pair]["wins"] += 1
        else:
            mem["pair_stats"][pair]["losses"] += 1

    # Adjust weights based on win rates
    weight_changes = []
    for sig_key, stats in mem["signal_stats"].items():
        total = stats["wins"] + stats["losses"]
        if total < 3:
            continue
        win_rate = stats["wins"] / total
        old_weight = mem["weights"].get(sig_key, DEFAULT_WEIGHTS.get(sig_key, 1.0))

        # Adjust weight based on win rate
        if win_rate > 0.6:
            new_weight = min(old_weight * 1.2, old_weight + 1.0)
            weight_changes.append(f"  ↑ {sig_key}: {old_weight:.1f} → {new_weight:.1f} ({win_rate*100:.0f}% WR)")
        elif win_rate < 0.35:
            new_weight = max(old_weight * 0.8, 0.1)
            weight_changes.append(f"  ↓ {sig_key}: {old_weight:.1f} → {new_weight:.1f} ({win_rate*100:.0f}% WR)")
        else:
            new_weight = old_weight
        mem["weights"][sig_key] = round(new_weight, 2)

    # Find best pairs
    best_pairs = []
    worst_pairs = []
    for pair, stats in mem["pair_stats"].items():
        total = stats["wins"] + stats["losses"]
        if total < 2:
            continue
        wr = stats["wins"] / total
        if wr > 0.6:
            best_pairs.append(f"{pair} ({wr*100:.0f}%)")
        elif wr < 0.3:
            worst_pairs.append(f"{pair} ({wr*100:.0f}%)")

    # Find best hours
    best_hours = []
    for h, stats in mem["hour_stats"].items():
        total = stats["wins"] + stats["losses"]
        if total < 2:
            continue
        wr = stats["wins"] / total
        if wr > 0.6:
            best_hours.append(f"{h}:00 ({wr*100:.0f}%)")

    # Adjust min score based on overall win rate
    all_trades = mem["trade_log"]
    if len(all_trades) >= 10:
        wins = sum(1 for t in all_trades if t.get("pnl", 0) > 0)
        overall_wr = wins / len(all_trades)
        if overall_wr < 0.35:
            mem["min_score"] = min(mem["min_score"] + 0.5, 14.0)
        elif overall_wr > 0.55:
            mem["min_score"] = max(mem["min_score"] - 0.5, 7.0)

    # Clear log after learning
    mem["trade_log"] = []

    # Send learning report
    report = f"🧠 <b>Learning Complete!</b>\n\n"
    report += f"📊 Min Score adjusted to: {mem['min_score']:.1f}\n\n"
    if weight_changes:
        report += f"<b>Weight Changes:</b>\n" + "\n".join(weight_changes[:8]) + "\n\n"
    if best_pairs:
        report += f"<b>Best Pairs:</b> {', '.join(best_pairs[:3])}\n"
    if worst_pairs:
        report += f"<b>Worst Pairs:</b> {', '.join(worst_pairs[:3])}\n"
    if best_hours:
        report += f"<b>Best Hours:</b> {', '.join(best_hours[:3])}\n"

    tg(report)
    return mem

memory = load_memory()

# ── Helper functions ───────────────────────────────────────
def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except:
        pass

def get_klines(symbol, interval="5m", limit=100):
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    r = requests.get(url, timeout=10)
    data = r.json()
    candles = []
    for d in reversed(data):
        candles.append({
            "o": float(d[1]), "h": float(d[2]),
            "l": float(d[3]), "c": float(d[4]), "v": float(d[5])
        })
    return candles

def get_price(symbol):
    url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
    r = requests.get(url, timeout=10)
    return float(r.json()["price"])

def calc_rsi(candles, period=14):
    if len(candles) < period + 1:
        return 50
    closes = list(reversed([c["c"] for c in candles]))
    gains = losses = 0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff > 0: gains += diff
        else: losses += abs(diff)
    ag = gains / period
    al = losses / period
    if al == 0: return 100
    return round(100 - (100 / (1 + ag / al)), 1)

def calc_ema(candles, period):
    closes = list(reversed([c["c"] for c in candles]))
    if len(closes) < period: return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema

def get_trend(symbol, interval="1h"):
    try:
        candles = get_klines(symbol, interval=interval, limit=60)
        ema20 = calc_ema(candles, 20)
        ema50 = calc_ema(candles, 50)
        if ema20 and ema50:
            return "bullish" if ema20 > ema50 else "bearish"
    except: pass
    return None

def get_btc_sentiment():
    try:
        candles = get_klines("BTCUSDT", interval="1h", limit=50)
        ema20 = calc_ema(candles, 20)
        ema50 = calc_ema(candles, 50)
        rsi = calc_rsi(candles)
        if ema20 and ema50:
            if ema20 > ema50 and rsi < 70: return "bullish"
            elif ema20 < ema50 or rsi > 75: return "bearish"
    except: pass
    return "neutral"

def is_trading_hours():
    hour = datetime.utcnow().hour
    return TRADE_START_HOUR <= hour < TRADE_END_HOUR

def is_good_hour():
    hour = str(datetime.utcnow().hour)
    stats = memory["hour_stats"].get(hour, {})
    total = stats.get("wins", 0) + stats.get("losses", 0)
    if total < 3: return True
    return stats.get("wins", 0) / total >= 0.35

def is_good_pair(pair):
    stats = memory["pair_stats"].get(pair, {})
    total = stats.get("wins", 0) + stats.get("losses", 0)
    if total < 3: return True
    return stats.get("wins", 0) / total >= 0.3

def detect_engulfing(candles):
    if len(candles) < 2: return None
    prev, curr = candles[1], candles[0]
    pb = abs(prev["c"] - prev["o"])
    cb = abs(curr["c"] - curr["o"])
    if cb < pb * 0.8: return None
    if curr["c"] > curr["o"] and prev["c"] < prev["o"] and curr["o"] <= prev["c"] and curr["c"] >= prev["o"]:
        return "bullish"
    return None

def detect_engulfing_1h(symbol):
    try:
        candles = get_klines(symbol, interval="1h", limit=10)
        return detect_engulfing(candles)
    except: return None

def detect_hammer(candles):
    if not candles: return False
    c = candles[0]
    body = abs(c["c"] - c["o"])
    if body == 0: return False
    lower_wick = min(c["c"], c["o"]) - c["l"]
    upper_wick = c["h"] - max(c["c"], c["o"])
    return lower_wick >= body * 2 and upper_wick <= body * 0.5 and c["c"] > c["o"]

def detect_hammer_1h(symbol):
    try:
        candles = get_klines(symbol, interval="1h", limit=5)
        return detect_hammer(candles)
    except: return False

def detect_double_bottom(symbol):
    try:
        candles = get_klines(symbol, interval="1h", limit=50)
        lows = [c["l"] for c in candles]
        closes = [c["c"] for c in candles]
        for i in range(5, 40):
            low1 = min(lows[i:i+5])
            peak = max(closes[2:i])
            low2 = min(lows[1:5])
            if low1 > 0 and abs(low1 - low2) / low1 < 0.02:
                if peak > low1 * 1.03 and closes[0] > peak * 0.98:
                    return True
        return False
    except: return False

def detect_support_bounce(symbol):
    try:
        candles = get_klines(symbol, interval="1h", limit=100)
        lows = [c["l"] for c in candles]
        curr_price = candles[0]["c"]
        support_levels = []
        for i in range(5, len(lows) - 5):
            local_low = lows[i]
            if local_low < min(lows[i-3:i]) and local_low < min(lows[i+1:i+4]):
                support_levels.append(local_low)
        for level in support_levels:
            if level > 0 and abs(curr_price - level) / level < 0.015:
                return True, level
        return False, None
    except: return False, None

def detect_pullback(candles):
    if len(candles) < 10: return False
    closes = [c["c"] for c in candles]
    recent_high = max(closes[1:10])
    if recent_high == 0: return False
    pullback_pct = (recent_high - closes[0]) / recent_high
    return 0.02 <= pullback_pct <= 0.08

def detect_hh_hl(candles):
    if len(candles) < 20: return False
    highs = [c["h"] for c in candles[:20]]
    lows = [c["l"] for c in candles[:20]]
    rh = sorted(range(len(highs)), key=lambda i: highs[i], reverse=True)[:3]
    rl = sorted(range(len(lows)), key=lambda i: lows[i])[:3]
    if len(rh) >= 2 and len(rl) >= 2:
        return highs[rh[0]] > highs[rh[1]] and lows[rl[0]] > lows[rl[1]]
    return False

def volume_confirmed(candles):
    if len(candles) < 10: return False
    avg_vol = sum(c["v"] for c in candles[1:10]) / 9
    return avg_vol > 0 and candles[0]["v"] > avg_vol * 1.2

def get_weight(signal_name):
    key = signal_name.split("(")[0].strip()
    return memory["weights"].get(key, DEFAULT_WEIGHTS.get(key, 1.0))

def get_signal(candles, symbol):
    rsi = calc_rsi(candles)
    ema9 = calc_ema(candles, 9)
    ema21 = calc_ema(candles, 21)
    trend_1h = get_trend(symbol, "1h")
    trend_4h = get_trend(symbol, "4h")

    if rsi > 55: return None, [], 0
    if trend_1h != "bullish": return None, [], 0

    score = 0.0
    reasons = []

    if rsi < 30:
        s = get_weight("RSI Oversold")
        score += s
        reasons.append(f"RSI Oversold ({rsi}) [{s:.1f}]")
    elif rsi < 40:
        s = get_weight("RSI Low")
        score += s
        reasons.append(f"RSI Low ({rsi}) [{s:.1f}]")
    else:
        s = get_weight("RSI Mild")
        score += s
        reasons.append(f"RSI ({rsi}) [{s:.1f}]")

    if ema9 and ema21 and ema9 > ema21:
        s = get_weight("EMA Cross 5m")
        score += s
        reasons.append(f"EMA Cross 5m [{s:.1f}]")

    if detect_engulfing(candles) == "bullish":
        s = get_weight("Engulfing 5m")
        score += s
        reasons.append(f"Engulfing 5m [{s:.1f}]")

    if detect_engulfing_1h(symbol) == "bullish":
        s = get_weight("Engulfing 1H")
        score += s
        reasons.append(f"Engulfing 1H [{s:.1f}]")

    if detect_hammer_1h(symbol):
        s = get_weight("Hammer 1H")
        score += s
        reasons.append(f"Hammer 1H [{s:.1f}]")

    if detect_double_bottom(symbol):
        s = get_weight("Double Bottom 1H")
        score += s
        reasons.append(f"Double Bottom 1H [{s:.1f}]")

    bouncing, level = detect_support_bounce(symbol)
    if bouncing:
        s = get_weight("Support Bounce")
        score += s
        reasons.append(f"Support Bounce [{s:.1f}]")

    if detect_pullback(candles):
        s = get_weight("Pullback Entry")
        score += s
        reasons.append(f"Pullback Entry [{s:.1f}]")

    if detect_hh_hl(candles):
        s = get_weight("HH/HL Structure")
        score += s
        reasons.append(f"HH/HL [{s:.1f}]")

    if volume_confirmed(candles):
        s = get_weight("Volume Confirmed")
        score += s
        reasons.append(f"Volume [{s:.1f}]")

    if trend_1h == "bullish":
        s = get_weight("1H Bullish")
        score += s
        reasons.append(f"1H Up [{s:.1f}]")

    if trend_4h == "bullish":
        s = get_weight("4H Bullish")
        score += s
        reasons.append(f"4H Up [{s:.1f}]")

    min_score = memory.get("min_score", 10.0)
    if score >= min_score:
        return "buy", reasons, round(score, 1)
    return None, [], round(score, 1)

def calc_trade_size():
    size = BALANCE * RISK_PER_TRADE / STOP_LOSS
    return min(max(size, 10), 100)

def check_open_trades():
    global BALANCE, total_pnl
    closed = []
    for pair, t in open_trades.items():
        try:
            p = get_price(pair)

            if not t.get("break_even") and not t.get("partial_closed"):
                if p >= t["entry"] * (1 + BREAK_EVEN_AT):
                    t["sl"] = t["entry"]
                    t["break_even"] = True
                    tg(f"🔒 <b>Break Even</b>\n{pair} SL → entry ${t['entry']:.4f}")

            if t.get("partial_closed"):
                new_trail = p * (1 - TRAIL_PERCENT)
                if new_trail > t["trail_sl"]:
                    t["trail_sl"] = new_trail
                if p <= t["trail_sl"]:
                    pnl = (p - t["entry"]) / t["entry"] * t["remaining_size"]
                    BALANCE += t["remaining_size"] + pnl
                    total_pnl += pnl
                    total_pnl_trade = pnl + t["partial_pnl"]
                    trade_history.append({"pair": pair, "pnl": total_pnl_trade})
                    memory["trade_log"].append({
                        "pair": pair, "pnl": total_pnl_trade,
                        "signals": t.get("signals", []),
                        "hour": t.get("hour", 12)
                    })
                    memory["total_trades"] += 1
                    save_memory(memory)
                    tg(f"🏁 <b>TRAIL STOP</b>\n\n<b>{pair}</b>\nExit: ${p:.4f}\nPnL: GBP{total_pnl_trade:+.2f}\nBalance: GBP{BALANCE:.2f}")
                    closed.append(pair)
                continue

            if p <= t["sl"]:
                pnl = (p - t["entry"]) / t["entry"] * t["size"]
                BALANCE += t["size"] + pnl
                total_pnl += pnl
                trade_history.append({"pair": pair, "pnl": pnl})
                memory["trade_log"].append({
                    "pair": pair, "pnl": pnl,
                    "signals": t.get("signals", []),
                    "hour": t.get("hour", 12)
                })
                memory["total_trades"] += 1
                save_memory(memory)
                be = " (BE)" if t.get("break_even") else ""
                tg(f"❌ <b>STOP LOSS{be}</b>\n\n<b>{pair}</b>\nEntry: ${t['entry']:.4f} Exit: ${p:.4f}\nPnL: GBP{pnl:+.2f}\nBalance: GBP{BALANCE:.2f}\nTotal: GBP{total_pnl:+.2f}")
                closed.append(pair)
                continue

            if p >= t["tp"]:
                partial_size = t["size"] * 0.75
                remaining_size = t["size"] * 0.25
                partial_pnl = (p - t["entry"]) / t["entry"] * partial_size
                trail_sl = p * (1 - TRAIL_PERCENT)
                BALANCE += partial_size + partial_pnl
                total_pnl += partial_pnl
                t["partial_closed"] = True
                t["partial_pnl"] = partial_pnl
                t["remaining_size"] = remaining_size
                t["trail_sl"] = trail_sl
                tg(f"✅ <b>75% TAKE PROFIT</b>\n\n<b>{pair}</b>\nEntry: ${t['entry']:.4f} Exit: ${p:.4f}\nPartial PnL: GBP{partial_pnl:+.2f}\n🔄 25% trailing @ ${trail_sl:.4f}\nBalance: GBP{BALANCE:.2f}")

            time.sleep(0.3)
        except Exception as e:
            print(f"Error {pair}: {e}")
    for pair in closed:
        del open_trades[pair]

    # Learn after every LEARN_EVERY trades
    if len(memory["trade_log"]) >= LEARN_EVERY:
        learn_from_trades(memory)
        save_memory(memory)

scan_count = 0
print(f"AI Bot starting... Balance: GBP{BALANCE}")
print(f"Current min score: {memory['min_score']}")
print(f"Current weights: {memory['weights']}")

tg(
    f"🤖 <b>AI Self-Learning Bot Started!</b>\n\n"
    f"💰 Balance: GBP{BALANCE}\n"
    f"🧠 Learns every {LEARN_EVERY} trades\n"
    f"📊 Current min score: {memory['min_score']:.1f}\n"
    f"💵 Dynamic size (1% risk)\n"
    f"🛑 SL: {STOP_LOSS*100:.0f}% | 🎯 TP: {TAKE_PROFIT*100:.0f}%\n"
    f"🔒 Break even: +{BREAK_EVEN_AT*100:.0f}%\n"
    f"⏰ Trading: {TRADE_START_HOUR}am-{TRADE_END_HOUR}pm UTC\n\n"
    f"Total trades so far: {memory['total_trades']}"
)

while True:
    try:
        check_open_trades()
        now = time.time()

        if not is_trading_hours():
            print(f"[{datetime.utcnow().strftime('%H:%M')}] Outside hours")
            time.sleep(600)
            continue

        btc_mood = get_btc_sentiment()
        if btc_mood == "bearish":
            print(f"BTC bearish — skipping")
            time.sleep(SCAN_INTERVAL)
            continue

        for pair in PAIRS:
            if pair in open_trades: continue
            if len(open_trades) >= MAX_TRADES: break
            if BALANCE < 20: break
            if pair in LAST_TRADE_TIME and now - LAST_TRADE_TIME[pair] < 900: continue
            if not is_good_pair(pair): continue
            if not is_good_hour(): continue

            try:
                candles = get_klines(pair)
                side, reasons, score = get_signal(candles, pair)
                price = candles[0]["c"]
                rsi = calc_rsi(candles)
                print(f"  {pair}: ${price:.4f} RSI:{rsi} Score:{score:.1f} Min:{memory['min_score']:.1f} Signal:{side}")
                if side == "buy":
                    trade_size = calc_trade_size()
                    sl = price * (1 - STOP_LOSS)
                    tp = price * (1 + TAKE_PROFIT)
                    open_trades[pair] = {
                        "entry": price, "size": trade_size,
                        "sl": sl, "tp": tp, "side": side,
                        "partial_closed": False, "break_even": False,
                        "signals": [r.split("[")[0].strip() for r in reasons],
                        "hour": datetime.utcnow().hour
                    }
                    BALANCE -= trade_size
                    LAST_TRADE_TIME[pair] = now
                    tg(
                        f"🟢 <b>BUY {pair}</b>\n\n"
                        f"Entry: ${price:.4f}\n"
                        f"🎯 TP: ${tp:.4f} | 🛑 SL: ${sl:.4f}\n"
                        f"💵 Size: GBP{trade_size:.0f}\n"
                        f"📊 Score: {score:.1f} (min {memory['min_score']:.1f})\n"
                        f"✅ {chr(10).join(reasons)}\n"
                        f"💰 Balance: GBP{BALANCE:.2f}"
                    )
                time.sleep(1.5)
            except Exception as e:
                print(f"  {pair} error: {e}")
                time.sleep(1.5)

        scan_count += 1
        if scan_count % 48 == 0:
            wins = len([t for t in trade_history if t["pnl"] > 0])
            total = len(trade_history)
            wr = wins / total * 100 if total > 0 else 0
            open_text = ""
            for pair, t in open_trades.items():
                try:
                    p = get_price(pair)
                    if t.get("partial_closed"):
                        unr = (p - t["entry"]) / t["entry"] * t["remaining_size"]
                        open_text += f"  {pair} TRAIL GBP{unr:+.2f}\n"
                    else:
                        unr = (p - t["entry"]) / t["entry"] * t["size"]
                        be = " BE" if t.get("break_even") else ""
                        open_text += f"  {pair}{be} GBP{unr:+.2f}\n"
                except:
                    open_text += f"  {pair}\n"
            top_weights = sorted(memory["weights"].items(), key=lambda x: x[1], reverse=True)[:5]
            weight_str = "\n".join(f"  {k}: {v:.1f}" for k, v in top_weights)
            tg(
                f"📊 <b>4-Hour Report</b>\n\n"
                f"💰 Balance: GBP{BALANCE:.2f}\n"
                f"📈 PnL: GBP{total_pnl:+.2f}\n"
                f"🎯 Win Rate: {wr:.0f}% ({wins}W/{total-wins}L)\n"
                f"📋 Trades: {total} | Min Score: {memory['min_score']:.1f}\n"
                f"📈 BTC: {btc_mood.upper()}\n\n"
                f"<b>Top Signals:</b>\n{weight_str}\n\n"
                f"<b>Open:</b>\n{open_text if open_text else 'None'}"
            )

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Done. Bal:GBP{BALANCE:.2f} Open:{len(open_trades)} Score_min:{memory['min_score']:.1f}")
        time.sleep(SCAN_INTERVAL)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(60)

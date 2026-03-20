# ==========================================================
# IBKR Wheel Strategy Scanner – CALIBRATED VERSION
# ==========================================================

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import yfinance as yf
from datetime import datetime
import math
import time  # <-- ADDED FOR DELAYS

# ==========================================================
# SYMBOL NORMALIZATION
# ==========================================================
def normalize_symbol(sym):
    sym = sym.upper().strip()
    if "." in sym:
        sym = sym.replace(".", "-")
    sym = sym.split()[0]
    return sym

# ==========================================================
# LOAD INDEX MEMBERSHIP
# ==========================================================
with open("sp500test.txt") as f:
    SP500 = set(normalize_symbol(line) for line in f if line.strip())

with open("nasdaq100test.txt") as f:
    NASDAQ100 = set(normalize_symbol(line) for line in f if line.strip())

# ==========================================================
# Math helpers
# ==========================================================
def norm_cdf(x):
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def put_delta(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return None
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1) - 1

def gamma_penalty(dte, delta, iv):
    penalty = 0
    if dte <= 10:
        penalty -= 2
    elif dte <= 14:
        penalty -= 1
    if abs(delta) < 0.20:
        penalty -= 1
    if iv >= 0.50:
        penalty += 1
    return penalty

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ==========================================================
# Score helpers
# ==========================================================
MAX_RAW_SCORE = 20

def normalise_score(raw):
    return round((raw / MAX_RAW_SCORE) * 100, 1)

def confidence_label(score):
    if score >= 85:
        return "A+"
    elif score >= 75:
        return "A"
    elif score >= 65:
        return "B"
    elif score >= 50:
        return "C"
    else:
        return "D"

# ==========================================================
# CONFIG - CALIBRATED FILTERS
# ==========================================================
CSV_FILE = "sp500test.txt"
OUTPUT_FILE = "wheel_trades_calibrated.csv"

RISK_FREE_RATE = 0.05
MIN_DTE = 7
MAX_DTE = 45
MIN_SCORE = 8  # Back to 8 (not 10)

# RELAXED liquidity requirements (based on diagnostics)
MIN_OPTION_VOLUME = 25        # Reduced from 100
MIN_OPEN_INTEREST = 100       # Reduced from 500
MAX_REL_SPREAD = 0.08         # Relaxed from 0.03

# RELAXED other filters
MIN_PREMIUM_PCT = 0.25        # Reduced from 0.5
MAX_OTM_PCT = 25.0            # Increased from 15.0
MIN_STOCK_VOLUME = 50_000     # Reduced from 100k

MIN_EARNINGS_DAYS = 20

# ==========================================================
# LOAD SYMBOLS
# ==========================================================
df = pd.read_csv(CSV_FILE)
df.columns = df.columns.str.strip()

if "Symbol" in df.columns:
    symbols = df["Symbol"].astype(str)
elif "Financial Instrument" in df.columns:
    symbols = df["Financial Instrument"].astype(str).str.split().str[0]
else:
    raise Exception(f"No usable symbol column found: {df.columns.tolist()}")

symbols = symbols.unique()
results = []

print(f"Scanning {len(symbols)} symbols...")

# ==========================================================
# MAIN LOOP
# ==========================================================
for idx, symbol in enumerate(symbols):
    if idx % 50 == 0:
        print(f"Progress: {idx}/{len(symbols)} symbols ({len(results)} trades found)")

    try:
        norm_symbol = normalize_symbol(symbol)

        stock = yf.Ticker(symbol)
        hist = stock.history(period="1y")

        if len(hist) < 200:
            time.sleep(0.5)  # <-- DELAY EVEN ON SKIP
            continue

        close = hist["Close"]
        S = close.iloc[-1]

        # Calculate averages
        sma20 = close.rolling(20).mean().iloc[-1]
        sma50 = close.rolling(50).mean().iloc[-1]

        # Calculate indicators
        rsi_val = rsi(close).iloc[-1]
        high_52w = close.rolling(252).max().iloc[-1]
        dist_from_high = (high_52w - S) / high_52w

        # Calculate historical volatility
        returns = close.pct_change().dropna()
        hv = returns.std() * math.sqrt(252)

        # Stock volume check
        avg_volume = hist["Volume"].tail(20).mean()
        if avg_volume < MIN_STOCK_VOLUME:
            time.sleep(0.5)  # <-- DELAY EVEN ON SKIP
            continue

        # ----------------------
        # HARD FILTERS (RELAXED)
        # ----------------------
        if rsi_val > 75 or rsi_val < 25:  # More permissive
            time.sleep(0.5)  # <-- DELAY EVEN ON SKIP
            continue

        if dist_from_high < 0.02:  # Slightly tighter
            time.sleep(0.5)  # <-- DELAY EVEN ON SKIP
            continue

        # ----------------------
        # Earnings filter
        # ----------------------
        earnings_ok = True
        try:
            cal = stock.calendar
            earn_date = None

            if isinstance(cal, dict):
                earn_date = cal.get("Earnings Date")
            elif hasattr(cal, "index") and "Earnings Date" in cal.index:
                earn_date = cal.loc["Earnings Date"][0]

            if earn_date is not None:
                if (earn_date.date() - datetime.today().date()).days <= MIN_EARNINGS_DAYS:
                    earnings_ok = False
        except:
            pass

        # ----------------------
        # OPTIONS
        # ----------------------
        for exp in stock.options:
            dte = (datetime.strptime(exp, "%Y-%m-%d").date() - datetime.today().date()).days
            if not (MIN_DTE <= dte <= MAX_DTE):
                continue

            try:
                chain = stock.option_chain(exp)
                puts = chain.puts.dropna()
                if puts.empty:
                    continue
            except:
                continue

            T = dte / 365

            for _, row in puts.iterrows():
                try:
                    K = row["strike"]
                    iv = row["impliedVolatility"]
                    premium = row["lastPrice"]
                    vol = row["volume"]
                    oi = row["openInterest"]
                    bid = row["bid"]
                    ask = row["ask"]

                    # CSP-only (strike below current price)
                    if K >= S:
                        continue

                    # Calculate OTM percentage
                    otm_pct = ((S - K) / S) * 100

                    # Skip strikes too far OTM
                    if otm_pct > MAX_OTM_PCT:
                        continue

                    # Calculate premium yield
                    if K <= 0:
                        continue
                    premium_pct = (premium / K) * 100

                    # Skip very low premium trades
                    if premium_pct < MIN_PREMIUM_PCT:
                        continue

                    # Relaxed liquidity filters
                    if vol < MIN_OPTION_VOLUME or oi < MIN_OPEN_INTEREST:
                        continue
                    if bid <= 0 or ask <= 0:
                        continue

                    mid = (bid + ask) / 2
                    if mid <= 0:
                        continue

                    spread_pct = (ask - bid) / mid

                    if spread_pct > MAX_REL_SPREAD:
                        continue

                    delta = put_delta(S, K, T, RISK_FREE_RATE, iv)
                    if delta is None:
                        continue

                    # Calculate IV rank vs HV
                    if hv > 0:
                        iv_rank = (iv - hv) / hv
                    else:
                        iv_rank = 0

                    # ----------------------
                    # SCORING SYSTEM
                    # ----------------------
                    score = 0

                    # 1. TREND (5 points max)
                    if S > sma50:
                        score += 2
                    if sma20 > sma50:
                        score += 2
                    if S > sma20:
                        score += 1

                    # 2. EARNINGS SAFETY (2 points)
                    if earnings_ok:
                        score += 2

                    # 3. DTE SCORING (3 points max)
                    if 21 <= dte <= 28:
                        score += 3
                    elif 14 <= dte <= 20:
                        score += 2
                    elif 28 <= dte <= 35:
                        score += 2
                    elif dte <= 10:
                        score -= 1

                    # 4. DELTA SCORING (3 points max)
                    abs_delta = abs(delta)
                    if 0.28 <= abs_delta <= 0.32:
                        score += 3
                    elif 0.25 <= abs_delta <= 0.35:
                        score += 2
                    elif 0.20 <= abs_delta <= 0.40:
                        score += 1

                    # 5. PREMIUM YIELD (2 points max)
                    if premium_pct >= 1.5:
                        score += 2
                    elif premium_pct >= 1.0:
                        score += 1
                    elif premium_pct >= 0.5:
                        score += 0.5

                    # 6. VOLATILITY REGIME (2 points max)
                    if 0.10 <= iv_rank <= 0.30:
                        score += 2
                    elif 0.30 < iv_rank <= 0.50:
                        score += 1
                    elif iv_rank > 0.60:
                        score -= 1

                    if iv >= 0.30:
                        score += 1

                    # 7. RSI POSITIONING (2 points max)
                    if 40 <= rsi_val <= 55:
                        score += 2
                    elif 35 <= rsi_val <= 60:
                        score += 1
                    elif rsi_val > 70:
                        score -= 2
                    elif rsi_val < 30:
                        score -= 1

                    # 8. INDEX MEMBERSHIP (2 points max)
                    if norm_symbol in SP500:
                        score += 2
                        index_tag = "S&P500"
                    elif norm_symbol in NASDAQ100:
                        score += 1
                        index_tag = "NASDAQ100"
                    else:
                        index_tag = "None"

                    # 9. LIQUIDITY BONUS (2 points max)
                    if vol >= 500 and oi >= 1000:
                        score += 2
                    elif vol >= 100 and oi >= 300:
                        score += 1

                    if avg_volume >= 1_000_000:
                        score += 1

                    # 10. BID-ASK SPREAD QUALITY (1 point)
                    if spread_pct <= 0.03:
                        score += 1
                    elif spread_pct >= 0.06:
                        score -= 0.5

                    # 11. OTM DISTANCE (1 point)
                    if 3 <= otm_pct <= 7:
                        score += 1
                    elif otm_pct > 15:
                        score -= 0.5

                    # 12. Gamma penalty
                    score += gamma_penalty(dte, delta, iv)

                    # Skip if below threshold
                    if score < MIN_SCORE:
                        continue

                    # Calculate returns
                    annual_return = (premium / (K * 100)) * (365 / dte) * 100
                    monthly_return = (premium / (K * 100)) * (30 / dte) * 100
                    norm = normalise_score(score)

                    results.append({
                        "Symbol": symbol,
                        "CurrentPrice": round(S, 2),
                        "Strike": K,
                        "OTM_%": round(otm_pct, 2),
                        "Expiration": exp,
                        "DTE": dte,
                        "Delta": round(delta, 2),
                        "IV_%": round(iv * 100, 1),
                        "HV_%": round(hv * 100, 1),
                        "IV_Rank": round(iv_rank, 2),
                        "Premium": round(premium, 2),
                        "PremiumYield_%": round(premium_pct, 2),
                        "MonthlyReturn_%": round(monthly_return, 2),
                        "AnnualReturn_%": round(annual_return, 2),
                        "Bid": round(bid, 2),
                        "Ask": round(ask, 2),
                        "Spread_%": round(spread_pct * 100, 2),
                        "Volume": int(vol),
                        "OpenInterest": int(oi),
                        "AvgStockVolume": int(avg_volume),
                        "RSI": round(rsi_val, 1),
                        "52W_Dist_%": round(dist_from_high * 100, 2),
                        "Index": index_tag,
                        "RawScore": round(score, 1),
                        "NormScore": norm,
                        "Grade": confidence_label(norm)
                    })

                except Exception:
                    continue

    except Exception as e:
        print(f"Failed to get ticker '{symbol}' reason: {e}")
        print(f"{symbol}: No price data found, symbol may be delisted (period=1y)")
    
    # <-- MAIN DELAY: Wait 1 second between each symbol
    time.sleep(1)

# ==========================================================
# OUTPUT
# ==========================================================
out = pd.DataFrame(results)

if not out.empty:
    out = out.sort_values(
        ["NormScore", "AnnualReturn_%"],
        ascending=[False, False]
    )

out.to_csv(OUTPUT_FILE, index=False)

print("\n" + "=" * 60)
print("IBKR WHEEL SCANNER – CALIBRATED VERSION COMPLETE")
print("=" * 60)
print(f"Total trades found: {len(out)}")




if not out.empty:
    print(f"\nScore range: {out['RawScore'].min():.1f}-{out['RawScore'].max():.1f} (raw)")
    print(f"Normalized range: {out['NormScore'].min():.1f}-{out['NormScore'].max():.1f}%")

    print(f"\nGrade distribution:")
    print(out['Grade'].value_counts().to_string())

    print(f"\nTop 10 trades by score:")
    top_cols = ['Symbol', 'Strike', 'DTE', 'Delta', 'PremiumYield_%', 'AnnualReturn_%', 'NormScore', 'Grade']
    print(out[top_cols].head(10).to_string(index=False))

    print(f"\nTop 10 trades by annualized return:")
    print(out.sort_values('AnnualReturn_%', ascending=False)[top_cols].head(10).to_string(index=False))

print("=" * 60)
print(f"Saved to: {OUTPUT_FILE}")
print("=" * 60)

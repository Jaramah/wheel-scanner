#!/usr/bin/env python3
"""
AI-Driven High-Frequency Crypto Trading Bot
Strategy : Trend-Following Momentum (BTC/USDT Perpetual Futures)
Stack    : CCXT  |  pandas-ta  |  Claude 3.5 Sonnet via OpenClaw  |  Binance Futures WebSocket
"""

import os
import sys
import json
import time
import logging
import threading
import datetime
import traceback
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

import requests
import ccxt
import pandas as pd
import pandas_ta as ta
import websocket  # websocket-client

# Load .env file if present (requires python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION  (all sensitive values via environment variables)
# ══════════════════════════════════════════════════════════════════════════════

# Exchange credentials
EXCHANGE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
EXCHANGE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
SANDBOX_MODE        = os.getenv("SANDBOX_MODE", "true").lower() == "true"

# Trading pair — USDT-margined BTC perpetual futures
SYMBOL        = "BTC/USDT:USDT"
BASE_CURRENCY = "USDT"
LEVERAGE      = int(os.getenv("LEVERAGE", "5"))

# Claude / OpenClaw local proxy
CLAUDE_API_URL = os.getenv("CLAUDE_API_URL", "http://localhost:8000/v1/chat/completions")
CLAUDE_MODEL   = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")
CLAUDE_TIMEOUT = int(os.getenv("CLAUDE_TIMEOUT", "30"))

# Telegram mobile alerts
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# Risk parameters
RISK_PER_TRADE_PCT   = float(os.getenv("RISK_PER_TRADE_PCT",   "0.01"))   # 1 % of equity
TRAILING_STOP_PCT    = float(os.getenv("TRAILING_STOP_PCT",    "0.005"))  # 0.5 % trailing
DAILY_LOSS_LIMIT_USD = float(os.getenv("DAILY_LOSS_LIMIT_USD", "100.0"))  # $100 hard cap
SLIPPAGE_LIMIT_PCT   = float(os.getenv("SLIPPAGE_LIMIT_PCT",   "0.001"))  # 0.10 % max slip

# Strategy timeframes & indicator periods
TIMEFRAME_MACRO  = "1h"
TIMEFRAME_MICRO  = "5m"
EMA_MACRO_PERIOD = 200
EMA_SHORT_PERIOD = 9
EMA_LONG_PERIOD  = 21
RSI_PERIOD       = 14
MACRO_CANDLE_LIMIT = 250   # must be > 200 for EMA warmup
MICRO_CANDLE_LIMIT = 60

# Logging
LOG_FILE = os.getenv("LOG_FILE", "trading_bot.log")

# Binance Futures mark-price WebSocket (1-second updates)
WS_URL = "wss://fstream.binance.com/ws/btcusdt@markPrice@1s"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — LOGGING
# ══════════════════════════════════════════════════════════════════════════════

class _BotFormatter(logging.Formatter):
    """Stamps each line with UTC time and a severity tag."""
    _TAGS = {
        logging.DEBUG:    "[DEBUG]",
        logging.INFO:     "[INFO]",
        logging.WARNING:  "[SKIP]",
        logging.ERROR:    "[ERROR]",
        logging.CRITICAL: "[CRITICAL]",
    }

    def format(self, record: logging.LogRecord) -> str:
        tag = self._TAGS.get(record.levelno, "[INFO]")
        ts  = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return f"{ts} {tag} {record.getMessage()}"


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("TradingBot")
    logger.setLevel(logging.DEBUG)
    fmt = _BotFormatter()

    fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


log = _setup_logging()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

class TradeDirection(Enum):
    LONG  = "LONG"
    SHORT = "SHORT"


@dataclass
class IndicatorSnapshot:
    """All pre-computed indicators that are forwarded to Claude."""
    timestamp:       str
    symbol:          str
    current_price:   float
    candle_close:    float   # last closed 5 m candle close — used for slippage check
    candle_high:     float
    candle_low:      float
    ema_200_1h:      float
    ema_9_5m:        float
    ema_21_5m:       float
    rsi_14_5m:       float
    macro_bias:      str     # "BULLISH" | "BEARISH"


@dataclass
class TradeSignal:
    action:      str    # "BUY" | "SELL" | "HOLD"
    stop_loss:   float
    take_profit: float


@dataclass
class OpenPosition:
    direction:     TradeDirection
    entry_price:   float
    stop_loss:     float
    take_profit:   float
    size:          float          # BTC quantity
    order_id:      str
    entry_time:    datetime.datetime
    peak_price:    float          # highest seen (LONG) / lowest seen (SHORT)
    trailing_stop: float          # current dynamic trailing stop level


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — TELEGRAM NOTIFIER
# ══════════════════════════════════════════════════════════════════════════════

class TelegramNotifier:
    _BASE = "https://api.telegram.org/bot"

    def __init__(self, token: str, chat_id: str) -> None:
        self.token   = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        if not self.enabled:
            log.warning("Telegram not configured — mobile alerts disabled.")

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            r = requests.post(
                f"{self._BASE}{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            r.raise_for_status()
            return True
        except Exception as exc:
            log.error(f"Telegram.send failed: {exc}")
            return False

    def send_document(self, file_path: str, caption: str = "") -> bool:
        if not self.enabled:
            return False
        try:
            with open(file_path, "rb") as fh:
                r = requests.post(
                    f"{self._BASE}{self.token}/sendDocument",
                    data={"chat_id": self.chat_id, "caption": caption},
                    files={"document": fh},
                    timeout=60,
                )
            r.raise_for_status()
            return True
        except Exception as exc:
            log.error(f"Telegram.send_document failed: {exc}")
            return False


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — LIVE PRICE FEED  (Binance Futures WebSocket, daemon thread)
# ══════════════════════════════════════════════════════════════════════════════

class LivePriceFeed:
    """
    Maintains the latest BTC/USDT mark price via Binance Futures WebSocket.
    Runs in a daemon thread and reconnects automatically with exponential back-off.
    """

    def __init__(self) -> None:
        self._price:    float = 0.0
        self._lock              = threading.Lock()
        self._running:  bool    = False
        self._thread: Optional[threading.Thread] = None

    @property
    def price(self) -> float:
        with self._lock:
            return self._price

    # ── WebSocket callbacks ───────────────────────────────────────────────

    def _on_message(self, _ws: Any, message: str) -> None:
        try:
            p = float(json.loads(message).get("p", 0))
            if p > 0:
                with self._lock:
                    self._price = p
        except Exception:
            pass

    def _on_error(self, _ws: Any, error: Any) -> None:
        log.error(f"WebSocket error: {error}")

    def _on_close(self, _ws: Any, code: Any, msg: Any) -> None:
        log.warning(f"WebSocket closed ({code}) — scheduled reconnect.")

    def _on_open(self, _ws: Any) -> None:
        log.info("WebSocket live price feed connected.")

    # ── Reconnect loop ────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        backoff = 2
        while self._running:
            try:
                ws = websocket.WebSocketApp(
                    WS_URL,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open,
                )
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:
                log.error(f"WebSocket thread exception: {exc}")
            if self._running:
                log.info(f"WebSocket reconnecting in {backoff}s…")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(
            target=self._run_loop, daemon=True, name="WSPriceFeed"
        )
        self._thread.start()
        # Block up to 6 s waiting for the first price tick
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and self.price == 0:
            time.sleep(0.1)
        if self.price == 0:
            log.warning("WebSocket: no price received within 6 s of start.")

    def stop(self) -> None:
        self._running = False


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — EXCHANGE MANAGER  (CCXT Binance USDT-M Futures)
# ══════════════════════════════════════════════════════════════════════════════

class ExchangeManager:
    """
    Thin CCXT wrapper with error handling and sandbox / live mode switching.
    Sandbox points to Binance Futures Testnet automatically via set_sandbox_mode().
    """

    def __init__(self) -> None:
        self.exchange = ccxt.binanceusdm({
            "apiKey":  EXCHANGE_API_KEY,
            "secret":  EXCHANGE_API_SECRET,
            "options": {"defaultType": "future", "adjustForTimeDifference": True},
            "enableRateLimit": True,
        })

        if SANDBOX_MODE:
            self.exchange.set_sandbox_mode(True)
            log.info("Exchange: SANDBOX / TESTNET mode active.")
        else:
            log.warning("Exchange: LIVE mode — real capital is at risk!")

        self._set_leverage()

    def _set_leverage(self) -> None:
        try:
            self.exchange.set_leverage(LEVERAGE, SYMBOL)
            log.info(f"Leverage set to {LEVERAGE}x on {SYMBOL}.")
        except Exception as exc:
            log.warning(f"set_leverage: {exc}  (may already be set correctly)")

    # ── Account ───────────────────────────────────────────────────────────

    def get_total_equity(self) -> float:
        """Total USDT equity (free + used margin)."""
        try:
            bal = self.exchange.fetch_balance()
            return float(bal.get("USDT", {}).get("total", 0.0))
        except Exception as exc:
            log.error(f"fetch_balance: {exc}")
            return 0.0

    # ── Market data ───────────────────────────────────────────────────────

    def fetch_ohlcv(self, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        """Returns a DataFrame with columns [open, high, low, close, volume] or None."""
        try:
            raw = self.exchange.fetch_ohlcv(SYMBOL, timeframe=timeframe, limit=limit)
            if not raw:
                return None
            df = pd.DataFrame(
                raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("timestamp").astype(float)
            return df
        except Exception as exc:
            log.error(f"fetch_ohlcv({timeframe}): {exc}")
            return None

    # ── Order execution ───────────────────────────────────────────────────

    def place_market_order(
        self,
        side:   str,
        amount: float,
        reduce_only: bool = False,
    ) -> Optional[Dict]:
        """Execute a market order. side='buy'|'sell'. Returns raw CCXT order or None."""
        params = {"reduceOnly": True} if reduce_only else {}
        try:
            order = self.exchange.create_market_order(SYMBOL, side, amount, params=params)
            log.info(
                f"Order filled: {side.upper()} {amount:.6f} BTC | "
                f"ID={order['id']} | avg={order.get('average')}"
            )
            return order
        except Exception as exc:
            log.error(f"create_market_order({side}, {amount}): {exc}")
            return None

    def close_position(self, position: "OpenPosition") -> bool:
        """Close an open position with a reduceOnly market order."""
        close_side = "sell" if position.direction == TradeDirection.LONG else "buy"
        order = self.place_market_order(close_side, position.size, reduce_only=True)
        return order is not None


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — INDICATOR ENGINE  (all calculations local via pandas-ta)
# ══════════════════════════════════════════════════════════════════════════════

class IndicatorEngine:
    """
    Fetches OHLCV data and computes all indicators locally.
    Claude receives only the finished numbers — no raw candle data is sent.
    """

    def __init__(self, exchange: ExchangeManager) -> None:
        self.exchange = exchange

    def compute(self, current_price: float) -> Optional[IndicatorSnapshot]:
        df_1h = self.exchange.fetch_ohlcv(TIMEFRAME_MACRO, MACRO_CANDLE_LIMIT)
        df_5m = self.exchange.fetch_ohlcv(TIMEFRAME_MICRO, MICRO_CANDLE_LIMIT)

        if df_1h is None or df_5m is None:
            log.error("OHLCV fetch failed — skipping indicator computation.")
            return None
        if len(df_1h) < EMA_MACRO_PERIOD:
            log.error(f"Insufficient 1h candles: {len(df_1h)} < {EMA_MACRO_PERIOD}.")
            return None
        if len(df_5m) < max(EMA_LONG_PERIOD, RSI_PERIOD) + 5:
            log.error(f"Insufficient 5m candles: {len(df_5m)}.")
            return None

        # ── 1H: 200 EMA ───────────────────────────────────────────────────
        ema_200_series = ta.ema(df_1h["close"], length=EMA_MACRO_PERIOD)
        if ema_200_series is None or ema_200_series.empty:
            log.error("EMA-200 computation returned empty.")
            return None
        ema_200 = float(ema_200_series.iloc[-1])

        # ── 5M: 9 EMA, 21 EMA, RSI(14) ────────────────────────────────────
        ema_9_series  = ta.ema(df_5m["close"], length=EMA_SHORT_PERIOD)
        ema_21_series = ta.ema(df_5m["close"], length=EMA_LONG_PERIOD)
        rsi_series    = ta.rsi(df_5m["close"], length=RSI_PERIOD)

        if any(
            s is None or (hasattr(s, "empty") and s.empty)
            for s in [ema_9_series, ema_21_series, rsi_series]
        ):
            log.error("5m indicator computation returned empty series.")
            return None

        ema_9  = float(ema_9_series.iloc[-1])
        ema_21 = float(ema_21_series.iloc[-1])
        rsi    = float(rsi_series.iloc[-1])

        candle_close = float(df_5m["close"].iloc[-1])
        candle_high  = float(df_5m["high"].iloc[-1])
        candle_low   = float(df_5m["low"].iloc[-1])

        macro_bias = "BULLISH" if candle_close > ema_200 else "BEARISH"

        return IndicatorSnapshot(
            timestamp     = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            symbol        = SYMBOL,
            current_price = current_price,
            candle_close  = round(candle_close, 2),
            candle_high   = round(candle_high,  2),
            candle_low    = round(candle_low,   2),
            ema_200_1h    = round(ema_200, 2),
            ema_9_5m      = round(ema_9,   2),
            ema_21_5m     = round(ema_21,  2),
            rsi_14_5m     = round(rsi,     2),
            macro_bias    = macro_bias,
        )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — CLAUDE SIGNAL ENGINE
#   System prompt is stable & long (>1 024 tokens) → qualifies for
#   Anthropic Prompt Caching.  cache_control is passed as an extra field
#   that OpenClaw forwards transparently to the Anthropic Messages API.
# ══════════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
You are a precision quantitative trading signal engine embedded inside an \
automated cryptocurrency trading system. Your sole function is to evaluate \
pre-computed technical indicator data and return a machine-parseable JSON \
trading signal. You do not fetch data, you do not call APIs, you do not \
narrate your reasoning.

────────────────────────────────────────────────────────────────────────────────
CRITICAL OUTPUT CONTRACT
────────────────────────────────────────────────────────────────────────────────
Respond with ONLY a single raw JSON object on one line. No markdown, no code \
fences, no prose, no keys other than the three specified. The output must pass \
json.loads() without preprocessing.

  {"action": "BUY"|"SELL"|"HOLD", "stop_loss": <float>, "take_profit": <float>}

• action      — must be exactly one of the three string literals above.
• stop_loss   — 2-decimal-place float; set to 0.0 for HOLD.
• take_profit — 2-decimal-place float; set to 0.0 for HOLD.
• Never emit null, None, or omit a field.

────────────────────────────────────────────────────────────────────────────────
TRADING RULES (apply in strict order)
────────────────────────────────────────────────────────────────────────────────

RULE 1 — MACRO REGIME FILTER  (absolute; overrides everything)
  • current_price  >  ema_200_1h  →  BULLISH regime  →  only BUY is valid
  • current_price  <  ema_200_1h  →  BEARISH regime  →  only SELL is valid
  • If the signal direction contradicts the regime, emit HOLD immediately.

RULE 2 — MICRO ENTRY CONDITIONS  (5-minute chart; ALL sub-rules must be true)

  BUY  (long) — requires BULLISH regime:
    2a. ema_9_5m  >  ema_21_5m             (short momentum is bullish)
    2b. rsi_14_5m is in [50, 75]           (momentum confirmed, not overbought)
    2c. current_price  >=  ema_9_5m        (price is at or above fast EMA)

  SELL (short) — requires BEARISH regime:
    2a. ema_9_5m  <  ema_21_5m             (short momentum is bearish)
    2b. rsi_14_5m is in [25, 50]           (momentum confirmed, not oversold)
    2c. current_price  <=  ema_9_5m        (price is at or below fast EMA)

  If any sub-rule fails, emit HOLD.

RULE 3 — STOP LOSS PLACEMENT
  BUY  :  stop_loss = round(candle_low_5m  * 0.997, 2)   # 0.3 % below candle low
  SELL :  stop_loss = round(candle_high_5m * 1.003, 2)   # 0.3 % above candle high

  Guard rails:
  • stop_distance = abs(current_price - stop_loss)
  • If stop_distance / current_price > 0.015  →  emit HOLD  (stop too wide)
  • If stop_distance / current_price < 0.002  →  emit HOLD  (stop too tight)

RULE 4 — TAKE PROFIT  (minimum 2 : 1 risk-reward ratio)
  BUY  :  take_profit = round(current_price + 2.0 * (current_price - stop_loss), 2)
  SELL :  take_profit = round(current_price - 2.0 * (stop_loss - current_price), 2)

────────────────────────────────────────────────────────────────────────────────
BEHAVIORAL CONSTRAINTS
────────────────────────────────────────────────────────────────────────────────
• Temperature is 0.0 — be fully deterministic; identical inputs → identical output.
• Do not add commentary, greetings, or apologies.
• The downstream system performs no pre-processing. A single extra character \
  outside the JSON object will cause a parse failure and a missed trade.
• When in doubt, emit HOLD.  Protecting capital is always correct.
"""


class ClaudeSignalEngine:
    """
    Sends indicator data to Claude 3.5 Sonnet via the OpenClaw local proxy.
    Parses and validates the strict JSON response into a TradeSignal.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', 'local')}",
        })

    def get_signal(self, snap: IndicatorSnapshot) -> Optional[TradeSignal]:
        user_content = json.dumps({
            "timestamp":       snap.timestamp,
            "symbol":          snap.symbol,
            "current_price":   snap.current_price,
            "candle_close_5m": snap.candle_close,
            "candle_high_5m":  snap.candle_high,
            "candle_low_5m":   snap.candle_low,
            "ema_200_1h":      snap.ema_200_1h,
            "ema_9_5m":        snap.ema_9_5m,
            "ema_21_5m":       snap.ema_21_5m,
            "rsi_14_5m":       snap.rsi_14_5m,
            "macro_bias":      snap.macro_bias,
        }, indent=2)

        # cache_control on the system message activates Anthropic Prompt Caching.
        # OpenClaw must forward this field verbatim to the Anthropic Messages API.
        payload = {
            "model":       CLAUDE_MODEL,
            "temperature": 0.0,
            "max_tokens":  64,
            "messages": [
                {
                    "role":          "system",
                    "content":       _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "role":    "user",
                    "content": user_content,
                },
            ],
        }

        try:
            resp = self._session.post(
                CLAUDE_API_URL, json=payload, timeout=CLAUDE_TIMEOUT
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()

            # Strip accidental markdown fences that a misconfigured proxy may add
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw   = "\n".join(lines[1:-1]).strip()

            parsed = json.loads(raw)
            action      = str(parsed.get("action", "HOLD")).upper()
            stop_loss   = float(parsed.get("stop_loss",   0.0))
            take_profit = float(parsed.get("take_profit", 0.0))

            if action not in ("BUY", "SELL", "HOLD"):
                log.error(f"Claude returned unknown action '{action}' — defaulting HOLD.")
                return TradeSignal("HOLD", 0.0, 0.0)

            log.info(
                f"Claude signal: action={action}  sl={stop_loss:.2f}  tp={take_profit:.2f}"
            )
            return TradeSignal(action, stop_loss, take_profit)

        except json.JSONDecodeError as exc:
            log.error(f"Claude JSON parse error: {exc} | raw='{resp.text[:300]}'")
        except requests.RequestException as exc:
            log.error(f"Claude API request failed: {exc}")
        except Exception as exc:
            log.error(f"ClaudeSignalEngine unexpected error: {exc}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — RISK MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class RiskManager:
    """
    Thread-safe guard that enforces:
      • 1 % per-trade position sizing
      • 0.1 % slippage filter
      • $100 / 24 h circuit breaker (resets at midnight UTC)
    """

    def __init__(self, telegram: TelegramNotifier) -> None:
        self._telegram              = telegram
        self._lock                  = threading.Lock()
        self._daily_loss:   float   = 0.0
        self._loss_date             = datetime.datetime.now(datetime.timezone.utc).date()
        self.circuit_breaker_active = False

    # ── Internal helpers ──────────────────────────────────────────────────

    def _maybe_reset_daily_loss(self) -> None:
        today = datetime.datetime.now(datetime.timezone.utc).date()
        with self._lock:
            if today > self._loss_date:
                prev = self._daily_loss
                self._daily_loss  = 0.0
                self._loss_date   = today
                log.info(f"Daily loss counter reset. Previous: ${prev:.2f}")
                if self.circuit_breaker_active:
                    self.circuit_breaker_active = False
                    log.info("Circuit breaker DEACTIVATED — new trading day.")
                    self._telegram.send(
                        "⚡ <b>Circuit Breaker Reset</b>\n"
                        "Daily loss counter reset at midnight UTC. Trading resumed."
                    )

    # ── Public interface ──────────────────────────────────────────────────

    def is_safe_to_trade(self) -> bool:
        self._maybe_reset_daily_loss()
        with self._lock:
            return not self.circuit_breaker_active

    def check_slippage(self, live_price: float, candle_close: float) -> bool:
        """Returns True when slippage is within the configured limit."""
        if candle_close == 0:
            return False
        slip = abs(live_price - candle_close) / candle_close
        if slip > SLIPPAGE_LIMIT_PCT:
            log.warning(
                f"Slippage {slip*100:.3f}% > limit {SLIPPAGE_LIMIT_PCT*100:.2f}% "
                f"(live={live_price:.2f}, close={candle_close:.2f}) — trade SKIPPED."
            )
            return False
        return True

    def calculate_position_size(
        self, equity: float, entry_price: float, stop_loss: float
    ) -> float:
        """
        Returns BTC quantity so that worst-case loss == equity * RISK_PER_TRADE_PCT.

          size = (equity × risk%) / |entry - stop_loss|
        """
        if stop_loss <= 0 or entry_price <= 0:
            return 0.0
        stop_dist = abs(entry_price - stop_loss)
        if stop_dist < 1.0:          # at least $1 of stop distance required
            return 0.0
        risk_usd = equity * RISK_PER_TRADE_PCT
        size_btc = risk_usd / stop_dist
        size_btc = round(size_btc, 3)  # Binance min step = 0.001 BTC
        log.info(
            f"Sizing: equity=${equity:.2f}  risk={RISK_PER_TRADE_PCT*100:.1f}%"
            f"  stop_dist=${stop_dist:.2f}  → {size_btc:.6f} BTC"
            f"  (notional ${size_btc * entry_price:,.2f})"
        )
        return size_btc

    def record_trade_pnl(self, pnl_usd: float) -> None:
        """Call after every trade close. Negative pnl_usd means a loss."""
        self._maybe_reset_daily_loss()
        if pnl_usd >= 0:
            log.info(f"Trade PnL: +${pnl_usd:.2f} (profit)")
            return
        loss = abs(pnl_usd)
        with self._lock:
            self._daily_loss += loss
            daily_total = self._daily_loss
            log.info(
                f"Trade PnL: -${loss:.2f} | Daily loss total: ${daily_total:.2f}"
                f" / ${DAILY_LOSS_LIMIT_USD:.2f}"
            )
            if daily_total >= DAILY_LOSS_LIMIT_USD and not self.circuit_breaker_active:
                self.circuit_breaker_active = True
                log.critical(
                    f"CIRCUIT BREAKER ACTIVATED — daily loss ${daily_total:.2f}"
                    f" >= limit ${DAILY_LOSS_LIMIT_USD:.2f}"
                )
                self._telegram.send(
                    "🚨 <b>CIRCUIT BREAKER TRIPPED</b> 🚨\n"
                    f"Daily loss limit of <b>${DAILY_LOSS_LIMIT_USD:.2f}</b> reached.\n"
                    f"Cumulative loss: <b>${daily_total:.2f}</b>\n"
                    "All new entries FROZEN until midnight UTC."
                )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — TRAILING STOP MONITOR  (daemon thread, checks every 1 second)
# ══════════════════════════════════════════════════════════════════════════════

class TrailingStopMonitor:
    """
    Watches an open position once per second using the WebSocket price.
    Moves the trailing stop up (LONG) or down (SHORT) as price improves.
    Fires a local market exit when the trailing stop or take-profit is touched.
    Claude is NOT consulted during live position management.
    """

    def __init__(
        self,
        exchange:   ExchangeManager,
        risk_mgr:   RiskManager,
        telegram:   TelegramNotifier,
        price_feed: LivePriceFeed,
    ) -> None:
        self._exchange   = exchange
        self._risk_mgr   = risk_mgr
        self._telegram   = telegram
        self._price_feed = price_feed
        self._lock       = threading.Lock()
        self._position:  Optional[OpenPosition]     = None
        self._stop_evt   = threading.Event()
        self._thread:    Optional[threading.Thread] = None

    @property
    def has_active_position(self) -> bool:
        with self._lock:
            return self._position is not None

    def start(self, position: OpenPosition) -> None:
        with self._lock:
            self._position = position
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="TrailingStop"
        )
        self._thread.start()
        log.info(
            f"Trailing stop monitor started | {position.direction.value}"
            f"  entry={position.entry_price:.2f}"
            f"  initial_ts={position.trailing_stop:.2f}"
        )

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    # ── Monitor loop ──────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                price = self._price_feed.price
                if price <= 0:
                    time.sleep(1)
                    continue

                with self._lock:
                    pos = self._position
                    if pos is None:
                        break

                    if pos.direction == TradeDirection.LONG:
                        # Ratchet trailing stop upward
                        if price > pos.peak_price:
                            pos.peak_price    = price
                            pos.trailing_stop = round(
                                pos.peak_price * (1.0 - TRAILING_STOP_PCT), 2
                            )
                        # Take-profit check
                        if price >= pos.take_profit:
                            self._exit(pos, price, "TAKE_PROFIT")
                            break
                        # Trailing stop breach
                        if price <= pos.trailing_stop:
                            self._exit(pos, price, "TRAILING_STOP")
                            break
                        # Hard stop safety net
                        if price <= pos.stop_loss:
                            self._exit(pos, price, "HARD_STOP")
                            break

                    else:  # SHORT
                        # Ratchet trailing stop downward
                        if price < pos.peak_price:
                            pos.peak_price    = price
                            pos.trailing_stop = round(
                                pos.peak_price * (1.0 + TRAILING_STOP_PCT), 2
                            )
                        if price <= pos.take_profit:
                            self._exit(pos, price, "TAKE_PROFIT")
                            break
                        if price >= pos.trailing_stop:
                            self._exit(pos, price, "TRAILING_STOP")
                            break
                        if price >= pos.stop_loss:
                            self._exit(pos, price, "HARD_STOP")
                            break

            except Exception as exc:
                log.error(f"TrailingStopMonitor loop error: {exc}\n{traceback.format_exc()}")
            time.sleep(1)

    def _exit(self, pos: OpenPosition, exit_price: float, reason: str) -> None:
        """Execute market close, compute PnL, notify."""
        success = self._exchange.close_position(pos)

        if pos.direction == TradeDirection.LONG:
            pnl_usd = (exit_price - pos.entry_price) * pos.size
        else:
            pnl_usd = (pos.entry_price - exit_price) * pos.size

        self._risk_mgr.record_trade_pnl(pnl_usd)

        emoji = "🟢" if pnl_usd >= 0 else "🔴"
        sign  = "+" if pnl_usd >= 0 else ""
        self._telegram.send(
            f"{emoji} <b>Position Closed — {reason}</b>\n"
            f"Pair: <b>{SYMBOL}</b>  {pos.direction.value}\n"
            f"Entry: {pos.entry_price:.2f}  →  Exit: <b>{exit_price:.2f}</b>\n"
            f"Size: {pos.size:.6f} BTC\n"
            f"PnL: <b>{sign}{pnl_usd:.2f} USDT</b>\n"
            f"Duration: {datetime.datetime.now(datetime.timezone.utc) - pos.entry_time}\n"
            f"Order OK: {success}"
        )
        log.info(
            f"Position closed | reason={reason} | exit={exit_price:.2f}"
            f" | pnl={sign}{pnl_usd:.2f} USDT"
        )
        with self._lock:
            self._position = None
        self._stop_evt.set()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11 — MAIN TRADING BOT  (orchestrator)
# ══════════════════════════════════════════════════════════════════════════════

class TradingBot:
    """
    Drives the full trading cycle:
      wait for 5 m candle close → compute indicators → call Claude
      → risk / slippage checks → size and execute order → hand off to TrailingStopMonitor
    """

    def __init__(self) -> None:
        log.info("═" * 68)
        log.info("AI-Driven Crypto Trading Bot — Initializing")
        log.info(f"Symbol: {SYMBOL}  |  Sandbox: {SANDBOX_MODE}  |  Leverage: {LEVERAGE}x")
        log.info(f"Risk: {RISK_PER_TRADE_PCT*100:.1f}% / trade"
                 f"  |  Daily limit: ${DAILY_LOSS_LIMIT_USD:.2f}"
                 f"  |  Trailing stop: {TRAILING_STOP_PCT*100:.2f}%")
        log.info("═" * 68)

        self.telegram   = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        self.price_feed = LivePriceFeed()
        self.exchange   = ExchangeManager()
        self.indicators = IndicatorEngine(self.exchange)
        self.claude     = ClaudeSignalEngine()
        self.risk_mgr   = RiskManager(self.telegram)
        self.ts_monitor = TrailingStopMonitor(
            self.exchange, self.risk_mgr, self.telegram, self.price_feed
        )

    # ── Timing helpers ────────────────────────────────────────────────────

    @staticmethod
    def _secs_until_next_5m_close() -> float:
        """Seconds until the next 5-minute candle closes, plus a 2 s buffer."""
        now      = datetime.datetime.now(datetime.timezone.utc)
        elapsed  = (now.minute % 5) * 60 + now.second + now.microsecond / 1e6
        return max(0.0, 300.0 - elapsed + 2.0)

    # ── Entry execution ───────────────────────────────────────────────────

    def _open_position(
        self, signal: TradeSignal, snap: IndicatorSnapshot
    ) -> bool:
        equity = self.exchange.get_total_equity()
        if equity <= 0:
            log.error("Could not fetch account equity — aborting entry.")
            return False

        entry_price = snap.current_price
        direction   = TradeDirection.LONG  if signal.action == "BUY"  else TradeDirection.SHORT
        side        = "buy"                if signal.action == "BUY"  else "sell"

        size_btc = self.risk_mgr.calculate_position_size(
            equity, entry_price, signal.stop_loss
        )
        if size_btc <= 0.0:
            log.error("Position size is 0 — aborting entry.")
            return False

        order = self.exchange.place_market_order(side, size_btc)
        if order is None:
            log.error("Order placement failed — aborting entry.")
            return False

        fill_price = float(order.get("average") or entry_price)

        # Compute initial trailing stop from actual fill price
        if direction == TradeDirection.LONG:
            init_ts = round(fill_price * (1.0 - TRAILING_STOP_PCT), 2)
        else:
            init_ts = round(fill_price * (1.0 + TRAILING_STOP_PCT), 2)

        position = OpenPosition(
            direction     = direction,
            entry_price   = fill_price,
            stop_loss     = signal.stop_loss,
            take_profit   = signal.take_profit,
            size          = size_btc,
            order_id      = str(order.get("id", "")),
            entry_time    = datetime.datetime.now(datetime.timezone.utc),
            peak_price    = fill_price,
            trailing_stop = init_ts,
        )

        self.ts_monitor.start(position)

        arrow = "🟢 LONG" if direction == TradeDirection.LONG else "🔴 SHORT"
        self.telegram.send(
            f"{arrow} <b>Trade Entry Executed</b>\n"
            f"Pair : <b>{SYMBOL}</b>\n"
            f"Entry: <b>{fill_price:.2f}</b> USDT\n"
            f"Size : {size_btc:.6f} BTC  (${size_btc * fill_price:,.2f})\n"
            f"SL   : {signal.stop_loss:.2f}  |  Init TS: {init_ts:.2f}\n"
            f"TP   : {signal.take_profit:.2f}\n"
            f"Equity risked: {RISK_PER_TRADE_PCT*100:.1f}% = ${equity * RISK_PER_TRADE_PCT:.2f}\n"
            f"Macro bias : {snap.macro_bias}\n"
            f"RSI: {snap.rsi_14_5m}  EMA9: {snap.ema_9_5m}  EMA21: {snap.ema_21_5m}"
        )
        log.info(
            f"Trade opened: {direction.value}  {size_btc:.6f} BTC @ {fill_price:.2f}"
        )
        return True

    # ── Main loop ─────────────────────────────────────────────────────────

    def run(self) -> None:
        self.price_feed.start()
        log.info(f"Price feed live.  Initial price: {self.price_feed.price:.2f} USDT")

        self.telegram.send(
            "🤖 <b>Trading Bot Online</b>\n"
            f"Symbol : {SYMBOL}\n"
            f"Mode   : {'🟡 SANDBOX' if SANDBOX_MODE else '🔴 LIVE'}\n"
            f"Leverage: {LEVERAGE}x\n"
            f"Daily loss cap: ${DAILY_LOSS_LIMIT_USD:.2f}"
        )

        while True:
            try:
                wait = self._secs_until_next_5m_close()
                log.info(f"Next 5 m candle closes in {wait:.1f} s — sleeping…")
                time.sleep(wait)

                # ── Active position check ─────────────────────────────────
                if self.ts_monitor.has_active_position:
                    log.info("Position open — skipping entry evaluation this cycle.")
                    continue

                # ── Circuit breaker ───────────────────────────────────────
                if not self.risk_mgr.is_safe_to_trade():
                    log.warning("Circuit breaker ACTIVE — all entries frozen.")
                    continue

                # ── Live price ────────────────────────────────────────────
                live_price = self.price_feed.price
                if live_price <= 0:
                    log.error("Live price unavailable — skipping cycle.")
                    continue

                # ── Compute indicators ────────────────────────────────────
                snap = self.indicators.compute(live_price)
                if snap is None:
                    log.error("Indicator computation failed — skipping cycle.")
                    continue

                log.info(
                    f"Indicators  bias={snap.macro_bias}"
                    f"  price={snap.current_price:.2f}"
                    f"  EMA200={snap.ema_200_1h:.2f}"
                    f"  EMA9={snap.ema_9_5m:.2f}"
                    f"  EMA21={snap.ema_21_5m:.2f}"
                    f"  RSI={snap.rsi_14_5m:.2f}"
                )

                # ── Slippage gate ─────────────────────────────────────────
                if not self.risk_mgr.check_slippage(live_price, snap.candle_close):
                    continue

                # ── Claude signal ─────────────────────────────────────────
                signal = self.claude.get_signal(snap)
                if signal is None:
                    log.error("Claude signal fetch failed — skipping cycle.")
                    continue

                if signal.action == "HOLD":
                    log.info("Claude: HOLD — no entry this cycle.")
                    continue

                # ── Macro alignment guard (second layer after Claude's own) ─
                if signal.action == "BUY"  and snap.macro_bias != "BULLISH":
                    log.warning("[SKIP] BUY rejected — macro bias is BEARISH.")
                    continue
                if signal.action == "SELL" and snap.macro_bias != "BEARISH":
                    log.warning("[SKIP] SELL rejected — macro bias is BULLISH.")
                    continue

                # ── Execute entry ─────────────────────────────────────────
                log.info(
                    f"Executing {signal.action} | sl={signal.stop_loss:.2f}"
                    f"  tp={signal.take_profit:.2f}"
                )
                self._open_position(signal, snap)

            except KeyboardInterrupt:
                log.info("KeyboardInterrupt — shutting down cleanly.")
                self.telegram.send("🛑 <b>Bot Stopped</b> (KeyboardInterrupt)")
                self.ts_monitor.stop()
                self.price_feed.stop()
                sys.exit(0)

            except Exception as exc:
                log.error(f"Main loop unhandled error: {exc}\n{traceback.format_exc()}")
                time.sleep(10)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12 — ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    if not EXCHANGE_API_KEY or not EXCHANGE_API_SECRET:
        log.critical(
            "BINANCE_API_KEY and BINANCE_API_SECRET must be set via environment "
            "variables or a .env file.  Exiting."
        )
        sys.exit(1)
    TradingBot().run()


if __name__ == "__main__":
    main()

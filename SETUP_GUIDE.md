# Crypto Trading Bot — Ubuntu VPS Setup Guide

> **Risk Warning**: This bot trades real financial instruments. Start with `SANDBOX_MODE=true` until you have verified every component end-to-end.

---

## 0. Prerequisites

| Item | Where to get it |
|---|---|
| Ubuntu 22.04 LTS VPS | DigitalOcean / AWS / Hetzner |
| Binance Futures Testnet keys | https://testnet.binancefuture.com |
| Telegram Bot token + Chat ID | @BotFather on Telegram |
| OpenClaw running locally | Your OpenClaw install on the same VPS |

---

## 1. Initial VPS Hardening

```bash
# Log in as root, then create a non-root user
adduser trader
usermod -aG sudo trader
# Disable root SSH (optional but recommended)
sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart sshd
# Switch to trader user for all remaining steps
su - trader
```

---

## 2. Install System Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    python3.11 python3.11-venv python3.11-dev \
    git curl tar screen htop \
    build-essential libssl-dev libffi-dev

# Confirm version
python3.11 --version   # must print 3.11.x
```

---

## 3. Clone the Repository and Set Up Python Environment

```bash
cd /home/trader
git clone https://github.com/<YOUR_USERNAME>/wheel-scanner.git
cd wheel-scanner

# Create isolated virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Upgrade pip and install all dependencies
pip install --upgrade pip wheel
pip install -r requirements_bot.txt
```

> **pandas-ta compatibility note**: If you see `AttributeError: 'DataFrame' object has no attribute 'append'` after installing, run:
> ```bash
> pip uninstall pandas-ta -y
> pip install git+https://github.com/twopirllc/pandas-ta.git@main
> ```

---

## 4. Configure Environment Variables

```bash
cd /home/trader/wheel-scanner

# Copy the example file and edit it with your real values
cp .env.example .env
nano .env
```

Fill in every value.  The minimum required set:

```
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
SANDBOX_MODE=true          # keep true until paper-testing is complete
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Protect the file:
```bash
chmod 600 .env
```

---

## 5. Verify the Setup (Dry Run)

```bash
source venv/bin/activate

# Quick connectivity test — prints the live price and exits
python3 - <<'EOF'
import ccxt, os
from dotenv import load_dotenv
load_dotenv()
ex = ccxt.binanceusdm({"enableRateLimit": True})
ex.set_sandbox_mode(os.getenv("SANDBOX_MODE","true") == "true")
ticker = ex.fetch_ticker("BTC/USDT:USDT")
print(f"BTC/USDT mark price: {ticker['last']:.2f}")
print("Exchange connectivity OK.")
EOF
```

Expected output:
```
BTC/USDT mark price: 67842.10
Exchange connectivity OK.
```

---

## 6. Launch the Bot in a `screen` Session

```bash
# Start a persistent named screen session
screen -S tradingbot

# Inside the screen session:
cd /home/trader/wheel-scanner
source venv/bin/activate
python bot.py
```

**Key screen commands:**
| Action | Keys |
|---|---|
| Detach (leave bot running) | `Ctrl+A` then `D` |
| Reattach to session | `screen -r tradingbot` |
| List all sessions | `screen -ls` |
| Kill the session | `screen -X -S tradingbot quit` |

---

## 7. Configure the Weekly Log Backup Cron Job

```bash
# Make the script executable
chmod +x /home/trader/wheel-scanner/send_weekly_log.sh
```

The script reads credentials directly from `/home/trader/wheel-scanner/.env`, so **no `/etc/environment` changes are needed**. The cron entry is therefore minimal:

```bash
# Open the crontab editor
crontab -e
```

Add this line at the bottom:

```cron
# Weekly log backup — every Sunday at 00:00 UTC
0 0 * * 0 /home/trader/wheel-scanner/send_weekly_log.sh >> /home/trader/wheel-scanner/backup_cron.log 2>&1
```

Verify the cron job is registered:
```bash
crontab -l
```

Test the script manually before relying on cron:
```bash
bash /home/trader/wheel-scanner/send_weekly_log.sh
```

---

## 8. Monitor the Bot

```bash
# Tail the live log (from any terminal or reattached screen)
tail -f /home/trader/wheel-scanner/trading_bot.log

# Watch only errors and circuit-breaker events
grep -E "\[ERROR\]|\[CRITICAL\]|\[SKIP\]" trading_bot.log | tail -30

# Check if bot process is running
ps aux | grep bot.py

# Check log rotation files (bot rotates at 10 MB, keeps 14 files ≈ 140 MB max)
ls -lh /home/trader/wheel-scanner/trading_bot.log*
```

> **Log rotation** is handled automatically by Python's `RotatingFileHandler` (10 MB per file, 14 backups). No separate `logrotate` configuration is needed. The weekly cron backup captures the active log file before rotation discards it.

---

## 9. Going Live (Removing Sandbox Mode)

Work through this checklist **in order** before changing `SANDBOX_MODE=false`:

- [ ] Bot ran on testnet for at least 2 weeks without crashes
- [ ] Circuit breaker fires and halts entries correctly (test by temporarily setting `DAILY_LOSS_LIMIT_PCT=0.001` so a tiny loss triggers it)
- [ ] Trailing stop exits positions correctly on testnet
- [ ] Telegram notifications arrive reliably
- [ ] Weekly backup cron ran successfully at least once
- [ ] You have reviewed the open positions in your Binance Futures dashboard and they match the bot's log
- [ ] You understand that **real money** is now at risk and 1 % per trade can still compound into significant losses

When ready:
```bash
nano /home/trader/wheel-scanner/.env
# Change:  SANDBOX_MODE=false
# Restart bot:
screen -r tradingbot
# Ctrl+C to stop, then:
python bot.py
```

---

## 10. Auto-Restart on Reboot (Optional)

If you want the bot to restart automatically after a VPS reboot:

```bash
# Create a systemd service (more reliable than @reboot cron)
sudo nano /etc/systemd/system/tradingbot.service
```

Paste:
```ini
[Unit]
Description=AI Crypto Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=trader
WorkingDirectory=/home/trader/wheel-scanner
EnvironmentFile=/home/trader/wheel-scanner/.env
ExecStart=/home/trader/wheel-scanner/venv/bin/python /home/trader/wheel-scanner/bot.py
Restart=on-failure
RestartSec=30
StandardOutput=append:/home/trader/wheel-scanner/trading_bot.log
StandardError=append:/home/trader/wheel-scanner/trading_bot.log

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable tradingbot
sudo systemctl start tradingbot
sudo systemctl status tradingbot
```

> **Note**: When running as a systemd service, the `screen` session is no longer needed. You can still `tail -f trading_bot.log` to monitor output.

---

## 11. Quick Reference — Environment Variables

| Variable | Default | Description |
|---|---|---|
| `BINANCE_API_KEY` | — | Binance API key (required) |
| `BINANCE_API_SECRET` | — | Binance API secret (required) |
| `SANDBOX_MODE` | `true` | `true` = testnet, `false` = live |
| `LEVERAGE` | `5` | Requested futures leverage |
| `MAX_LEVERAGE` | `20` | Hard cap — bot clamps `LEVERAGE` down to this value |
| `CLAUDE_API_URL` | `http://localhost:8000/v1/chat/completions` | OpenClaw proxy URL |
| `CLAUDE_MODEL` | `claude-3-5-sonnet-20241022` | Model name forwarded to Anthropic |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | Telegram chat / channel ID |
| `RISK_PER_TRADE_PCT` | `0.01` | Fraction of equity risked per trade |
| `TRAILING_STOP_PCT` | `0.005` | Trailing stop distance (0.5%) |
| `DAILY_LOSS_LIMIT_PCT` | `0.03` | Circuit breaker threshold as fraction of startup equity (3%) |
| `SLIPPAGE_LIMIT_PCT` | `0.001` | Max allowed slippage before skipping (0.1%) |
| `LOG_FILE` | `trading_bot.log` | Path to the rolling log file |

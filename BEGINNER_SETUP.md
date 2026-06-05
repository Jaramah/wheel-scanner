# 🤖 Beginner Setup Guide — AI Crypto Trading Bot
### Read this if you have never used a Linux server before

> **Before you start**: This bot uses real (or test) money. Every step below uses
> **Testnet / Paper money** until YOU decide to go live. Take your time.

---

## What You'll Need (Checklist)

Before starting, make sure you have these five things:

| # | What | Where to get it | Free? |
|---|------|-----------------|-------|
| 1 | A computer (Windows, Mac, or Linux) | You already have this | ✅ |
| 2 | A DigitalOcean account | https://digitalocean.com | Free to sign up |
| 3 | A Binance account (Testnet) | https://testnet.binancefuture.com | ✅ Free |
| 4 | A Telegram account | https://telegram.org | ✅ Free |
| 5 | An Anthropic API key | https://console.anthropic.com | Pay-as-you-go |

---

## PART 1 — Create Your Server (VPS)

A VPS is just a computer in the cloud that runs 24/7 even when your laptop is off.

### Step 1.1 — Sign up for DigitalOcean

1. Go to **https://digitalocean.com**
2. Click **Sign Up**
3. Enter your email and a strong password
4. Verify your email
5. Add a payment method (credit card — you won't be charged yet)

### Step 1.2 — Create a Server (called a "Droplet")

1. Once logged in, click the green **Create** button at the top
2. Click **Droplets**
3. Choose these settings:

   | Setting | Value |
   |---------|-------|
   | **Region** | Choose the one closest to you |
   | **Image (OS)** | Ubuntu 22.04 LTS x64 |
   | **Size** | Basic → Regular → **$6/month** (1 GB RAM is enough) |
   | **Authentication** | Password → type a strong root password and save it |

4. Scroll down and click **Create Droplet**
5. Wait about 60 seconds — you will see a green dot and an IP address like `134.122.88.10`

> 📌 **Write down your server IP address** — you'll need it in the next step.

---

## PART 2 — Connect to Your Server

You talk to the server by typing commands into a "terminal" (black window with text).

### Step 2.1 — Open a Terminal

**On Windows:**
- Press `Windows key + R`, type `cmd`, press Enter
- OR install the free app **PuTTY** from https://putty.org (easier for beginners)

**On Mac:**
- Press `Cmd + Space`, type `Terminal`, press Enter

**On Linux:**
- Press `Ctrl + Alt + T`

### Step 2.2 — Connect to your server via SSH

Type this command (replace `YOUR_SERVER_IP` with the actual IP address from Step 1.2):

```bash
ssh root@YOUR_SERVER_IP
```

Example:
```bash
ssh root@134.122.88.10
```

- It will ask: **"Are you sure you want to continue connecting?"** → Type `yes` and press Enter
- It will ask for your password → Type the password you set in Step 1.2 (you won't see it typing — that's normal)
- Press Enter

✅ If you see a prompt that looks like `root@ubuntu-s-1vcpu-1gb:~#` — you're in!

---

## PART 3 — Set Up the Server

You only need to do this once. Copy and paste each command exactly.

> 💡 **How to paste** in a terminal:
> - Windows CMD: Right-click
> - Windows PuTTY: Right-click
> - Mac Terminal: Cmd+V
> - Linux Terminal: Ctrl+Shift+V

### Step 3.1 — Create a safe user (don't run everything as root)

```bash
adduser trader
```
- It will ask for a password → choose something strong and remember it
- For "Full name" and other questions → just press Enter to skip

```bash
usermod -aG sudo trader
```
This gives your new user admin powers when needed.

### Step 3.2 — Update the server software

```bash
apt update && apt upgrade -y
```
This may take 1–2 minutes. Wait for it to finish.

### Step 3.3 — Install required tools

```bash
apt install -y python3.11 python3.11-venv python3.11-dev git curl screen nano
```

Check Python installed correctly:
```bash
python3.11 --version
```
You should see something like: `Python 3.11.9`

### Step 3.4 — Switch to your trader user

```bash
su - trader
```

Your prompt will change to `trader@ubuntu-s-1vcpu-1gb:~$` — that's correct.

---

## PART 4 — Download the Bot

### Step 4.1 — Clone the code from GitHub

```bash
cd /home/trader
git clone https://github.com/jaramah/wheel-scanner.git
cd wheel-scanner
```

You should now be inside the bot's folder. Check:
```bash
ls
```
You should see files like: `bot.py`, `.env.example`, `requirements_bot.txt`, etc.

### Step 4.2 — Create a Python virtual environment

A virtual environment keeps this bot's libraries separate from everything else on the server.

```bash
python3.11 -m venv venv
```

Activate it (you need to do this every time you log in):
```bash
source venv/bin/activate
```

Your prompt will change to show `(venv)` at the start — like `(venv) trader@ubuntu:~$` — this means it's active.

### Step 4.3 — Install the bot's libraries

```bash
pip install --upgrade pip wheel
pip install -r requirements_bot.txt
```

This will take 2–3 minutes. Lots of text will scroll by — that's normal. Wait for it to finish.

> ⚠️ **If you see an error about `pandas-ta`**, run this instead:
> ```bash
> pip uninstall pandas-ta -y
> pip install git+https://github.com/twopirllc/pandas-ta.git@4af9a68
> ```

---

## PART 5 — Get Your API Keys

You need three sets of credentials. Follow each sub-section.

---

### 5A — Binance Futures Testnet Keys (Fake money — start here!)

1. Go to **https://testnet.binancefuture.com**
2. Click **Log In** → Sign up with your email if you don't have an account
3. Once logged in, look for a button called **API Management** (usually top right menu)
4. Click **Create API**
5. Give it a name like `tradingbot`
6. Copy the **API Key** and **Secret Key** — save them in a text file on your computer
7. Make sure **Futures Trading** permission is enabled

> 🔑 **Testnet keys only work on the testnet** — they cannot touch real money.

---

### 5B — Telegram Bot Setup

You'll get notifications on your phone through a Telegram bot you create.

**Step 1 — Create the bot:**
1. Open Telegram on your phone or computer
2. Search for **@BotFather** (it has a blue checkmark)
3. Send it the message: `/newbot`
4. It will ask for a name — type anything, like: `My Trading Bot`
5. It will ask for a username — must end in `bot`, like: `mytrading123bot`
6. BotFather will reply with a **token** that looks like: `7123456789:ABCxyz...`
7. **Copy and save this token** — this is your `TELEGRAM_BOT_TOKEN`

**Step 2 — Get your Chat ID:**
1. Search for **@userinfobot** in Telegram
2. Send it any message (e.g. `/start`)
3. It will reply with your **ID number** like `123456789`
4. **Save this number** — this is your `TELEGRAM_CHAT_ID`

**Step 3 — Start your bot:**
1. In Telegram, search for the bot name you created (e.g. `mytrading123bot`)
2. Click **Start** — this lets the bot send you messages

---

### 5C — Anthropic API Key (for Claude)

The bot uses Claude AI via a local proxy called OpenClaw.

1. Go to **https://console.anthropic.com**
2. Sign up or log in
3. Click **API Keys** in the left menu
4. Click **Create Key**, give it a name
5. Copy the key — it starts with `sk-ant-...`
6. Save it

> 📌 You will also need to have **OpenClaw running on your server**. OpenClaw is a local
> proxy that accepts the OpenAI API format and forwards it to Anthropic. If you don't have
> it set up yet, ask for separate OpenClaw setup instructions. The bot cannot work without it.

---

## PART 6 — Configure the Bot

### Step 6.1 — Create your configuration file

Make sure you are in the bot folder and venv is active:
```bash
cd /home/trader/wheel-scanner
source venv/bin/activate
```

Create your personal config file by copying the example:
```bash
cp .env.example .env
```

Open it to edit:
```bash
nano .env
```

You will see a file that looks like this:
```
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_API_SECRET=your_binance_api_secret_here
...
```

### Step 6.2 — Fill in your values

Using the arrow keys, navigate to each line and replace the placeholder text with your real values.

Here is what each line means:

```
BINANCE_API_KEY=         ← Paste your Binance Testnet API Key here
BINANCE_API_SECRET=      ← Paste your Binance Testnet Secret Key here
SANDBOX_MODE=true        ← LEAVE AS true until you are confident it works
LEVERAGE=5               ← Start with 5x leverage (safe default)
MAX_LEVERAGE=20          ← Bot will never exceed 20x even if you mistype
CLAUDE_API_URL=http://localhost:8000/v1/chat/completions   ← Leave as-is
CLAUDE_MODEL=claude-3-5-sonnet-20241022                    ← Leave as-is
OPENAI_API_KEY=          ← Paste your Anthropic API key here
TELEGRAM_BOT_TOKEN=      ← Paste your Telegram bot token here
TELEGRAM_CHAT_ID=        ← Paste your numeric Telegram chat ID here
RISK_PER_TRADE_PCT=0.01  ← 1% of your balance per trade — leave as-is
TRAILING_STOP_PCT=0.005  ← 0.5% trailing stop — leave as-is
DAILY_LOSS_LIMIT_PCT=0.03← Stop trading if you lose 3% of balance today
SLIPPAGE_LIMIT_PCT=0.001 ← Skip trade if price moved more than 0.1%
LOG_FILE=trading_bot.log ← Leave as-is
```

**When done editing:**
- Press `Ctrl + X`
- Press `Y` (to confirm save)
- Press `Enter`

### Step 6.3 — Protect your credentials file

```bash
chmod 600 .env
```

This makes the file only readable by you.

### Step 6.4 — Test that everything connects

Run this quick test (copy the whole block and paste it):

```bash
python3 - <<'EOF'
import ccxt, os
from dotenv import load_dotenv
load_dotenv()
ex = ccxt.binanceusdm({
    "apiKey": os.getenv("BINANCE_API_KEY"),
    "secret": os.getenv("BINANCE_API_SECRET"),
    "enableRateLimit": True
})
ex.set_sandbox_mode(True)
ticker = ex.fetch_ticker("BTC/USDT:USDT")
print(f"✅ Exchange connected! BTC price: {ticker['last']:.2f}")
EOF
```

If you see something like `✅ Exchange connected! BTC price: 67842.10` — it's working.

If you see an error — double-check your API key and secret in `.env`.

---

## PART 7 — Run the Bot

### Step 7.1 — Start a "screen" session

`screen` lets the bot keep running even after you close your terminal or disconnect.

```bash
screen -S tradingbot
```

Your terminal will clear and look the same — that's normal. You are now inside a screen session.

### Step 7.2 — Start the bot

```bash
cd /home/trader/wheel-scanner
source venv/bin/activate
python bot.py
```

You should see startup messages like:
```
2025-01-15 10:32:01 UTC [INFO] ════════════════════════════════
2025-01-15 10:32:01 UTC [INFO] AI-Driven Crypto Trading Bot — Initializing
2025-01-15 10:32:01 UTC [INFO] Symbol: BTC/USDT:USDT  |  Sandbox: True  |  Leverage: 5x
2025-01-15 10:32:02 UTC [INFO] Exchange credential validation: OK
2025-01-15 10:32:02 UTC [INFO] Price feed live.  Initial price: 67842.10 USDT
2025-01-15 10:32:02 UTC [INFO] Startup: no open position found — clean state.
2025-01-15 10:32:02 UTC [INFO] Next 5 m candle closes in 187.3 s — sleeping…
```

And you should get a Telegram message on your phone saying the bot is online! 🎉

### Step 7.3 — Detach from screen (leave bot running)

Press these keys in order:
1. Hold `Ctrl` and press `A`
2. Release both, then press `D`

You will see `[detached from ...]` and return to the normal terminal. **The bot is still running in the background.**

### Step 7.4 — Come back to check the bot later

To reconnect to the running bot at any time:
```bash
screen -r tradingbot
```

To see all running screen sessions:
```bash
screen -ls
```

To stop the bot:
1. `screen -r tradingbot` (reconnect)
2. Press `Ctrl + C` (stops the bot)

---

## PART 8 — Watch Your Bot Work

### Reading the log file

The bot writes every action to a file called `trading_bot.log`. Open a second terminal window and watch it live:

```bash
tail -f /home/trader/wheel-scanner/trading_bot.log
```

**What the tags mean:**

| Tag | Meaning |
|-----|---------|
| `[INFO]` | Normal activity — candle closed, indicators calculated, etc. |
| `[SKIP]` | Trade skipped — slippage too high, wrong macro bias, etc. |
| `[ERROR]` | Something went wrong but the bot kept running |
| `[CRITICAL]` | Circuit breaker tripped — losses hit the daily limit |

### Typical log output when no trade is taken:
```
[INFO] Next 5 m candle closes in 187.3 s — sleeping…
[INFO] Indicators  bias=BEARISH  price=67842.10  EMA200=68100.00  RSI=44.20
[INFO] Claude: HOLD — no entry this cycle.
```

### Typical log output when a trade fires:
```
[INFO] Claude signal: action=BUY  sl=67630.00  tp=68482.00
[INFO] Sizing: equity=$1000.00  risk=1.0%  stop_dist=$212.10  → 0.047 BTC
[INFO] Trade opened: LONG  0.047 BTC @ 67842.10
```

---

## PART 9 — Set Up the Weekly Log Backup

This sends a compressed copy of your log to Telegram every Sunday automatically.

### Step 9.1 — Make the backup script executable

```bash
chmod +x /home/trader/wheel-scanner/send_weekly_log.sh
```

### Step 9.2 — Test it manually first

```bash
bash /home/trader/wheel-scanner/send_weekly_log.sh
```

You should receive a file in Telegram within 10 seconds.

### Step 9.3 — Schedule it to run automatically every Sunday

```bash
crontab -e
```

If it asks which editor to use, type `1` and press Enter (this selects nano).

Scroll to the bottom of the file and add this exact line:

```
0 0 * * 0 /home/trader/wheel-scanner/send_weekly_log.sh >> /home/trader/wheel-scanner/backup_cron.log 2>&1
```

Save and exit: `Ctrl+X` → `Y` → `Enter`

Verify it was saved:
```bash
crontab -l
```

---

## PART 10 — Auto-Restart After Reboot (Recommended)

If your VPS restarts, you want the bot to come back automatically.

### Step 10.1 — Create the service file

```bash
sudo nano /etc/systemd/system/tradingbot.service
```

Paste this exactly (use Ctrl+Shift+V to paste):

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

Save: `Ctrl+X` → `Y` → `Enter`

### Step 10.2 — Enable and start the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable tradingbot
sudo systemctl start tradingbot
```

### Step 10.3 — Check it's running

```bash
sudo systemctl status tradingbot
```

You should see `Active: active (running)` in green.

> ℹ️ When using systemd, you don't need the `screen` session anymore.
> The service manages the bot automatically.

---

## PART 11 — Going Live With Real Money

**Only do this after running on Testnet for at least 2 weeks with no problems.**

### Checklist before switching to live:

- [ ] Bot ran on testnet for 14+ days without crashing
- [ ] You received Telegram alerts when trades opened and closed
- [ ] The circuit breaker tested correctly
- [ ] You understand you can lose real money
- [ ] You have reviewed all open positions in Binance and they match the log

### How to switch:

1. Edit your config:
   ```bash
   nano /home/trader/wheel-scanner/.env
   ```
2. Change: `SANDBOX_MODE=true` → `SANDBOX_MODE=false`
3. **Also change your API keys** to your LIVE Binance keys (not testnet keys)
4. Save and restart the bot:
   ```bash
   sudo systemctl restart tradingbot
   ```

---

## Troubleshooting — Common Problems

### "Permission denied" when running commands
Add `sudo` before the command:
```bash
sudo apt install something
```

### "command not found: python"
Use `python3.11` instead of `python`:
```bash
python3.11 bot.py
```

### "ModuleNotFoundError: No module named 'ccxt'"
Your virtual environment is not active. Run:
```bash
source /home/trader/wheel-scanner/venv/bin/activate
```

### Bot is not sending Telegram messages
- Check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
- Make sure you sent `/start` to your bot in Telegram
- Test manually:
  ```bash
  curl -s "https://api.telegram.org/bot<YOUR_TOKEN>/sendMessage?chat_id=<YOUR_CHAT_ID>&text=Hello"
  ```
  Replace `<YOUR_TOKEN>` and `<YOUR_CHAT_ID>` with your values. You should see `"ok":true`.

### "Authentication failed" on startup
Your Binance API keys are wrong or expired. Go back to Step 5A and create new ones.

### Bot shows [SKIP] every cycle
This is normal — the bot only trades when all conditions align (macro trend + momentum + RSI).
It may wait hours between trades. This is by design.

### I closed my terminal and the bot stopped
If you used `screen`, it should still be running. Try:
```bash
screen -r tradingbot
```
If it's not there, restart with:
```bash
screen -S tradingbot
source /home/trader/wheel-scanner/venv/bin/activate
python /home/trader/wheel-scanner/bot.py
```

---

## Quick Command Reference

| What you want to do | Command |
|---------------------|---------|
| Connect to server | `ssh trader@YOUR_SERVER_IP` |
| Activate Python environment | `source /home/trader/wheel-scanner/venv/bin/activate` |
| Start the bot (screen) | `screen -S tradingbot` then `python bot.py` |
| Detach from screen | `Ctrl+A` then `D` |
| Reconnect to bot screen | `screen -r tradingbot` |
| Watch the log live | `tail -f /home/trader/wheel-scanner/trading_bot.log` |
| See only errors | `grep ERROR /home/trader/wheel-scanner/trading_bot.log` |
| Stop the bot | `Ctrl+C` (when screen is attached) |
| Restart the service | `sudo systemctl restart tradingbot` |
| Check service status | `sudo systemctl status tradingbot` |
| Edit config | `nano /home/trader/wheel-scanner/.env` |
| Test backup script | `bash /home/trader/wheel-scanner/send_weekly_log.sh` |

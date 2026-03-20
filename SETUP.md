# George Setup Guide

You need 3 things: a Telegram bot, a Claude API key, and your Raspberry Pi.

---

## Step 1: Create Your Telegram Bot

This is how George will talk to you — through Telegram on your phone.

1. Open Telegram on your phone
2. Search for **@BotFather** and open a chat with it
3. Send `/newbot`
4. BotFather asks: "What name for your bot?" — Type `George` (or whatever you want displayed)
5. BotFather asks: "Choose a username" — Type something unique like `george_pa_bot` (must end in `bot`)
6. BotFather gives you a **token** that looks like `7123456789:AAF1234abcd5678efgh` — **copy this, you'll need it**

Now get your Telegram user ID (so George only responds to YOU):

1. In Telegram, search for **@userinfobot** and open a chat
2. Send `/start`
3. It replies with your **user ID** — a number like `123456789` — **copy this too**

---

## Step 2: Get a Claude API Key

This is how George thinks — he uses Claude to analyze your finances.

1. Go to https://console.anthropic.com
2. Create an account (or log in)
3. Go to **API Keys** in the left sidebar
4. Click **Create Key**
5. Name it `george` and click **Create**
6. **Copy the key** — it starts with `sk-ant-` — you only see it once

You need to add credit to your account:
1. Go to **Billing** in the left sidebar
2. Add a payment method
3. Add $5-10 to start (George's default budget is $20/month, but most queries cost fractions of a cent)

---

## Step 3: Set Up the Raspberry Pi

### 3a. First-time Pi setup (if brand new)

1. On your Windows PC, download **Raspberry Pi Imager** from https://www.raspberrypi.com/software/
2. Insert your microSD card into your PC
3. Open Raspberry Pi Imager
4. Click **Choose OS** → **Raspberry Pi OS (64-bit)**
5. Click **Choose Storage** → select your SD card
6. Click the **gear icon** (bottom right) — this is important:
   - Check **Enable SSH** and set a password
   - Check **Set username and password** — pick something you'll remember (e.g., `pi` / `yourpassword`)
   - Check **Configure wireless LAN** — enter your WiFi name and password
   - Set your locale/timezone
7. Click **Save**, then **Write** — wait for it to finish
8. Put the SD card in your Pi and plug it in

### 3b. Connect to your Pi from Windows

1. Wait 1-2 minutes for the Pi to boot
2. Open **PowerShell** on your Windows PC
3. Type: `ssh pi@raspberrypi.local` (use the username you set)
4. Type `yes` when asked about fingerprint
5. Enter your password

You're now on the Pi. Everything below happens in this terminal.

### 3c. Get the code onto the Pi

If you have a GitHub repo:
```bash
git clone https://github.com/YOUR_USERNAME/PA.git ~/pa
```

If not, from your **Windows PC** (new PowerShell window):
```bash
scp -r C:\Dev\PA pi@raspberrypi.local:~/pa
```

### 3d. Run the setup script

Back in your **Pi SSH terminal**:
```bash
cd ~/pa
bash deploy/setup-pi.sh
```

This takes 5-10 minutes. It installs Python, dependencies, Playwright browser, and creates a system service.

---

## Step 4: Configure George

Still on the Pi:

### 4a. Add your API keys

```bash
nano ~/pa/.env
```

Replace the placeholder values:
```
PA_TELEGRAM_TOKEN=7123456789:AAF1234abcd5678efgh
PA_CLAUDE_API_KEY=sk-ant-api03-xxxxx
```

Save: press `Ctrl+O`, then `Enter`, then `Ctrl+X`

### 4b. Add your personal info

```bash
nano ~/pa/config.json
```

Change these values:
```json
{
  "telegram_user_id": 123456789,
  "monthly_income": 4500.0,
  "financial_goals": ["pay off credit cards", "build emergency fund"],
  "cost_cap_monthly_usd": 20.0
}
```

- `telegram_user_id` — the number you got from @userinfobot
- `monthly_income` — your monthly take-home pay
- `financial_goals` — whatever you want George to focus on
- `cost_cap_monthly_usd` — max George will spend on Claude API per month

Save: `Ctrl+O`, `Enter`, `Ctrl+X`

---

## Step 5: Start George

```bash
sudo systemctl start pa
```

Check that it's running:
```bash
journalctl -u pa -f
```

You should see startup messages. Press `Ctrl+C` to stop watching logs.

---

## Step 6: First Chat with George

1. Open Telegram on your phone
2. Find your bot (search for the username you picked, like `george_pa_bot`)
3. George should have sent you a welcome message
4. Send `/unlock` and set your master password — this encrypts your saved credentials
5. Send `/help` to see what George can do

---

## Common Commands

| Command | What it does |
|---------|-------------|
| `/unlock` | Enter master password to activate George |
| `/lock` | Lock vault, pause scrapers |
| `/balance` | Show all account balances |
| `/debt` | Debt summary with APR |
| `/due` | Upcoming payment due dates |
| `/spending` | Spending breakdown by category |
| `/plan` | AI debt payoff strategy |
| `/status` | System health and API budget |
| `/help` | Full command list |

You can also just type a question like "where am I spending the most?" and George will answer using AI.

---

## Managing George

**Stop George:**
```bash
sudo systemctl stop pa
```

**Restart George** (after code changes):
```bash
sudo systemctl restart pa
```

**View logs:**
```bash
journalctl -u pa -f
```

**Push code updates from your Windows PC:**
```bash
cd C:\Dev\PA
bash deploy/push-to-pi.sh pi@raspberrypi.local
```

**George starts automatically** when the Pi boots — no action needed after a power outage.

---

## Troubleshooting

**"George isn't responding in Telegram"**
- Check logs: `journalctl -u pa -f`
- Verify token: `cat ~/pa/.env`
- Make sure the bot is started: `sudo systemctl status pa`

**"Wrong password"**
- You set this when you first sent `/unlock`. If forgotten, delete the vault file and start over:
  ```bash
  rm ~/pa/data/vault.enc ~/pa/data/vault.params.json
  sudo systemctl restart pa
  ```

**"Claude API error"**
- Check your API key: `cat ~/pa/.env`
- Check billing at https://console.anthropic.com/settings/billing
- Check budget: send `/status` in Telegram

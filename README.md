# ⚡ TradePilot AI — Indian F&O Intraday Trading Signal System

TradePilot AI is an automated intraday signal generation and risk management engine designed for Indian Futures & Options (F&O) markets (**NIFTY, BANK NIFTY, FINNIFTY, and liquid F&O stocks**).

> ⚠️ **IMPORTANT SAFETY NOTICE**: This system is hard-locked in **PAPER TRADING MODE**. Real-money order execution is disabled. No automated trades will be placed on your broker account.

---

## 🎯 Key Features

1. **Dual-Timeframe Multi-Indicator Engine:**
   * **Execution Timeframe:** 5-minute chart
   * **Trend Filter Timeframe:** 15-minute chart
   * Indicators: RSI(14), MACD(12,26,9), Bollinger Bands(20,2), EMAs(9, 21, 50, 200), ATR(14), VWAP, SuperTrend(10,3), and Volume Ratio.

2. **Strict Strategy Rules:**
   * **Options Buying:** Momentum & breakout detection, VWAP confirmation, strict -35% stop-loss, 2:1 and 3:1 reward-to-risk targets.
   * **Options Selling:** High IV Percentile requirement ($\ge 40\%$), sideways/range-bound filter, delta $< 0.35$, $2\times$ premium stop-loss.
   * **Strict `NO TRADE` Principle:** If market conditions or technical indicators fail validation, the system outputs `⛔ NO TRADE` to protect capital.

3. **Intraday Capital & Risk Controls:**
   * Max 3–4 new trades per day.
   * Max 2% capital risk per trade.
   * Max 3% daily drawdown stop.
   * Cutoff gate: No new trades after 14:30 IST.
   * Mandatory intraday square-off alert at 15:20 IST (no overnight positions).

4. **Trade Validation & Verification Inspector:**
   * Audit any symbol's live scorecard with a rule-by-rule pass/fail checklist before entering any position.

5. **Broker Integration (Groww API / Webhooks):**
   * Supports live market data authentication via official `growwapi` SDK.
   * **Zero Order Risk:** Order execution functions are hard-locked off.

---

## 🚀 Quick Start

### 1. Prerequisites
* Python 3.10+
* Virtual environment (`venv`)

### 2. Installation
```bash
git clone https://github.com/your-username/tradepilot-ai.git
cd tradepilot-ai

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Launch TradePilot AI
```bash
chmod +x start.sh
./start.sh
```
Or start manually:
```bash
cd backend
python main.py
```

Open your browser at:
* **Dashboard:** [http://localhost:8000](http://localhost:8000)
* **API Docs:** [http://localhost:8000/api/docs](http://localhost:8000/api/docs)

---

## 🔒 Security & Privacy

* **Credentials are Never Committed:** All local tokens and credentials are kept in `data/` and excluded via `.gitignore`.
* **Execution Safety Barrier:** Order placement is disabled at the code level.
* Copy `.env.example` to `.env` if you wish to use environment variables.

---

## 📄 License
MIT License. For educational and paper-trading research purposes only.

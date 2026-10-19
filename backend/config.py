"""
TradePilot AI Configuration
"""
from dataclasses import dataclass, field
from typing import Dict, List

# ============================================================
# MARKET CONFIGURATION
# ============================================================

# NSE Market hours (IST)
MARKET_OPEN_TIME = "09:15"
MARKET_CLOSE_TIME = "15:30"
FO_CUTOFF_TIME = "15:25"  # Close all positions by this time
NO_NEW_TRADE_AFTER = "14:30"  # Stop new trades after this time

# Supported symbols
INDEX_SYMBOLS = {
    "NIFTY": {
        "yf_symbol": "^NSEI",
        "lot_size": 25,
        "tick_size": 0.05,
        "strike_gap": 50,
        "nse_symbol": "NIFTY",
        "exchange": "NSE",
    },
    "BANKNIFTY": {
        "yf_symbol": "^NSEBANK",
        "lot_size": 15,
        "tick_size": 0.05,
        "strike_gap": 100,
        "nse_symbol": "BANKNIFTY",
        "exchange": "NSE",
    },
    "FINNIFTY": {
        "yf_symbol": "NIFTY_FIN_SERVICE.NS",
        "lot_size": 25,
        "tick_size": 0.05,
        "strike_gap": 50,
        "nse_symbol": "FINNIFTY",
        "exchange": "NSE",
    },
}

# Eligible F&O stocks (top liquid ones)
FO_STOCKS = {
    "RELIANCE": {"yf_symbol": "RELIANCE.NS", "lot_size": 250, "strike_gap": 20},
    "TCS": {"yf_symbol": "TCS.NS", "lot_size": 150, "strike_gap": 50},
    "INFY": {"yf_symbol": "INFY.NS", "lot_size": 300, "strike_gap": 20},
    "HDFCBANK": {"yf_symbol": "HDFCBANK.NS", "lot_size": 550, "strike_gap": 10},
    "ICICIBANK": {"yf_symbol": "ICICIBANK.NS", "lot_size": 700, "strike_gap": 10},
    "SBIN": {"yf_symbol": "SBIN.NS", "lot_size": 1500, "strike_gap": 5},
    "AXISBANK": {"yf_symbol": "AXISBANK.NS", "lot_size": 625, "strike_gap": 10},
    "WIPRO": {"yf_symbol": "WIPRO.NS", "lot_size": 1500, "strike_gap": 5},
    "LT": {"yf_symbol": "LT.NS", "lot_size": 150, "strike_gap": 25},
    "TATAMOTORS": {"yf_symbol": "TATAMOTORS.NS", "lot_size": 1425, "strike_gap": 5},
}

# ============================================================
# STRATEGY CONFIGURATION
# ============================================================

# Options Buying Rules
OPTIONS_BUYING_CONFIG = {
    "max_sl_pct": 35.0,          # Max stop-loss as % of premium
    "min_rr_ratio": 2.0,         # Minimum Risk:Reward ratio
    "max_capital_risk_pct": 2.0,  # Max % of capital to risk per trade
    "max_delta": 0.55,           # Max delta (avoid deep ITM)
    "min_delta": 0.25,           # Min delta (avoid very far OTM)
    "min_dte": 1,                # Minimum days to expiry
    "target_dte": 7,             # Preferred DTE range
    "premium_sl_multiplier": 0.60,  # Exit at 60% of entry premium (40% loss)
    "target_1_multiplier": 2.0,  # Target 1 = entry * 2 (100% gain)
    "target_2_multiplier": 3.0,  # Target 2 = entry * 3 (200% gain)
    "min_rsi_bull": 55,          # RSI threshold for bullish entry
    "max_rsi_bear": 45,          # RSI threshold for bearish entry
    "min_volume_ratio": 1.3,     # Volume must be 1.3x average
}

# Options Selling Rules (Stricter - higher risk profile)
OPTIONS_SELLING_CONFIG = {
    "max_sl_pct": 50.0,          # Max SL as % of premium received
    "sl_premium_multiplier": 2.0,  # Exit when premium doubles (2x received)
    "target_pct": 50.0,          # Target: keep 50% of premium
    "target_2_pct": 70.0,        # Target 2: keep 70% of premium
    "min_rr_ratio": 1.0,         # Min R:R (lower since probability is high)
    "max_capital_risk_pct": 1.5,  # Stricter risk for selling
    "max_delta": 0.35,           # Sell OTM options (max delta)
    "min_iv_percentile": 40,     # Only sell when IV percentile is adequate
    "max_pcr_bearish": 0.6,      # PCR constraints
    "min_pcr_bullish": 1.4,
    "min_theta_credit": 5.0,     # Minimum theta per lot
}

# ============================================================
# RISK MANAGEMENT
# ============================================================

RISK_CONFIG = {
    "max_trades_per_day": 4,       # Max 3-4 trades per day
    "max_total_capital_risk": 5.0, # Max 5% of capital at risk at any time
    "max_daily_loss_pct": 3.0,    # Stop trading if daily loss exceeds 3%
    "max_single_trade_risk": 2.0, # Max 2% risk per trade
    "paper_trading_capital": 500000.0,  # ₹5 lakh starting capital
    "real_trading_enabled": False,   # DISABLED - Paper trading only
    "square_off_time": "15:20",    # Force square-off at this time
    "no_new_trade_after": "14:30",  # No new trades after this
}

# ============================================================
# INDICATOR CONFIGURATION  
# ============================================================

INDICATOR_CONFIG = {
    # RSI
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "rsi_bull_zone": 50,
    
    # MACD
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    
    # Bollinger Bands
    "bb_period": 20,
    "bb_std": 2.0,
    
    # EMA
    "ema_short": 9,
    "ema_medium": 21,
    "ema_long": 50,
    "ema_trend": 200,
    
    # ATR
    "atr_period": 14,
    
    # SuperTrend
    "supertrend_period": 10,
    "supertrend_multiplier": 3.0,
    
    # VWAP
    "vwap_enabled": True,
    
    # Volume
    "volume_ma_period": 20,
}

# Signal validation thresholds
VALIDATION_CONFIG = {
    "min_confirmations_buying": 4,   # Need 4 out of 6 indicators to confirm
    "min_confirmations_selling": 3,  # Need 3 out of 5 indicators
    "market_hours_only": True,
    "require_volume_confirmation": True,
    "require_trend_alignment": True,  # 5m and 15m must agree
}

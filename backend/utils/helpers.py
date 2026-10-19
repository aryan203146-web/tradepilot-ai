"""
Helper utilities for TradePilot AI
"""
import logging
from datetime import datetime, time
from typing import Optional
import pytz

IST = pytz.timezone("Asia/Kolkata")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("tradepilot")


def get_ist_now() -> datetime:
    """Get current time in IST."""
    return datetime.now(IST)


def is_market_open() -> bool:
    """Check if NSE market is currently open."""
    now = get_ist_now()
    # Check weekday (0=Mon, 4=Fri)
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def is_new_trade_allowed() -> bool:
    """Check if new trades can be taken (before 14:30 IST)."""
    now = get_ist_now()
    if now.weekday() >= 5:
        return False
    cutoff = now.replace(hour=14, minute=30, second=0, microsecond=0)
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    return market_open <= now <= cutoff


def is_squareoff_time() -> bool:
    """Check if it's time to square off all positions."""
    now = get_ist_now()
    squareoff = now.replace(hour=15, minute=20, second=0, microsecond=0)
    return now >= squareoff


def round_to_strike(price: float, strike_gap: int) -> int:
    """Round price to nearest valid strike price."""
    return int(round(price / strike_gap) * strike_gap)


def get_atm_strike(spot_price: float, strike_gap: int) -> int:
    """Get At-The-Money strike."""
    return round_to_strike(spot_price, strike_gap)


def get_otm_strikes(spot_price: float, strike_gap: int, n_strikes: int = 3):
    """Get OTM call and put strikes."""
    atm = get_atm_strike(spot_price, strike_gap)
    call_strikes = [atm + (i * strike_gap) for i in range(1, n_strikes + 1)]
    put_strikes = [atm - (i * strike_gap) for i in range(1, n_strikes + 1)]
    return call_strikes, put_strikes


def calculate_position_size(capital: float, risk_pct: float, premium: float, lot_size: int) -> int:
    """Calculate number of lots based on risk percentage."""
    max_risk_amount = capital * (risk_pct / 100)
    premium_per_lot = premium * lot_size
    if premium_per_lot <= 0:
        return 1
    lots = int(max_risk_amount / premium_per_lot)
    return max(1, lots)  # Minimum 1 lot


def format_inr(amount: float) -> str:
    """Format amount as Indian Rupees."""
    if abs(amount) >= 100000:
        return f"₹{amount/100000:.2f}L"
    elif abs(amount) >= 1000:
        return f"₹{amount/1000:.1f}K"
    else:
        return f"₹{amount:.2f}"


def get_nearest_expiry_string(symbol: str) -> str:
    """Get nearest weekly expiry string based on contract schedule."""
    now = get_ist_now()
    expiry_weekday = 3  # Thursday for NIFTY & default
    if "BANK" in symbol:
        expiry_weekday = 2  # Wednesday for BANKNIFTY
    elif "FIN" in symbol:
        expiry_weekday = 1  # Tuesday for FINNIFTY

    days_until = (expiry_weekday - now.weekday()) % 7
    if days_until == 0 and now.hour >= 15:
        days_until = 7  # Roll to next week
    expiry = now + __import__('datetime').timedelta(days=days_until)
    return expiry.strftime("%d%b%y").upper()


def classify_market_trend(ema_short: float, ema_long: float, price: float) -> str:
    """Classify market trend based on EMAs."""
    if price > ema_short > ema_long:
        return "STRONG_BULL"
    elif price > ema_short and ema_short < ema_long:
        return "WEAK_BULL"
    elif price < ema_short < ema_long:
        return "STRONG_BEAR"
    elif price < ema_short and ema_short > ema_long:
        return "WEAK_BEAR"
    else:
        return "SIDEWAYS"

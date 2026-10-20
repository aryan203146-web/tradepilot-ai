"""
Market Data Fetcher for TradePilot AI
Fetches OHLCV data from Yahoo Finance (NSE symbols)
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
import logging
import time
import json
import os
import math

logger = logging.getLogger("tradepilot.data")

# Try importing yfinance
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    logger.warning("yfinance not available - using simulated data")


from config import INDEX_SYMBOLS, FO_STOCKS


def _generate_simulated_ohlcv(symbol: str, interval: str, periods: int = 100) -> pd.DataFrame:
    """
    Generate realistic simulated OHLCV data for paper trading when live data unavailable.
    """
    try:
        import pytz
        IST = pytz.timezone("Asia/Kolkata")
    except ImportError:
        from datetime import timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)

    # Base prices for simulation
    base_prices = {
        "^NSEI": 24500.0,
        "^NSEBANK": 52000.0,
        "NIFTY_FIN_SERVICE.NS": 23000.0,
        "RELIANCE.NS": 1280.0,
        "TCS.NS": 3800.0,
        "INFY.NS": 1780.0,
        "HDFCBANK.NS": 1680.0,
        "ICICIBANK.NS": 1240.0,
        "SBIN.NS": 820.0,
    }

    base_price = base_prices.get(symbol, 1000.0)
    freq = "5min" if interval == "5m" else "15min"

    np.random.seed(int(time.time()) % 1000)

    # Generate timestamps
    end_time = now.replace(second=0, microsecond=0)
    timestamps = []
    t = end_time - timedelta(minutes=int(freq[:-3]) * periods)
    while t <= end_time:
        if 9 <= t.hour <= 15:
            if not (t.hour == 9 and t.minute < 15):
                timestamps.append(t)
        t += timedelta(minutes=int(freq[:-3]))

    if not timestamps:
        timestamps = [end_time - timedelta(minutes=int(freq[:-3]) * i) for i in range(periods, 0, -1)]

    # Simulate price walk
    returns = np.random.normal(0.0002, 0.003, len(timestamps))
    prices = [base_price]
    for r in returns[1:]:
        prices.append(prices[-1] * (1 + r))

    data = []
    for i, (ts, price) in enumerate(zip(timestamps, prices)):
        spread = price * 0.002
        open_p = price + np.random.uniform(-spread * 0.3, spread * 0.3)
        close_p = price + np.random.uniform(-spread * 0.5, spread * 0.5)
        high_p = max(open_p, close_p) + abs(np.random.normal(0, spread * 0.4))
        low_p = min(open_p, close_p) - abs(np.random.normal(0, spread * 0.4))
        volume = int(np.random.normal(50000, 15000))
        data.append({
            'Open': round(open_p, 2),
            'High': round(high_p, 2),
            'Low': round(low_p, 2),
            'Close': round(close_p, 2),
            'Volume': max(volume, 1000),
        })

    df = pd.DataFrame(data, index=pd.DatetimeIndex(timestamps))
    df.index.name = 'Datetime'
    return df


def fetch_ohlcv(yf_symbol: str, interval: str = "5m", lookback_days: int = 5) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV data.
    
    Args:
        yf_symbol: Yahoo Finance symbol (e.g. '^NSEI', 'RELIANCE.NS')
        interval: '5m' or '15m'
        lookback_days: Days of history to fetch
    
    Returns:
        DataFrame with OHLCV data or None
    """
    if YFINANCE_AVAILABLE:
        try:
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(
                period=f"{lookback_days}d",
                interval=interval,
                auto_adjust=True,
                prepost=False
            )
            if df is not None and len(df) >= 20:
                # Keep only market hours
                df = df.between_time('09:15', '15:30')
                if len(df) >= 20:
                    logger.info(f"Fetched {len(df)} bars for {yf_symbol} [{interval}]")
                    return df
        except Exception as e:
            logger.warning(f"yfinance error for {yf_symbol}: {e}")

    # Fallback to simulated data
    logger.info(f"Using simulated data for {yf_symbol} [{interval}]")
    return _generate_simulated_ohlcv(yf_symbol, interval)


def fetch_market_data(symbol: str) -> Dict:
    """
    Fetch 5m and 15m data for a given symbol.
    
    Args:
        symbol: e.g. 'NIFTY', 'BANKNIFTY', 'RELIANCE'
    
    Returns:
        Dict with 'df_5m', 'df_15m', 'spot_price', 'symbol'
    """
    # Get config
    config = INDEX_SYMBOLS.get(symbol) or FO_STOCKS.get(symbol)
    if not config:
        logger.error(f"Unknown symbol: {symbol}")
        return {}

    yf_sym = config['yf_symbol']

    df_5m = fetch_ohlcv(yf_sym, '5m', lookback_days=5)
    df_15m = fetch_ohlcv(yf_sym, '15m', lookback_days=10)

    spot_price = None
    if df_5m is not None and len(df_5m) > 0:
        spot_price = float(df_5m['Close'].iloc[-1])

    # If Upstox live feed is connected, prioritize real exchange LTP
    try:
        from market_data.upstox_feed import upstox_manager
        if upstox_manager.is_connected:
            live_quotes = upstox_manager.get_live_ltp([symbol])
            if symbol in live_quotes and live_quotes[symbol] > 0:
                spot_price = live_quotes[symbol]
                logger.info(f"Using live Upstox LTP for {symbol}: ₹{spot_price}")
    except Exception as e:
        logger.debug(f"Upstox LTP lookup bypassed: {e}")

    return {
        'symbol': symbol,
        'yf_symbol': yf_sym,
        'df_5m': df_5m,
        'df_15m': df_15m,
        'spot_price': spot_price,
        'lot_size': config.get('lot_size', 1),
        'strike_gap': config.get('strike_gap', 50),
        'fetched_at': datetime.now().isoformat(),
    }


_LIVE_VIX_CACHE = {"value": 14.5, "updated_at": 0.0}

def get_live_vix() -> float:
    """Fetch live India VIX from yfinance or fallback to typical baseline."""
    now = time.time()
    if now - _LIVE_VIX_CACHE["updated_at"] < 300:  # 5 min cache
        return _LIVE_VIX_CACHE["value"]

    if YFINANCE_AVAILABLE:
        try:
            ticker = yf.Ticker("^INDIAVIX")
            hist = ticker.history(period="1d")
            if hist is not None and len(hist) > 0:
                vix = float(hist["Close"].iloc[-1])
                if 8.0 <= vix <= 60.0:
                    _LIVE_VIX_CACHE["value"] = vix
                    _LIVE_VIX_CACHE["updated_at"] = now
                    logger.info(f"Live India VIX updated: {vix:.2f}%")
                    return vix
        except Exception as e:
            logger.warning(f"Failed to fetch ^INDIAVIX: {e}")

    return _LIVE_VIX_CACHE["value"]


def _norm_cdf(x: float) -> float:
    """Standard Normal Cumulative Distribution Function."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _norm_pdf(x: float) -> float:
    """Standard Normal Probability Density Function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes_pricing(S: float, K: float, T: float, r: float, sigma: float, is_call: bool = True) -> Tuple[float, float, float]:
    """
    Standard Black-Scholes formula for European options (NIFTY/BANKNIFTY).
    Returns: (premium, delta, theta)
    """
    if T <= 0.0005:  # Less than a few hours
        intrinsic = max(0.05, S - K if is_call else K - S)
        delta = 1.0 if (is_call and S > K) else (-1.0 if (not is_call and S < K) else 0.0)
        return round(intrinsic, 2), round(delta, 3), 0.0

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    exp_rt = math.exp(-r * T)
    sqrt_t = math.sqrt(T)

    if is_call:
        price = S * _norm_cdf(d1) - K * exp_rt * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        # Theta per day
        theta = (- (S * _norm_pdf(d1) * sigma) / (2 * sqrt_t) - r * K * exp_rt * _norm_cdf(d2)) / 365.0
    else:
        price = K * exp_rt * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta = (- (S * _norm_pdf(d1) * sigma) / (2 * sqrt_t) + r * K * exp_rt * _norm_cdf(-d2)) / 365.0

    # Ensure tick precision (NSE tick size 0.05) and minimum 0.05
    price = max(0.05, round(price / 0.05) * 0.05)
    return round(price, 2), round(delta, 3), round(theta, 2)


def get_options_chain_mock(symbol: str, spot_price: float, strike_gap: int) -> Dict:
    """
    Generate options chain data for paper trading.
    If Upstox API v2 is connected, uses 100% REAL live market option chain!
    Otherwise falls back to calibrated Black-Scholes model.
    """
    try:
        from market_data.upstox_feed import upstox_manager
        if upstox_manager.is_connected:
            live_chain = upstox_manager.get_live_option_chain(symbol)
            if live_chain and live_chain.get('calls') and live_chain.get('puts'):
                logger.info(f"Using 100% REAL live Upstox option chain for {symbol}")
                live_chain['vix'] = round(get_live_vix(), 2)
                live_chain['dte_days'] = 7.0
                return live_chain
    except Exception as e:
        logger.warning(f"Upstox option chain lookup fallback: {e}")

    try:
        import pytz
        IST = pytz.timezone("Asia/Kolkata")
    except ImportError:
        from datetime import timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)

    # Calculate Days to Expiry (DTE)
    # NIFTY: Thursday (weekday=3), BANKNIFTY: Wednesday (weekday=2), FINNIFTY: Tuesday (weekday=1)
    expiry_weekday = 3
    if "BANK" in symbol:
        expiry_weekday = 2
    elif "FIN" in symbol:
        expiry_weekday = 1

    days_until_expiry = (expiry_weekday - now.weekday()) % 7
    # If today is expiry day and past 15:00, roll to next week
    if days_until_expiry == 0 and (now.hour >= 15 or (now.hour == 15 and now.minute >= 15)):
        days_until_expiry = 7

    # Active contract cycle: Traders trade standard weekly contracts (~5-7 DTE)
    effective_days = 7.0 if "BANK" in symbol else max(5.0, float(days_until_expiry) if days_until_expiry > 0 else 7.0)
    T = effective_days / 365.0

    # IV: Get base IV from live India VIX
    live_vix = get_live_vix()
    if symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
        base_iv = (live_vix / 100.0)
        # Bank NIFTY typically has slightly higher IV (+1.5%)
        if "BANK" in symbol:
            base_iv += 0.015
    else:
        # Single stocks typically trade at 20-30% IV
        base_iv = max(0.22, (live_vix / 100.0) * 1.5)

    r = 0.065  # RBI Repo / Risk-free rate (6.5%)

    atm_strike = round(spot_price / strike_gap) * strike_gap
    strikes = list(range(int(atm_strike - strike_gap * 6), int(atm_strike + strike_gap * 7), strike_gap))

    chain = {
        'calls': {},
        'puts': {},
        'pcr': round(float(np.clip(1.0 + np.random.normal(0, 0.15), 0.70, 1.45)), 2),
        'iv_percentile': round(float(np.clip((live_vix - 10.0) / (25.0 - 10.0) * 100.0, 15.0, 85.0)), 1),
        'vix': round(live_vix, 2),
        'dte_days': round(effective_days, 1),
    }

    for strike in strikes:
        moneyness = (strike - spot_price) / spot_price

        # Volatility skew (OTM Puts usually trade at higher IV in Indian markets)
        call_iv = max(0.08, base_iv + moneyness * 0.06)
        put_iv = max(0.08, base_iv - moneyness * 0.12)

        call_premium, call_delta, call_theta = black_scholes_pricing(spot_price, strike, T, r, call_iv, is_call=True)
        put_premium, put_delta, put_theta = black_scholes_pricing(spot_price, strike, T, r, put_iv, is_call=False)

        chain['calls'][strike] = {
            'premium': call_premium,
            'iv': round(call_iv * 100.0, 2),
            'delta': call_delta,
            'theta': call_theta,
        }
        chain['puts'][strike] = {
            'premium': put_premium,
            'iv': round(put_iv * 100.0, 2),
            'delta': put_delta,
            'theta': put_theta,
        }

    return chain

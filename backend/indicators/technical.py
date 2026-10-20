"""
Technical Indicators for TradePilot AI
Computes all 7 quantitative pillars: RSI, EMA, VWAP, MACD, ATR, Volume, and Support/Resistance.
Robust, vectorized, zero-division safe, and handles edge cases cleanly without NaN leakage.
"""
import pandas as pd
import numpy as np
from typing import Optional, Dict, Tuple, List
import logging

logger = logging.getLogger("tradepilot.indicators")


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index (RSI) using Wilder's exponential smoothing.
    Handles constant price series, NaN, and small datasets cleanly.
    """
    if series is None or len(series) < 2:
        return pd.Series([50.0] * (len(series) if series is not None else 0))

    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    # Wilder's smoothing: alpha = 1 / period (com = period - 1)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    # Avoid zero division
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    # If avg_loss is 0 and avg_gain > 0, RSI is 100
    rsi = rsi.where(~(avg_loss == 0) | (avg_gain == 0), 100.0)
    # If both gain and loss are 0 (flat price), RSI is 50
    rsi = rsi.where((avg_gain != 0) | (avg_loss != 0), 50.0)

    # Fill leading NaNs with 50.0 (neutral)
    return rsi.fillna(50.0)


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """
    Calculate Exponential Moving Average (EMA).
    """
    if series is None or len(series) == 0:
        return pd.Series(dtype=float)
    return series.ewm(span=period, adjust=False).mean()


def calculate_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: Optional[pd.Series] = None,
    dates: Optional[pd.DatetimeIndex] = None,
) -> pd.Series:
    """
    Calculate intraday Volume-Weighted Average Price (VWAP).
    - Resets at the start of each daily trading session.
    - If volume is missing or 0 (common for index spot like ^NSEI),
      uses range-weighted typical price (price spread proxy) so VWAP reflects
      intraday benchmark price rather than collapsing to 0.0 or None.
    """
    typical_price = (high + low + close) / 3.0

    # Ensure valid volume series
    vol = volume.copy() if volume is not None else pd.Series(0.0, index=close.index)
    vol = vol.fillna(0.0)

    # If volume has no positive values, use true range * 1000 as tick activity proxy
    if vol.sum() <= 0:
        price_spread = (high - low).clip(lower=0.05)
        vol = price_spread * 1000.0

    # Session grouping: if dates available, reset daily; otherwise single cumulative session
    if dates is not None and hasattr(dates, 'date'):
        session_id = pd.Series(dates.date, index=close.index)
    elif isinstance(close.index, pd.DatetimeIndex):
        session_id = pd.Series(close.index.date, index=close.index)
    else:
        session_id = pd.Series(1, index=close.index)

    tp_vol = typical_price * vol
    cum_tp_vol = tp_vol.groupby(session_id).cumsum()
    cum_vol = vol.groupby(session_id).cumsum()

    vwap = cum_tp_vol / cum_vol.replace(0.0, np.nan)
    # Fallback to typical price if cumulative volume is 0
    vwap = vwap.fillna(typical_price)
    return vwap


def calculate_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate MACD Line, Signal Line, and Histogram.
    """
    if series is None or len(series) == 0:
        empty = pd.Series(dtype=float)
        return empty, empty, empty

    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """
    Calculate Average True Range (ATR) with Wilder's exponential smoothing.
    """
    if high is None or low is None or close is None or len(close) == 0:
        return pd.Series(dtype=float)

    prev_close = close.shift(1).fillna(close)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = true_range.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    # Backfill initial bars with rolling mean or true range
    initial_mean = true_range.head(period).mean() if len(true_range) >= period else true_range.mean()
    return atr.fillna(initial_mean)


def calculate_volume_ratio(volume: Optional[pd.Series], period: int = 20) -> pd.Series:
    """
    Calculate volume ratio vs 20-period moving average.
    Guaranteed never to return NaN: defaults to 1.0 (neutral) on edge cases.
    """
    if volume is None or len(volume) == 0:
        return pd.Series(1.0, index=[0])

    vol_clean = volume.fillna(0.0)
    if vol_clean.sum() <= 0:
        return pd.Series(1.0, index=volume.index)

    vol_ma = vol_clean.rolling(window=period, min_periods=1).mean()
    ratio = vol_clean / vol_ma.replace(0.0, np.nan)
    return ratio.fillna(1.0).clip(lower=0.1, upper=10.0)


def calculate_bollinger_bands(
    series: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate Bollinger Bands (upper, middle, lower)."""
    middle = series.rolling(window=period, min_periods=1).mean()
    std = series.rolling(window=period, min_periods=1).std().fillna(0.0)
    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)
    return upper, middle, lower


def calculate_supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 10,
    multiplier: float = 3.0,
) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate SuperTrend indicator.
    Returns (supertrend_series, direction_series [1=BULL, -1=BEAR]).
    """
    n = len(close)
    if n == 0:
        return pd.Series(dtype=float), pd.Series(dtype=int)

    atr = calculate_atr(high, low, close, period)
    hl2 = (high + low) / 2.0

    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    supertrend = pd.Series(index=close.index, dtype=float)
    direction = pd.Series(index=close.index, dtype=int)

    # Initialize first bar
    supertrend.iloc[0] = upper_band.iloc[0]
    direction.iloc[0] = 1

    ub = upper_band.values
    lb = lower_band.values
    c = close.values
    st = np.zeros(n, dtype=float)
    dr = np.ones(n, dtype=int)

    st[0] = ub[0]
    dr[0] = 1

    for i in range(1, n):
        # Upper band adjustment
        if ub[i] < ub[i - 1] or c[i - 1] > ub[i - 1]:
            curr_ub = ub[i]
        else:
            curr_ub = ub[i - 1]
        ub[i] = curr_ub

        # Lower band adjustment
        if lb[i] > lb[i - 1] or c[i - 1] < lb[i - 1]:
            curr_lb = lb[i]
        else:
            curr_lb = lb[i - 1]
        lb[i] = curr_lb

        # Direction flip
        prev_st = st[i - 1]
        prev_dr = dr[i - 1]

        if prev_dr == 1:
            if c[i] < curr_lb:
                dr[i] = -1
                st[i] = curr_ub
            else:
                dr[i] = 1
                st[i] = curr_lb
        else:
            if c[i] > curr_ub:
                dr[i] = 1
                st[i] = curr_lb
            else:
                dr[i] = -1
                st[i] = curr_ub

    supertrend = pd.Series(st, index=close.index)
    direction = pd.Series(dr, index=close.index)
    return supertrend, direction


def find_support_resistance(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    lookback: int = 30,
) -> Tuple[float, float, List[float], List[float]]:
    """
    Find structural swing support and resistance levels using pivot high/low fractals.
    Returns (nearest_support, nearest_resistance, all_supports, all_resistances).
    """
    if len(close) < 5:
        cp = float(close.iloc[-1]) if len(close) > 0 else 100.0
        return cp * 0.99, cp * 1.01, [cp * 0.99], [cp * 1.01]

    sub_h = high.tail(lookback).reset_index(drop=True)
    sub_l = low.tail(lookback).reset_index(drop=True)
    current_price = float(close.iloc[-1])

    pivot_highs = []
    pivot_lows = []

    # 5-bar fractal pivot detection
    for i in range(2, len(sub_h) - 2):
        if (sub_h[i] >= sub_h[i - 1] and sub_h[i] >= sub_h[i - 2] and
                sub_h[i] >= sub_h[i + 1] and sub_h[i] >= sub_h[i + 2]):
            pivot_highs.append(float(sub_h[i]))

        if (sub_l[i] <= sub_l[i - 1] and sub_l[i] <= sub_l[i - 2] and
                sub_l[i] <= sub_l[i + 1] and sub_l[i] <= sub_l[i + 2]):
            pivot_lows.append(float(sub_l[i]))

    # Fallbacks if no fractal pivots found
    if not pivot_highs:
        pivot_highs = [float(sub_h.max())]
    if not pivot_lows:
        pivot_lows = [float(sub_l.min())]

    # Nearest resistance strictly above current price
    above = [h for h in pivot_highs if h > current_price]
    nearest_res = min(above) if above else float(sub_h.max())
    if nearest_res <= current_price:
        nearest_res = current_price * 1.008

    # Nearest support strictly below current price
    below = [l for l in pivot_lows if l < current_price]
    nearest_sup = max(below) if below else float(sub_l.min())
    if nearest_sup >= current_price:
        nearest_sup = current_price * 0.992

    return round(nearest_sup, 2), round(nearest_res, 2), sorted(pivot_lows), sorted(pivot_highs)


def compute_all_indicators(df_5m: pd.DataFrame, df_15m: pd.DataFrame) -> Dict:
    """
    Compute all technical indicators for 5m and 15m timeframes across the 7 quantitative pillars.
    Zero NaN values; fully populated dictionary ready for strategy evaluation.
    """
    indicators = {}

    try:
        # ---- 5 MINUTE TIMEFRAME INDICATORS ----
        if df_5m is not None and len(df_5m) >= 5:
            close_5m = df_5m['Close']
            high_5m = df_5m['High']
            low_5m = df_5m['Low']
            vol_5m = df_5m['Volume'] if 'Volume' in df_5m.columns else None
            current_5m = float(close_5m.iloc[-1])
            indicators['price_5m'] = round(current_5m, 2)

            # 1. RSI (14)
            rsi_5m = calculate_rsi(close_5m, 14)
            indicators['rsi_5m'] = round(float(rsi_5m.iloc[-1]), 2)
            indicators['rsi_5m_prev'] = round(float(rsi_5m.iloc[-2]), 2) if len(rsi_5m) >= 2 else indicators['rsi_5m']

            # 2. EMAs (9, 21)
            ema9_5m = calculate_ema(close_5m, 9)
            ema21_5m = calculate_ema(close_5m, 21)
            indicators['ema_9_5m'] = round(float(ema9_5m.iloc[-1]), 2)
            indicators['ema_21_5m'] = round(float(ema21_5m.iloc[-1]), 2)
            indicators['ema_9_21_cross_bull'] = (
                float(ema9_5m.iloc[-1]) > float(ema21_5m.iloc[-1]) and
                float(ema9_5m.iloc[-2]) <= float(ema21_5m.iloc[-2])
            ) if len(ema9_5m) >= 2 else False
            indicators['ema_9_21_cross_bear'] = (
                float(ema9_5m.iloc[-1]) < float(ema21_5m.iloc[-1]) and
                float(ema9_5m.iloc[-2]) >= float(ema21_5m.iloc[-2])
            ) if len(ema9_5m) >= 2 else False

            # 3. VWAP
            vwap_5m = calculate_vwap(high_5m, low_5m, close_5m, vol_5m, df_5m.index)
            vwap_val = float(vwap_5m.iloc[-1])
            indicators['vwap'] = round(vwap_val, 2)
            indicators['price_vs_vwap_pct'] = round((current_5m - vwap_val) / max(vwap_val, 0.01) * 100.0, 3)

            # 4. MACD (12, 26, 9)
            macd, macd_sig, macd_hist = calculate_macd(close_5m, 12, 26, 9)
            indicators['macd_5m'] = round(float(macd.iloc[-1]), 4)
            indicators['macd_signal_5m'] = round(float(macd_sig.iloc[-1]), 4)
            indicators['macd_hist_5m'] = round(float(macd_hist.iloc[-1]), 4)
            indicators['macd_hist_5m_prev'] = round(float(macd_hist.iloc[-2]), 4) if len(macd_hist) >= 2 else 0.0
            indicators['macd_crossover_5m'] = (
                float(macd_hist.iloc[-1]) > 0.0 and float(macd_hist.iloc[-2]) <= 0.0
            ) if len(macd_hist) >= 2 else False
            indicators['macd_crossunder_5m'] = (
                float(macd_hist.iloc[-1]) < 0.0 and float(macd_hist.iloc[-2]) >= 0.0
            ) if len(macd_hist) >= 2 else False
            indicators['macd_expanding_bull'] = (
                float(macd_hist.iloc[-1]) > float(macd_hist.iloc[-2]) > 0
            ) if len(macd_hist) >= 2 else False
            indicators['macd_expanding_bear'] = (
                float(macd_hist.iloc[-1]) < float(macd_hist.iloc[-2]) < 0
            ) if len(macd_hist) >= 2 else False

            # 5. ATR (14)
            atr_5m = calculate_atr(high_5m, low_5m, close_5m, 14)
            atr_val = float(atr_5m.iloc[-1])
            indicators['atr_5m'] = round(atr_val, 2)
            indicators['atr_5m_pct'] = round(atr_val / max(current_5m, 0.01) * 100.0, 3)

            # 6. Volume Ratio
            vol_ratio_5m = calculate_volume_ratio(vol_5m, 20)
            indicators['volume_ratio_5m'] = round(float(vol_ratio_5m.iloc[-1]), 2)

            # 7. Support / Resistance
            sup_5m, res_5m, _, _ = find_support_resistance(high_5m, low_5m, close_5m, lookback=30)
            indicators['support_5m'] = sup_5m
            indicators['resistance_5m'] = res_5m
            indicators['dist_to_resistance_atr'] = round(max(0.0, res_5m - current_5m) / max(atr_val, 0.01), 2)
            indicators['dist_to_support_atr'] = round(max(0.0, current_5m - sup_5m) / max(atr_val, 0.01), 2)

            # Bollinger Bands (5m)
            bb_u, bb_m, bb_l = calculate_bollinger_bands(close_5m, 20, 2.0)
            indicators['bb_upper_5m'] = round(float(bb_u.iloc[-1]), 2)
            indicators['bb_middle_5m'] = round(float(bb_m.iloc[-1]), 2)
            indicators['bb_lower_5m'] = round(float(bb_l.iloc[-1]), 2)

            # SuperTrend (5m)
            _, st_dir_5m = calculate_supertrend(high_5m, low_5m, close_5m, 10, 3.0)
            indicators['supertrend_5m'] = "BULL" if st_dir_5m.iloc[-1] == 1 else "BEAR"

            # 5m price change %
            if len(close_5m) >= 2:
                prev_c = float(close_5m.iloc[-2])
                indicators['price_change_5m_pct'] = round((current_5m - prev_c) / prev_c * 100.0, 3)
            else:
                indicators['price_change_5m_pct'] = 0.0

        # ---- 15 MINUTE TIMEFRAME INDICATORS ----
        if df_15m is not None and len(df_15m) >= 5:
            close_15m = df_15m['Close']
            high_15m = df_15m['High']
            low_15m = df_15m['Low']
            vol_15m = df_15m['Volume'] if 'Volume' in df_15m.columns else None
            current_15m = float(close_15m.iloc[-1])

            # 1. RSI (15m)
            rsi_15m = calculate_rsi(close_15m, 14)
            indicators['rsi_15m'] = round(float(rsi_15m.iloc[-1]), 2)

            # 2. EMAs (9, 21, 50, 200)
            indicators['ema_9_15m'] = round(float(calculate_ema(close_15m, 9).iloc[-1]), 2)
            indicators['ema_21_15m'] = round(float(calculate_ema(close_15m, 21).iloc[-1]), 2)
            indicators['ema_50_15m'] = round(float(calculate_ema(close_15m, 50).iloc[-1]), 2)
            indicators['ema_200_15m'] = round(float(calculate_ema(close_15m, 200).iloc[-1]), 2)

            # 3. MACD (15m)
            m15, ms15, mh15 = calculate_macd(close_15m, 12, 26, 9)
            indicators['macd_15m'] = round(float(m15.iloc[-1]), 4)
            indicators['macd_signal_15m'] = round(float(ms15.iloc[-1]), 4)
            indicators['macd_hist_15m'] = round(float(mh15.iloc[-1]), 4)

            # 4. ATR (15m)
            atr_15m = calculate_atr(high_15m, low_15m, close_15m, 14)
            indicators['atr_15m'] = round(float(atr_15m.iloc[-1]), 2)

            # 5. Volume Ratio (15m)
            vol_ratio_15m = calculate_volume_ratio(vol_15m, 20)
            indicators['volume_ratio_15m'] = round(float(vol_ratio_15m.iloc[-1]), 2)

            # 6. SuperTrend (15m)
            _, st_dir_15m = calculate_supertrend(high_15m, low_15m, close_15m, 10, 3.0)
            indicators['supertrend_15m'] = "BULL" if st_dir_15m.iloc[-1] == 1 else "BEAR"

            # 7. S/R (15m)
            sup_15m, res_15m, _, _ = find_support_resistance(high_15m, low_15m, close_15m, lookback=40)
            indicators['support_15m'] = sup_15m
            indicators['resistance_15m'] = res_15m

            # Higher Timeframe Structural Trend Classification
            ema9 = indicators['ema_9_15m']
            ema21 = indicators['ema_21_15m']
            ema50 = indicators['ema_50_15m']
            ema200 = indicators['ema_200_15m']

            if current_15m > ema9 > ema21 > ema50:
                indicators['trend_15m'] = "STRONG_BULL"
            elif current_15m > ema21 and current_15m > ema50:
                indicators['trend_15m'] = "BULL"
            elif current_15m < ema9 < ema21 < ema50:
                indicators['trend_15m'] = "STRONG_BEAR"
            elif current_15m < ema21 and current_15m < ema50:
                indicators['trend_15m'] = "BEAR"
            else:
                indicators['trend_15m'] = "SIDEWAYS"

    except Exception as e:
        logger.error(f"Error computing indicators: {e}", exc_info=True)

    return indicators

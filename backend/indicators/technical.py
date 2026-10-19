"""
Technical Indicators for TradePilot AI
Computes all indicators needed for signal generation.
"""
import pandas as pd
import numpy as np
from typing import Optional, Dict, Tuple
import logging

logger = logging.getLogger("tradepilot.indicators")


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.inf)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate MACD, Signal line, and Histogram."""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(
    series: pd.Series,
    period: int = 20,
    std_dev: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate Bollinger Bands (upper, middle, lower)."""
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)
    return upper, middle, lower


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Average True Range."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(com=period - 1, min_periods=period).mean()
    return atr


def calculate_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Calculate VWAP (Volume Weighted Average Price) - resets daily."""
    typical_price = (high + low + close) / 3
    vwap = (typical_price * volume).cumsum() / volume.cumsum()
    return vwap


def calculate_supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 10,
    multiplier: float = 3.0
) -> Tuple[pd.Series, pd.Series]:
    """Calculate SuperTrend indicator."""
    atr = calculate_atr(high, low, close, period)
    hl2 = (high + low) / 2

    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    supertrend = pd.Series(index=close.index, dtype=float)
    direction = pd.Series(index=close.index, dtype=int)  # 1=bullish, -1=bearish

    for i in range(1, len(close)):
        # Upper band
        if upper_band.iloc[i] < upper_band.iloc[i - 1] or close.iloc[i - 1] > upper_band.iloc[i - 1]:
            upper_band.iloc[i] = upper_band.iloc[i]
        else:
            upper_band.iloc[i] = upper_band.iloc[i - 1]

        # Lower band
        if lower_band.iloc[i] > lower_band.iloc[i - 1] or close.iloc[i - 1] < lower_band.iloc[i - 1]:
            lower_band.iloc[i] = lower_band.iloc[i]
        else:
            lower_band.iloc[i] = lower_band.iloc[i - 1]

        # SuperTrend direction
        if i == 1:
            direction.iloc[i] = 1
        elif supertrend.iloc[i - 1] == upper_band.iloc[i - 1]:
            direction.iloc[i] = -1 if close.iloc[i] > upper_band.iloc[i] else 1
        else:
            direction.iloc[i] = 1 if close.iloc[i] < lower_band.iloc[i] else -1

        supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == -1 else upper_band.iloc[i]

    return supertrend, direction


def calculate_volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    """Calculate volume ratio vs moving average."""
    vol_ma = volume.rolling(window=period).mean()
    return volume / vol_ma


def find_support_resistance(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    lookback: int = 20
) -> Tuple[float, float]:
    """Find key support and resistance levels."""
    recent_high = high.tail(lookback)
    recent_low = low.tail(lookback)

    # Pivot high/low based method
    resistance = recent_high.max()
    support = recent_low.min()

    # Refine using price clustering
    current_price = close.iloc[-1]

    # Find nearest resistance above current price
    pivot_highs = []
    for i in range(2, len(recent_high) - 2):
        if (recent_high.iloc[i] > recent_high.iloc[i-1] and
                recent_high.iloc[i] > recent_high.iloc[i+1] and
                recent_high.iloc[i] > recent_high.iloc[i-2] and
                recent_high.iloc[i] > recent_high.iloc[i+2]):
            pivot_highs.append(recent_high.iloc[i])

    pivot_lows = []
    for i in range(2, len(recent_low) - 2):
        if (recent_low.iloc[i] < recent_low.iloc[i-1] and
                recent_low.iloc[i] < recent_low.iloc[i+1] and
                recent_low.iloc[i] < recent_low.iloc[i-2] and
                recent_low.iloc[i] < recent_low.iloc[i+2]):
            pivot_lows.append(recent_low.iloc[i])

    if pivot_highs:
        above = [h for h in pivot_highs if h > current_price]
        resistance = min(above) if above else resistance

    if pivot_lows:
        below = [l for l in pivot_lows if l < current_price]
        support = max(below) if below else support

    return support, resistance


def compute_all_indicators(df_5m: pd.DataFrame, df_15m: pd.DataFrame) -> Dict:
    """
    Compute all technical indicators for both timeframes.
    
    Args:
        df_5m: OHLCV DataFrame for 5-minute timeframe
        df_15m: OHLCV DataFrame for 15-minute timeframe
    
    Returns:
        Dictionary of all indicator values
    """
    indicators = {}

    try:
        # ---- 5 MINUTE INDICATORS ----
        if df_5m is not None and len(df_5m) >= 30:
            close_5m = df_5m['Close']
            high_5m = df_5m['High']
            low_5m = df_5m['Low']
            vol_5m = df_5m['Volume']

            # RSI
            rsi_5m = calculate_rsi(close_5m, 14)
            indicators['rsi_5m'] = round(float(rsi_5m.iloc[-1]), 2)

            # MACD
            macd, macd_sig, macd_hist = calculate_macd(close_5m)
            indicators['macd_5m'] = round(float(macd.iloc[-1]), 4)
            indicators['macd_signal_5m'] = round(float(macd_sig.iloc[-1]), 4)
            indicators['macd_hist_5m'] = round(float(macd_hist.iloc[-1]), 4)
            indicators['macd_crossover_5m'] = (
                float(macd_hist.iloc[-1]) > 0 and float(macd_hist.iloc[-2]) <= 0
            )
            indicators['macd_crossunder_5m'] = (
                float(macd_hist.iloc[-1]) < 0 and float(macd_hist.iloc[-2]) >= 0
            )

            # Bollinger Bands
            bb_upper, bb_mid, bb_lower = calculate_bollinger_bands(close_5m)
            indicators['bb_upper_5m'] = round(float(bb_upper.iloc[-1]), 2)
            indicators['bb_middle_5m'] = round(float(bb_mid.iloc[-1]), 2)
            indicators['bb_lower_5m'] = round(float(bb_lower.iloc[-1]), 2)
            current_5m = float(close_5m.iloc[-1])
            indicators['bb_pct_b_5m'] = round(
                (current_5m - float(bb_lower.iloc[-1])) /
                max((float(bb_upper.iloc[-1]) - float(bb_lower.iloc[-1])), 0.01), 4
            )

            # EMAs
            indicators['ema_9_5m'] = round(float(calculate_ema(close_5m, 9).iloc[-1]), 2)
            indicators['ema_21_5m'] = round(float(calculate_ema(close_5m, 21).iloc[-1]), 2)

            # ATR
            indicators['atr_5m'] = round(float(calculate_atr(high_5m, low_5m, close_5m).iloc[-1]), 2)

            # VWAP
            if 'Volume' in df_5m.columns and vol_5m.sum() > 0:
                vwap = calculate_vwap(high_5m, low_5m, close_5m, vol_5m)
                indicators['vwap'] = round(float(vwap.iloc[-1]), 2)

            # Volume ratio
            indicators['volume_ratio_5m'] = round(float(calculate_volume_ratio(vol_5m).iloc[-1]), 2)

            # SuperTrend
            if len(df_5m) >= 20:
                _, st_dir = calculate_supertrend(high_5m, low_5m, close_5m)
                indicators['supertrend_5m'] = "BULL" if st_dir.iloc[-1] == -1 else "BEAR"

            # Support / Resistance
            support, resistance = find_support_resistance(high_5m, low_5m, close_5m)
            indicators['support_5m'] = round(support, 2)
            indicators['resistance_5m'] = round(resistance, 2)

            # Price action
            indicators['price_5m'] = round(current_5m, 2)
            prev_close_5m = float(close_5m.iloc[-2])
            indicators['price_change_5m_pct'] = round((current_5m - prev_close_5m) / prev_close_5m * 100, 3)

        # ---- 15 MINUTE INDICATORS ----
        if df_15m is not None and len(df_15m) >= 30:
            close_15m = df_15m['Close']
            high_15m = df_15m['High']
            low_15m = df_15m['Low']
            vol_15m = df_15m['Volume']

            # RSI
            rsi_15m = calculate_rsi(close_15m, 14)
            indicators['rsi_15m'] = round(float(rsi_15m.iloc[-1]), 2)

            # MACD
            macd_15, macd_sig_15, macd_hist_15 = calculate_macd(close_15m)
            indicators['macd_15m'] = round(float(macd_15.iloc[-1]), 4)
            indicators['macd_signal_15m'] = round(float(macd_sig_15.iloc[-1]), 4)
            indicators['macd_hist_15m'] = round(float(macd_hist_15.iloc[-1]), 4)

            # Bollinger Bands
            bb_u15, bb_m15, bb_l15 = calculate_bollinger_bands(close_15m)
            indicators['bb_upper_15m'] = round(float(bb_u15.iloc[-1]), 2)
            indicators['bb_middle_15m'] = round(float(bb_m15.iloc[-1]), 2)
            indicators['bb_lower_15m'] = round(float(bb_l15.iloc[-1]), 2)

            # EMAs
            indicators['ema_9_15m'] = round(float(calculate_ema(close_15m, 9).iloc[-1]), 2)
            indicators['ema_21_15m'] = round(float(calculate_ema(close_15m, 21).iloc[-1]), 2)
            indicators['ema_50_15m'] = round(float(calculate_ema(close_15m, 50).iloc[-1]), 2)
            indicators['ema_200_15m'] = round(float(calculate_ema(close_15m, 200).iloc[-1]), 2)

            # ATR
            indicators['atr_15m'] = round(float(calculate_atr(high_15m, low_15m, close_15m).iloc[-1]), 2)

            # Volume ratio
            indicators['volume_ratio_15m'] = round(float(calculate_volume_ratio(vol_15m).iloc[-1]), 2)

            # SuperTrend
            if len(df_15m) >= 20:
                _, st_dir_15 = calculate_supertrend(high_15m, low_15m, close_15m)
                indicators['supertrend_15m'] = "BULL" if st_dir_15.iloc[-1] == -1 else "BEAR"

            # Support / Resistance
            sup15, res15 = find_support_resistance(high_15m, low_15m, close_15m)
            indicators['support_15m'] = round(sup15, 2)
            indicators['resistance_15m'] = round(res15, 2)

            # Trend classification
            ema9 = indicators.get('ema_9_15m', 0)
            ema21 = indicators.get('ema_21_15m', 0)
            ema50 = indicators.get('ema_50_15m', 0)
            price = float(close_15m.iloc[-1])

            if price > ema9 > ema21 > ema50:
                indicators['trend_15m'] = "STRONG_BULL"
            elif price > ema9 and price > ema21:
                indicators['trend_15m'] = "BULL"
            elif price < ema9 < ema21 < ema50:
                indicators['trend_15m'] = "STRONG_BEAR"
            elif price < ema9 and price < ema21:
                indicators['trend_15m'] = "BEAR"
            else:
                indicators['trend_15m'] = "SIDEWAYS"

    except Exception as e:
        logger.error(f"Error computing indicators: {e}")

    return indicators

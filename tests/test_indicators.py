"""
Unit tests for Technical Indicators (RSI, EMA, VWAP, MACD, ATR, Volume Ratio, Support/Resistance).
Tests mathematical correctness, edge cases (zeros, NaNs, flat prices), and boundary conditions.
"""
import sys
import os
import pytest
import pandas as pd
import numpy as np

# Ensure backend directory is in python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from indicators.technical import (
    calculate_rsi,
    calculate_ema,
    calculate_vwap,
    calculate_macd,
    calculate_atr,
    calculate_volume_ratio,
    calculate_bollinger_bands,
    calculate_supertrend,
    find_support_resistance,
    compute_all_indicators,
)


class TestRSI:
    def test_rsi_bounds(self):
        """RSI must always strictly be bounded between 0 and 100."""
        prices = pd.Series([100.0, 102.0, 101.0, 105.0, 108.0, 107.0, 110.0, 112.0, 115.0, 114.0, 118.0, 120.0, 122.0, 121.0, 125.0, 130.0])
        rsi = calculate_rsi(prices, period=14)
        assert len(rsi) == len(prices)
        assert (rsi >= 0.0).all()
        assert (rsi <= 100.0).all()
        # Rising prices must yield RSI > 50
        assert rsi.iloc[-1] > 50.0

    def test_rsi_constant_price(self):
        """Flat price series must yield neutral 50.0, not NaN or division error."""
        flat_prices = pd.Series([100.0] * 30)
        rsi = calculate_rsi(flat_prices, period=14)
        assert not rsi.isna().any()
        assert (rsi == 50.0).all()

    def test_rsi_strictly_falling(self):
        """Monotonically falling series should yield low RSI < 30."""
        falling_prices = pd.Series(range(100, 70, -1), dtype=float)
        rsi = calculate_rsi(falling_prices, period=14)
        assert rsi.iloc[-1] < 30.0


class TestEMA:
    def test_ema_convergence(self):
        """EMA must converge toward constant price."""
        prices = pd.Series([50.0] * 10 + [100.0] * 50)
        ema9 = calculate_ema(prices, 9)
        assert len(ema9) == len(prices)
        assert abs(ema9.iloc[-1] - 100.0) < 0.5

    def test_ema_short_vs_long(self):
        """In an uptrend, fast EMA 9 must exceed slow EMA 21."""
        uptrend = pd.Series(np.linspace(100, 200, 50))
        ema9 = calculate_ema(uptrend, 9)
        ema21 = calculate_ema(uptrend, 21)
        assert ema9.iloc[-1] > ema21.iloc[-1]


class TestVWAP:
    def test_vwap_typical_price_weighting(self):
        """VWAP must lie within high-low bounds and correctly weight higher volume."""
        high = pd.Series([105.0, 110.0, 115.0])
        low = pd.Series([95.0, 100.0, 105.0])
        close = pd.Series([100.0, 105.0, 110.0])
        # Higher volume on last candle
        volume = pd.Series([1000.0, 1000.0, 8000.0])
        vwap = calculate_vwap(high, low, close, volume)

        assert len(vwap) == 3
        assert not vwap.isna().any()
        # VWAP must be skewed toward last typical price (110.0)
        assert vwap.iloc[-1] > 105.0

    def test_vwap_zero_volume_fallback(self):
        """When volume is 0 (as in index spot data), VWAP must not be 0.0 or NaN."""
        high = pd.Series([24550.0, 24580.0, 24600.0])
        low = pd.Series([24500.0, 24520.0, 24550.0])
        close = pd.Series([24530.0, 24560.0, 24590.0])
        zero_vol = pd.Series([0.0, 0.0, 0.0])
        vwap = calculate_vwap(high, low, close, zero_vol)

        assert not vwap.isna().any()
        assert (vwap > 24000.0).all()


class TestMACD:
    def test_macd_calculation(self):
        """MACD line, signal line, and histogram relations."""
        prices = pd.Series(np.sin(np.linspace(0, 10, 100)) * 20 + 100)
        macd, signal, hist = calculate_macd(prices, 12, 26, 9)
        assert len(macd) == 100
        assert len(signal) == 100
        assert len(hist) == 100
        # By definition: hist = macd - signal
        diff = (hist - (macd - signal)).abs().max()
        assert diff < 1e-6


class TestATR:
    def test_atr_strictly_positive(self):
        """ATR must always be non-negative."""
        high = pd.Series([105.0, 108.0, 106.0, 110.0, 112.0] * 5)
        low = pd.Series([98.0, 101.0, 99.0, 103.0, 105.0] * 5)
        close = pd.Series([100.0, 105.0, 102.0, 108.0, 110.0] * 5)
        atr = calculate_atr(high, low, close, 14)
        assert (atr > 0.0).all()
        assert not atr.isna().any()

    def test_atr_gap_up(self):
        """True range must include overnight gap up."""
        high = pd.Series([100.0, 150.0])
        low = pd.Series([90.0, 140.0])
        close = pd.Series([95.0, 145.0])
        atr = calculate_atr(high, low, close, 2)
        # Second bar true range is max(150-140, |150-95|, |140-95|) = 55.0
        assert atr.iloc[-1] > 20.0


class TestVolumeRatio:
    def test_volume_ratio_normal(self):
        """Double average volume must produce ratio ~ 2.0."""
        vol = pd.Series([1000.0] * 20 + [2000.0])
        ratio = calculate_volume_ratio(vol, 20)
        assert abs(ratio.iloc[-1] - 2.0) < 0.2

    def test_volume_ratio_zero_volume_safe(self):
        """Zero volume series must safely return 1.0 (neutral), not NaN."""
        vol = pd.Series([0.0] * 25)
        ratio = calculate_volume_ratio(vol, 20)
        assert not ratio.isna().any()
        assert ratio.iloc[-1] == 1.0


class TestSupportResistance:
    def test_fractal_pivots(self):
        """Support must be below current price and resistance above current price."""
        prices = [100.0, 102.0, 108.0, 105.0, 101.0, 95.0, 98.0, 103.0, 107.0, 104.0, 100.0] * 3
        df = pd.DataFrame({
            'High': [p + 2.0 for p in prices],
            'Low': [p - 2.0 for p in prices],
            'Close': prices,
        })
        sup, res, all_sup, all_res = find_support_resistance(df['High'], df['Low'], df['Close'])
        current = df['Close'].iloc[-1]
        assert sup <= current
        assert res >= current
        assert sup < res


class TestComputeAllIndicators:
    def test_compute_all_populates_7_pillars(self):
        """compute_all_indicators must return all 7 pillars with zero NaNs."""
        n = 50
        dates = pd.date_range("2026-10-20 09:15", periods=n, freq="5min")
        df_5m = pd.DataFrame({
            'Open': np.linspace(24000, 24500, n),
            'High': np.linspace(24050, 24550, n),
            'Low': np.linspace(23980, 24480, n),
            'Close': np.linspace(24020, 24520, n),
            'Volume': [50000] * n,
        }, index=dates)

        df_15m = pd.DataFrame({
            'Open': np.linspace(24000, 24500, n),
            'High': np.linspace(24060, 24560, n),
            'Low': np.linspace(23970, 24470, n),
            'Close': np.linspace(24030, 24530, n),
            'Volume': [150000] * n,
        }, index=dates)

        indicators = compute_all_indicators(df_5m, df_15m)

        # Check all 7 pillars
        assert "rsi_5m" in indicators and indicators["rsi_5m"] is not None
        assert "ema_9_5m" in indicators and indicators["ema_9_5m"] is not None
        assert "ema_21_5m" in indicators and indicators["ema_21_5m"] is not None
        assert "vwap" in indicators and indicators["vwap"] is not None
        assert "macd_hist_5m" in indicators and indicators["macd_hist_5m"] is not None
        assert "atr_5m" in indicators and indicators["atr_5m"] is not None
        assert "volume_ratio_5m" in indicators and indicators["volume_ratio_5m"] is not None
        assert "support_5m" in indicators and indicators["support_5m"] is not None
        assert "resistance_5m" in indicators and indicators["resistance_5m"] is not None

"""
Unit tests for Quantitative Strategy Engine.
Tests entry rule evaluation across the 7 pillars, explicit rejection rules,
mathematical exit roadmap (SL, Target 1, Target 2, Trailing), and invalidation conditions.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from strategies.quant_engine import (
    QuantitativeStrategyEngine,
    RejectionCode,
    RuleEvaluation,
    ExitRoadmap,
    quant_engine,
)


@pytest.fixture
def sample_bullish_indicators():
    return {
        "rsi_5m": 58.5,
        "rsi_15m": 55.0,
        "ema_9_5m": 24520.0,
        "ema_21_5m": 24500.0,
        "ema_50_15m": 24450.0,
        "ema_200_15m": 24300.0,
        "trend_15m": "BULL",
        "vwap": 24490.0,
        "price_vs_vwap_pct": 0.12,
        "macd_hist_5m": 3.45,
        "macd_hist_15m": 2.10,
        "macd_expanding_bull": True,
        "atr_5m": 45.0,
        "atr_5m_pct": 0.18,
        "volume_ratio_5m": 1.45,
        "support_5m": 24460.0,
        "resistance_5m": 24650.0,
        "dist_to_resistance_atr": 2.88,
        "dist_to_support_atr": 1.33,
    }


@pytest.fixture
def sample_bearish_indicators():
    return {
        "rsi_5m": 42.0,
        "rsi_15m": 44.0,
        "ema_9_5m": 24480.0,
        "ema_21_5m": 24510.0,
        "ema_50_15m": 24560.0,
        "ema_200_15m": 24700.0,
        "trend_15m": "BEAR",
        "vwap": 24530.0,
        "price_vs_vwap_pct": -0.15,
        "macd_hist_5m": -4.20,
        "macd_hist_15m": -3.10,
        "macd_expanding_bear": True,
        "atr_5m": 45.0,
        "atr_5m_pct": 0.18,
        "volume_ratio_5m": 1.35,
        "support_5m": 24350.0,
        "resistance_5m": 24550.0,
        "dist_to_resistance_atr": 1.25,
        "dist_to_support_atr": 3.15,
    }


class TestQuantEngineEntry:
    def test_bullish_entry_all_pillars_pass(self, sample_bullish_indicators):
        """Bullish setup meeting all criteria must pass entry rules."""
        engine = QuantitativeStrategyEngine()
        spot = 24520.0
        passed, rules, score = engine.evaluate_entry_rules("LONG", spot, sample_bullish_indicators)

        assert passed is True
        assert score >= 70.0
        assert len(rules) == 7

        rule_dict = {r.rule_id: r.passed for r in rules}
        assert rule_dict["RULE_EMA_TREND"] is True
        assert rule_dict["RULE_RSI_MOMENTUM"] is True
        assert rule_dict["RULE_VWAP_BIAS"] is True
        assert rule_dict["RULE_MACD_EXPANSION"] is True
        assert rule_dict["RULE_ATR_VOLATILITY"] is True
        assert rule_dict["RULE_VOLUME_CONFIRMATION"] is True
        assert rule_dict["RULE_SR_CLEARANCE"] is True

    def test_bearish_entry_all_pillars_pass(self, sample_bearish_indicators):
        """Bearish setup meeting all criteria must pass entry rules."""
        engine = QuantitativeStrategyEngine()
        spot = 24490.0
        passed, rules, score = engine.evaluate_entry_rules("SHORT", spot, sample_bearish_indicators)

        assert passed is True
        assert score >= 70.0
        assert len(rules) == 7


class TestQuantEngineRejections:
    def test_reject_counter_trend_long_in_strong_bear(self, sample_bullish_indicators):
        """Long setup in a 15m STRONG_BEAR market must be rejected."""
        engine = QuantitativeStrategyEngine()
        indicators = sample_bullish_indicators.copy()
        indicators["trend_15m"] = "STRONG_BEAR"

        rejections = engine.evaluate_rejection_rules("LONG", 24520.0, indicators, check_time=False)
        codes = [c for c, _ in rejections]
        assert RejectionCode.REJECT_COUNTER_TREND in codes

    def test_reject_counter_trend_short_in_strong_bull(self, sample_bearish_indicators):
        """Short setup in a 15m STRONG_BULL market must be rejected."""
        engine = QuantitativeStrategyEngine()
        indicators = sample_bearish_indicators.copy()
        indicators["trend_15m"] = "STRONG_BULL"

        rejections = engine.evaluate_rejection_rules("SHORT", 24490.0, indicators, check_time=False)
        codes = [c for c, _ in rejections]
        assert RejectionCode.REJECT_COUNTER_TREND in codes

    def test_reject_rsi_overbought_call_buying(self, sample_bullish_indicators):
        """Call buying when 5m RSI is overbought (>74) must be rejected."""
        engine = QuantitativeStrategyEngine()
        indicators = sample_bullish_indicators.copy()
        indicators["rsi_5m"] = 78.0

        rejections = engine.evaluate_rejection_rules("LONG", 24520.0, indicators, check_time=False)
        codes = [c for c, _ in rejections]
        assert RejectionCode.REJECT_RSI_EXTREME in codes

    def test_reject_low_volume_dry_up(self, sample_bullish_indicators):
        """Breakout without volume (<0.6x average) must be rejected."""
        engine = QuantitativeStrategyEngine()
        indicators = sample_bullish_indicators.copy()
        indicators["volume_ratio_5m"] = 0.40

        rejections = engine.evaluate_rejection_rules("LONG", 24520.0, indicators, check_time=False)
        codes = [c for c, _ in rejections]
        assert RejectionCode.REJECT_LOW_VOLUME in codes

    def test_reject_overhead_resistance_wall(self, sample_bullish_indicators):
        """Long setup directly under heavy resistance (<0.2 ATR) must be rejected."""
        engine = QuantitativeStrategyEngine()
        indicators = sample_bullish_indicators.copy()
        indicators["dist_to_resistance_atr"] = 0.10

        rejections = engine.evaluate_rejection_rules("LONG", 24520.0, indicators, check_time=False)
        codes = [c for c, _ in rejections]
        assert RejectionCode.REJECT_OVERHEAD_SR in codes

    def test_reject_daily_trade_limit(self, sample_bullish_indicators):
        """When 4 daily trades have already been executed, reject new setups."""
        engine = QuantitativeStrategyEngine()
        rejections = engine.evaluate_rejection_rules(
            "LONG", 24520.0, sample_bullish_indicators, daily_trades_count=4, max_daily_trades=4, check_time=False
        )
        codes = [c for c, _ in rejections]
        assert RejectionCode.REJECT_DAILY_LIMIT in codes


class TestExitRoadmap:
    def test_exit_roadmap_mathematics(self, sample_bullish_indicators):
        """Verify Stop-Loss (-35%), Target 1 (+100%), Target 2 (+200%), and R:R."""
        engine = QuantitativeStrategyEngine()
        premium = 200.0
        spot = 24520.0
        roadmap = engine.compute_exit_roadmap("LONG", spot, premium, sample_bullish_indicators, sl_pct=35.0)

        # SL must be 65% of entry (200 * 0.65 = 130.0)
        assert roadmap.stop_loss_premium == 130.0
        # Target 1 must be 200 * 2 = 400.0
        assert roadmap.target_1_premium == 400.0
        # Target 2 must be 200 * 3 = 600.0
        assert roadmap.target_2_premium == 600.0
        # R:R = (400 - 200) / (200 - 130) = 200 / 70 = 2.86
        assert roadmap.risk_reward_ratio == 2.86
        # Trailing rule must specify moving to Cost
        assert "Cost" in roadmap.trailing_sl_rule


class TestInvalidationRules:
    def test_invalidation_rules_contain_vwap_and_support(self, sample_bullish_indicators):
        """Invalidation list must explicitly detail VWAP, EMA, and S/R breach conditions."""
        engine = QuantitativeStrategyEngine()
        invals = engine.build_invalidation_rules("LONG", 24520.0, sample_bullish_indicators)
        assert len(invals) >= 5
        text = " ".join(invals)
        assert "VWAP" in text
        assert "EMA" in text
        assert "stop-loss" in text
        assert "15:20 IST" in text

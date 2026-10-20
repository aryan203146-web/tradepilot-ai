"""
Unit tests for Quantitative Strategy Engine.
Tests entry rule evaluation across the 7 pillars, explicit rejection rules,
dynamic Black-Scholes exit roadmap (SL, Target 1, Target 2, Trailing),
R:R validation, active position evaluation, and invalidation conditions.
"""
import sys
import os
import pytest
from datetime import datetime
import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from strategies.quant_engine import (
    QuantitativeStrategyEngine,
    RejectionCode,
    RuleEvaluation,
    ExitRoadmap,
    find_missing_indicators,
    quant_engine,
)

IST = pytz.timezone("Asia/Kolkata")


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

    def test_empty_indicators_score_zero(self):
        """Empty indicators dict must score 0% and fail validation."""
        engine = QuantitativeStrategyEngine()
        passed, rules, score = engine.evaluate_entry_rules("LONG", 24500.0, {})
        assert passed is False
        assert score == 0.0

    def test_find_missing_indicators(self):
        """Missing or None indicator values must be flagged."""
        partial = {"rsi_5m": 50.0, "ema_9_5m": 24500.0}
        missing = find_missing_indicators(partial)
        assert "vwap" in missing
        assert "macd_hist_5m" in missing
        assert "atr_5m" in missing


class TestQuantEngineRejections:
    def test_reject_missing_data(self):
        """Missing indicators must trigger REJECT_MISSING_DATA."""
        engine = QuantitativeStrategyEngine()
        rejections = engine.evaluate_rejection_rules("LONG", 24500.0, {}, check_time=False)
        codes = [c for c, _ in rejections]
        assert RejectionCode.REJECT_MISSING_DATA in codes

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

    def test_reject_weekend_time_window(self, sample_bullish_indicators):
        """Candles occurring on a Saturday/Sunday must be rejected."""
        engine = QuantitativeStrategyEngine()
        saturday = datetime(2026, 10, 24, 11, 0, tzinfo=IST)
        rejections = engine.evaluate_rejection_rules(
            "LONG", 24520.0, sample_bullish_indicators, check_time=True, now=saturday
        )
        codes = [c for c, _ in rejections]
        assert RejectionCode.REJECT_TIME_WINDOW in codes

    def test_reject_daily_trade_limit(self, sample_bullish_indicators):
        """When 4 daily trades have already been executed, reject new setups."""
        engine = QuantitativeStrategyEngine()
        rejections = engine.evaluate_rejection_rules(
            "LONG", 24520.0, sample_bullish_indicators, daily_trades_count=4, max_daily_trades=4, check_time=False
        )
        codes = [c for c, _ in rejections]
        assert RejectionCode.REJECT_DAILY_LIMIT in codes


class TestExitRoadmapAndPositionEvaluation:
    def test_dynamic_bs_exit_roadmap(self, sample_bullish_indicators):
        """
        Verify dynamic Black-Scholes ATR-based exit levels.
        For a Nifty ATM Call at 25,000 (premium ₹150, 3 DTE, ATR 20):
        SL is around ~10% loss, T1 is around ~22% gain, T2 is around ~34% gain.
        """
        engine = QuantitativeStrategyEngine()
        ind = sample_bullish_indicators.copy()
        ind["atr_5m"] = 20.0
        roadmap = engine.compute_exit_roadmap(
            direction="LONG",
            spot_price=25000.0,
            entry_premium=150.0,
            indicators=ind,
            sl_pct=35.0,
            strike_price=25000.0,
            dte_days=3.0,
        )

        assert roadmap.stop_loss_premium < 150.0
        assert roadmap.target_1_premium > 150.0
        assert roadmap.target_2_premium > roadmap.target_1_premium
        assert roadmap.risk_reward_ratio >= 1.5
        assert "Cost" in roadmap.trailing_sl_rule

        # R:R check passes
        assert engine.check_exit_roadmap_rr(roadmap, min_rr=1.5) is None

    def test_evaluate_open_position_lifecycle(self):
        """Verify position lifecycle: T1 scale 50% & trail to cost, T2 exit, EOD 15:20 exit."""
        engine = QuantitativeStrategyEngine()
        entry = 150.0
        sl = 135.0
        t1 = 182.0
        t2 = 201.0

        # Within bounds -> HOLD
        action, _, _ = engine.evaluate_open_position(entry, 160.0, sl, t1, t2, current_time=datetime(2026, 10, 21, 10, 0, tzinfo=IST))
        assert action == "HOLD"

        # Hits T1 -> BOOK_50_TRAIL, effective stop moved to cost (150)
        action, _, new_sl = engine.evaluate_open_position(entry, 185.0, sl, t1, t2, current_time=datetime(2026, 10, 21, 10, 30, tzinfo=IST), t1_hit=False)
        assert action == "BOOK_50_TRAIL"
        assert new_sl == entry

        # After T1, if price drops back to cost (150) -> CLOSE_SL at cost
        action, _, _ = engine.evaluate_open_position(entry, 150.0, sl, t1, t2, current_time=datetime(2026, 10, 21, 11, 0, tzinfo=IST), t1_hit=True)
        assert action == "CLOSE_SL"

        # 15:20 IST EOD cutoff -> CLOSE_EOD
        action, _, _ = engine.evaluate_open_position(entry, 165.0, sl, t1, t2, current_time=datetime(2026, 10, 21, 15, 21, tzinfo=IST))
        assert action == "CLOSE_EOD"


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

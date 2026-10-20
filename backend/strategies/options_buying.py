"""
Options Buying Strategy Engine for TradePilot AI
Generates intraday call/put buying signals using all 7 quantitative pillars:
RSI, EMA, VWAP, MACD, ATR, Volume, and Support/Resistance.
Includes explicit entry rules, exit roadmap, invalidation conditions, and rejection handling.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple, List

import pytz

from models.trade import (
    TradeSignal, TradeDirection, OptionType, TradeType,
    SignalStrength, IndicatorValues
)
from config import INDEX_SYMBOLS, FO_STOCKS, OPTIONS_BUYING_CONFIG, RISK_CONFIG
from utils.helpers import get_atm_strike, round_to_strike, get_nearest_expiry_string
from market_data.data_fetcher import black_scholes_pricing
from strategies.quant_engine import quant_engine, RejectionCode

logger = logging.getLogger("tradepilot.strategy.buying")
IST = pytz.timezone("Asia/Kolkata")


class OptionsBuyingStrategy:
    """
    Intraday quantitative options buying strategy.
    Evaluates momentum, trend alignment, institutional value, and volatility.
    """

    def generate_signal(
        self,
        symbol: str,
        spot_price: float,
        indicators: Dict,
        options_chain: Dict,
        daily_trades_count: int = 0,
    ) -> TradeSignal:
        """
        Generate a quantitative options buying signal.
        Returns a TradeSignal (with is_no_trade=True if any rejection triggers).
        """
        signal = TradeSignal()
        signal.symbol = symbol
        signal.underlying_price = spot_price
        signal.trade_type = TradeType.OPTIONS_BUYING
        signal.timeframe = "5m + 15m"

        # Symbol specifications
        sym_config = INDEX_SYMBOLS.get(symbol) or FO_STOCKS.get(symbol, {})
        lot_size = sym_config.get('lot_size', 50)
        strike_gap = sym_config.get('strike_gap', 50)
        signal.lot_size = lot_size

        # Populate indicator snapshot
        signal.indicators = IndicatorValues(
            rsi_5m=indicators.get('rsi_5m'),
            rsi_15m=indicators.get('rsi_15m'),
            macd_hist_5m=indicators.get('macd_hist_5m'),
            macd_hist_15m=indicators.get('macd_hist_15m'),
            ema_9_5m=indicators.get('ema_9_5m'),
            ema_21_5m=indicators.get('ema_21_5m'),
            ema_50_15m=indicators.get('ema_50_15m'),
            ema_200_15m=indicators.get('ema_200_15m'),
            vwap=indicators.get('vwap'),
            atr_5m=indicators.get('atr_5m'),
            atr_15m=indicators.get('atr_15m'),
            volume_ratio=indicators.get('volume_ratio_5m'),
            supertrend_5m=indicators.get('supertrend_5m'),
            supertrend_15m=indicators.get('supertrend_15m'),
            pcr=options_chain.get('pcr'),
            iv_percentile=options_chain.get('iv_percentile'),
            support_level=indicators.get('support_5m'),
            resistance_level=indicators.get('resistance_5m'),
            bb_upper_5m=indicators.get('bb_upper_5m'),
            bb_lower_5m=indicators.get('bb_lower_5m'),
        )

        # ----------------------------------------------------
        # Step 1: Quantitative Trend & Bias Scoring
        # ----------------------------------------------------
        trend_15m = indicators.get('trend_15m', 'SIDEWAYS')
        rsi_5m = indicators.get('rsi_5m', 50.0)
        macd_hist_5m = indicators.get('macd_hist_5m', 0.0)
        macd_hist_15m = indicators.get('macd_hist_15m', 0.0)
        supertrend_5m = indicators.get('supertrend_5m', 'NEUTRAL')
        supertrend_15m = indicators.get('supertrend_15m', 'NEUTRAL')
        vwap = indicators.get('vwap', spot_price)
        ema9_5m = indicators.get('ema_9_5m', spot_price)
        ema21_5m = indicators.get('ema_21_5m', spot_price)

        bull_score = 0.0
        bear_score = 0.0

        # EMA & Trend
        if 'BULL' in trend_15m:
            bull_score += 2.0
        elif 'BEAR' in trend_15m:
            bear_score += 2.0

        if ema9_5m > ema21_5m:
            bull_score += 1.0
        elif ema9_5m < ema21_5m:
            bear_score += 1.0

        # RSI Momentum
        if 50.0 <= rsi_5m <= 70.0:
            bull_score += 1.5
        elif 30.0 <= rsi_5m <= 50.0:
            bear_score += 1.5

        # MACD Histogram
        if macd_hist_5m > 0:
            bull_score += 1.0
        elif macd_hist_5m < 0:
            bear_score += 1.0

        if macd_hist_15m > 0:
            bull_score += 1.0
        elif macd_hist_15m < 0:
            bear_score += 1.0

        # SuperTrend
        if supertrend_5m == 'BULL':
            bull_score += 1.0
        elif supertrend_5m == 'BEAR':
            bear_score += 1.0

        # VWAP
        if spot_price >= vwap:
            bull_score += 1.5
        else:
            bear_score += 1.5

        # Minimum directional score required
        min_threshold = 4.5
        if bull_score < min_threshold and bear_score < min_threshold:
            signal.is_no_trade = True
            signal.rejection_codes = [RejectionCode.REJECT_CHOPPY_REGIME.value]
            signal.no_trade_reason = (
                f"Insufficient directional conviction. Bull score: {bull_score:.1f}, "
                f"Bear score: {bear_score:.1f} (min {min_threshold} required)."
            )
            signal.validation_notes = [f"⛔ {signal.no_trade_reason}"]
            return signal

        # Direction Selection
        if bull_score >= bear_score:
            direction_str = "LONG"
            signal.direction = TradeDirection.LONG
            signal.option_type = OptionType.CALL
            primary_score = bull_score
        else:
            direction_str = "SHORT"
            signal.direction = TradeDirection.SHORT
            signal.option_type = OptionType.PUT
            primary_score = bear_score

        # ----------------------------------------------------
        # Step 2: Evaluate Non-Negotiable Rejection Rules
        # ----------------------------------------------------
        rejections = quant_engine.evaluate_rejection_rules(
            direction=direction_str,
            spot_price=spot_price,
            indicators=indicators,
            daily_trades_count=daily_trades_count,
            max_daily_trades=RISK_CONFIG['max_trades_per_day'],
            check_time=False,  # Allow scanning at all times; flag in reasons
        )

        if rejections:
            signal.is_no_trade = True
            signal.rejection_codes = [code.value for code, _ in rejections]
            rejection_texts = [f"[{code.value}] {reason}" for code, reason in rejections]
            signal.no_trade_reason = " | ".join(rejection_texts)
            signal.validation_notes = [f"⛔ REJECTED: {r}" for r in rejection_texts]
            return signal

        # ----------------------------------------------------
        # Step 3: Evaluate All 7 Quantitative Entry Rules
        # ----------------------------------------------------
        rules_passed, evaluations, score_pct = quant_engine.evaluate_entry_rules(
            direction=direction_str,
            spot_price=spot_price,
            indicators=indicators,
        )
        signal.entry_rules = [e.to_dict() for e in evaluations]
        signal.score_pct = score_pct

        if not rules_passed:
            failed_rules = [e.name for e in evaluations if not e.passed]
            signal.is_no_trade = True
            signal.rejection_codes = [RejectionCode.REJECT_CHOPPY_REGIME.value]
            signal.no_trade_reason = f"Failed quantitative entry checks: {', '.join(failed_rules)} (Score: {score_pct}%)"
            signal.validation_notes = [f"⛔ {signal.no_trade_reason}"]
            return signal

        # Signal Strength
        if score_pct >= 85.0:
            signal.signal_strength = SignalStrength.STRONG
        elif score_pct >= 70.0:
            signal.signal_strength = SignalStrength.MODERATE
        else:
            signal.signal_strength = SignalStrength.WEAK

        # ----------------------------------------------------
        # Step 4: Strike Selection (ATM / Near OTM)
        # ----------------------------------------------------
        atm = get_atm_strike(spot_price, strike_gap)
        if signal.option_type == OptionType.CALL:
            signal.strike_price = atm if primary_score >= 7.5 else atm + strike_gap
        else:
            signal.strike_price = atm if primary_score >= 7.5 else atm - strike_gap

        # ----------------------------------------------------
        # Step 5: Premium Retrieval / Calibrated Pricing
        # ----------------------------------------------------
        chain_key = 'calls' if signal.option_type == OptionType.CALL else 'puts'
        strike_data = options_chain.get(chain_key, {}).get(int(signal.strike_price), {})
        premium = strike_data.get('premium', None)

        if premium is None or premium <= 0:
            is_call = (signal.option_type == OptionType.CALL)
            vix = options_chain.get('vix', 14.5)
            dte = options_chain.get('dte_days', 5.0) / 365.0
            sigma = max(0.12, vix / 100.0)
            premium, _, _ = black_scholes_pricing(spot_price, signal.strike_price, dte, 0.065, sigma, is_call)

        signal.entry_price = round(premium, 2)
        signal.entry_price_range_low = round(premium * 0.98, 2)
        signal.entry_price_range_high = round(premium * 1.05, 2)

        # ----------------------------------------------------
        # Step 6: Explicit Exit Roadmap (SL, T1 Scale 50%, T2, Trailing)
        # ----------------------------------------------------
        exit_roadmap = quant_engine.compute_exit_roadmap(
            direction=direction_str,
            spot_price=spot_price,
            entry_premium=premium,
            indicators=indicators,
            sl_pct=OPTIONS_BUYING_CONFIG['max_sl_pct'],
        )
        signal.exit_roadmap = exit_roadmap.to_dict()
        signal.stop_loss = exit_roadmap.stop_loss_premium
        signal.stop_loss_pct = exit_roadmap.stop_loss_pct
        signal.target_1 = exit_roadmap.target_1_premium
        signal.target_2 = exit_roadmap.target_2_premium
        signal.risk_reward_ratio = exit_roadmap.risk_reward_ratio

        # Position Sizing
        capital = RISK_CONFIG['paper_trading_capital']
        max_risk_amount = capital * (OPTIONS_BUYING_CONFIG['max_capital_risk_pct'] / 100.0)
        risk_per_unit = max(0.01, premium - signal.stop_loss)
        loss_per_lot = risk_per_unit * lot_size
        lots = max(1, int(max_risk_amount / loss_per_lot)) if loss_per_lot > 0 else 1
        signal.position_size_lots = lots
        signal.capital_at_risk = round(loss_per_lot * lots, 2)
        signal.capital_at_risk_pct = round((signal.capital_at_risk / capital) * 100.0, 2)
        signal.max_loss_per_trade = signal.capital_at_risk

        # ----------------------------------------------------
        # Step 7: Option Symbol & Expiry
        # ----------------------------------------------------
        expiry = get_nearest_expiry_string(symbol)
        signal.expiry_date = expiry
        opt_type_str = "CE" if signal.option_type == OptionType.CALL else "PE"
        signal.option_symbol = f"{symbol}{expiry}{int(signal.strike_price)}{opt_type_str}"

        # ----------------------------------------------------
        # Step 8: Explicit Invalidation Conditions
        # ----------------------------------------------------
        signal.invalidation_conditions = quant_engine.build_invalidation_rules(
            direction=direction_str,
            spot_price=spot_price,
            indicators=indicators,
        )

        # Build human-readable entry narrative
        signal.entry_conditions = [
            f"1. Entry: Buy {signal.symbol} {int(signal.strike_price)}{opt_type_str} at limit ₹{signal.entry_price:.2f} (buffer ₹{signal.entry_price_range_low:.2f} - ₹{signal.entry_price_range_high:.2f}).",
            f"2. Spot Benchmark: Underlying {signal.symbol} spot at ₹{spot_price:.2f} ({'above' if direction_str == 'LONG' else 'below'} VWAP ₹{vwap:.2f}).",
            f"3. Quantitative Confirmation: Score {score_pct}% ({sum(1 for e in evaluations if e.passed)}/7 rules verified).",
            f"4. RSI Momentum: 5m RSI at {rsi_5m:.1f} (in active {direction_str.lower()} expansion zone).",
            f"5. Target 1 (Scale 50%): ₹{signal.target_1:.2f} (+100%), then trail Stop-Loss to Cost.",
            f"6. Target 2 (Runner): ₹{signal.target_2:.2f} (+200%).",
            f"7. Hard Stop-Loss: ₹{signal.stop_loss:.2f} (-35% capital protection).",
        ]

        signal.validity_duration_minutes = 30
        signal.validation_passed = True
        signal.is_no_trade = False
        return signal

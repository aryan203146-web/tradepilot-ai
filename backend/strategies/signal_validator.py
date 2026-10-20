"""
Signal Validator for TradePilot AI
Validates trade signals against explicit quantitative rules across the 7 pillars:
RSI, EMA, VWAP, MACD, ATR, Volume, and Support/Resistance.
Assigns explicit rejection codes and detailed notes.
"""
import logging
from typing import Dict, List, Tuple
from models.trade import TradeSignal, TradeType
from config import VALIDATION_CONFIG, OPTIONS_BUYING_CONFIG, OPTIONS_SELLING_CONFIG
from strategies.quant_engine import RejectionCode

logger = logging.getLogger("tradepilot.validator")


class SignalValidator:
    """
    Validates signals against strict quantitative and risk parameters.
    Rejects any setup failing minimum confirmation thresholds.
    """

    def validate_buying_signal(self, signal: TradeSignal, indicators: Dict) -> Tuple[bool, List[str]]:
        """
        Validate options buying signal against all 7 quantitative pillars.
        Returns (is_valid, list_of_notes).
        """
        notes = []
        checks_passed = 0
        checks_total = 0
        rejection_reasons = []

        direction = signal.direction.value if signal.direction else ''

        # 1. EMA & Structural Trend Alignment
        trend_15m = indicators.get('trend_15m', 'SIDEWAYS')
        supertrend_5m = indicators.get('supertrend_5m', '')
        supertrend_15m = indicators.get('supertrend_15m', '')

        checks_total += 1
        if direction == 'LONG':
            if 'STRONG_BEAR' in trend_15m:
                rejection_reasons.append(f"[{RejectionCode.REJECT_COUNTER_TREND.value}] 15m trend is STRONG_BEAR")
                notes.append("❌ 15m structural trend is STRONG_BEAR — Long trades prohibited")
            elif 'BULL' in trend_15m or supertrend_15m == 'BULL':
                checks_passed += 1
                notes.append("✅ 15m structural trend is bullish")
            else:
                checks_passed += 0.5
                notes.append("⚠️ 15m trend neutral/sideways — partial conviction")
        elif direction == 'SHORT':
            if 'STRONG_BULL' in trend_15m:
                rejection_reasons.append(f"[{RejectionCode.REJECT_COUNTER_TREND.value}] 15m trend is STRONG_BULL")
                notes.append("❌ 15m structural trend is STRONG_BULL — Short trades prohibited")
            elif 'BEAR' in trend_15m or supertrend_15m == 'BEAR':
                checks_passed += 1
                notes.append("✅ 15m structural trend is bearish")
            else:
                checks_passed += 0.5
                notes.append("⚠️ 15m trend neutral/sideways — partial conviction")

        # 2. RSI Momentum & Headroom
        rsi_5m = indicators.get('rsi_5m', 50.0)
        checks_total += 1
        if direction == 'LONG':
            if rsi_5m > 74.0:
                rejection_reasons.append(f"[{RejectionCode.REJECT_RSI_EXTREME.value}] RSI 5m ({rsi_5m:.1f}) overbought >74")
                notes.append(f"❌ RSI 5m ({rsi_5m:.1f}) is heavily overbought (>74)")
            elif 48.0 <= rsi_5m <= 72.0:
                checks_passed += 1
                notes.append(f"✅ RSI 5m in bullish momentum zone ({rsi_5m:.1f})")
            else:
                notes.append(f"❌ RSI 5m ({rsi_5m:.1f}) outside bullish momentum zone")
        elif direction == 'SHORT':
            if rsi_5m < 26.0:
                rejection_reasons.append(f"[{RejectionCode.REJECT_RSI_EXTREME.value}] RSI 5m ({rsi_5m:.1f}) oversold <26")
                notes.append(f"❌ RSI 5m ({rsi_5m:.1f}) is heavily oversold (<26)")
            elif 28.0 <= rsi_5m <= 52.0:
                checks_passed += 1
                notes.append(f"✅ RSI 5m in bearish momentum zone ({rsi_5m:.1f})")
            else:
                notes.append(f"❌ RSI 5m ({rsi_5m:.1f}) outside bearish momentum zone")

        # 3. MACD Momentum
        macd_hist_5m = indicators.get('macd_hist_5m', 0.0)
        macd_hist_15m = indicators.get('macd_hist_15m', 0.0)
        checks_total += 1
        if direction == 'LONG':
            if macd_hist_5m > 0 and macd_hist_15m > 0:
                checks_passed += 1
                notes.append("✅ MACD histogram positive on both 5m and 15m")
            elif macd_hist_5m > 0:
                checks_passed += 0.8
                notes.append("✅ MACD histogram positive on 5m trigger timeframe")
            else:
                notes.append("❌ MACD histogram negative — lack of upside momentum")
        elif direction == 'SHORT':
            if macd_hist_5m < 0 and macd_hist_15m < 0:
                checks_passed += 1
                notes.append("✅ MACD histogram negative on both 5m and 15m")
            elif macd_hist_5m < 0:
                checks_passed += 0.8
                notes.append("✅ MACD histogram negative on 5m trigger timeframe")
            else:
                notes.append("❌ MACD histogram positive — lack of downside momentum")

        # 4. VWAP Location Benchmark
        vwap = indicators.get('vwap', 0.0)
        price = indicators.get('price_5m', signal.underlying_price)
        checks_total += 1
        if vwap > 0:
            if direction == 'LONG':
                if price >= vwap * 0.998:
                    checks_passed += 1
                    notes.append(f"✅ Spot price (₹{price:.2f}) above VWAP (₹{vwap:.2f})")
                else:
                    rejection_reasons.append(f"[{RejectionCode.REJECT_WRONG_SIDE_OF_VWAP.value}] Price below VWAP")
                    notes.append(f"❌ Spot price below VWAP (₹{vwap:.2f}) — buyer weakness")
            elif direction == 'SHORT':
                if price <= vwap * 1.002:
                    checks_passed += 1
                    notes.append(f"✅ Spot price (₹{price:.2f}) below VWAP (₹{vwap:.2f})")
                else:
                    rejection_reasons.append(f"[{RejectionCode.REJECT_WRONG_SIDE_OF_VWAP.value}] Price above VWAP")
                    notes.append(f"❌ Spot price above VWAP (₹{vwap:.2f}) — seller weakness")
        else:
            checks_total -= 1

        # 5. Volume Participation
        vol_ratio = indicators.get('volume_ratio_5m', 1.0)
        checks_total += 1
        if vol_ratio >= 1.15:
            checks_passed += 1
            notes.append(f"✅ Volume ratio {vol_ratio:.2f}x average — institutional volume expansion")
        elif vol_ratio >= 0.95:
            checks_passed += 0.8
            notes.append(f"✅ Volume ratio {vol_ratio:.2f}x average — adequate liquidity")
        elif vol_ratio < 0.60:
            rejection_reasons.append(f"[{RejectionCode.REJECT_LOW_VOLUME.value}] Volume dry-up {vol_ratio:.2f}x")
            notes.append(f"❌ Low volume {vol_ratio:.2f}x avg — high false breakout risk")
        else:
            checks_passed += 0.5
            notes.append(f"⚠️ Volume {vol_ratio:.2f}x avg — moderate")

        # 6. S/R Headroom Clearance
        checks_total += 1
        dist_res = indicators.get('dist_to_resistance_atr', 1.0)
        dist_sup = indicators.get('dist_to_support_atr', 1.0)
        if direction == 'LONG':
            if dist_res >= 0.40:
                checks_passed += 1
                notes.append(f"✅ Resistance clearance: {dist_res:.2f} ATR headroom to overhead pivot")
            elif dist_res < 0.20:
                rejection_reasons.append(f"[{RejectionCode.REJECT_OVERHEAD_SR.value}] Resistance blocked {dist_res:.2f} ATR")
                notes.append(f"❌ Imminent overhead resistance ({dist_res:.2f} ATR away)")
            else:
                checks_passed += 0.5
                notes.append(f"⚠️ Resistance close ({dist_res:.2f} ATR away)")
        else:
            if dist_sup >= 0.40:
                checks_passed += 1
                notes.append(f"✅ Support clearance: {dist_sup:.2f} ATR headroom to support floor")
            elif dist_sup < 0.20:
                rejection_reasons.append(f"[{RejectionCode.REJECT_OVERHEAD_SR.value}] Support floor blocked {dist_sup:.2f} ATR")
                notes.append(f"❌ Imminent support floor ({dist_sup:.2f} ATR away)")
            else:
                checks_passed += 0.5
                notes.append(f"⚠️ Support floor close ({dist_sup:.2f} ATR away)")

        # 7. Risk/Reward Ratio Check
        checks_total += 1
        min_rr = OPTIONS_BUYING_CONFIG['min_rr_ratio']
        if signal.risk_reward_ratio >= min_rr:
            checks_passed += 1
            notes.append(f"✅ Risk/Reward ratio {signal.risk_reward_ratio:.2f}:1 (min {min_rr}:1)")
        else:
            rejection_reasons.append(f"[{RejectionCode.REJECT_INSUFFICIENT_RR.value}] R:R {signal.risk_reward_ratio:.2f}:1 < {min_rr}:1")
            notes.append(f"❌ R:R ratio {signal.risk_reward_ratio:.2f}:1 fails minimum {min_rr}:1")

        # Overall Validation Decision
        min_required = 4.5
        is_valid = (checks_passed >= min_required) and (len(rejection_reasons) == 0)

        score_note = f"Quantitative Score: {checks_passed:.1f}/{checks_total} (min {min_required} required)"
        notes.insert(0, score_note)

        if is_valid:
            notes.insert(1, "✅ QUANTITATIVE SIGNAL VALIDATED")
        else:
            notes.insert(1, f"❌ SIGNAL REJECTED: {'; '.join(rejection_reasons) if rejection_reasons else 'Score below threshold'}")
            signal.rejection_codes.extend([r.split(']')[0].replace('[', '') for r in rejection_reasons])

        return is_valid, notes

    def validate_selling_signal(self, signal: TradeSignal, indicators: Dict) -> Tuple[bool, List[str]]:
        """
        Validate options selling signal.
        Stricter rules: requires range-bound / sideways conditions and adequate IV percentile.
        """
        notes = []
        checks_passed = 0
        checks_total = 0
        rejection_reasons = []

        direction = signal.direction.value if signal.direction else ''

        # 1. IV Percentile Check
        iv_percentile = indicators.get('iv_percentile', 50)
        min_iv = OPTIONS_SELLING_CONFIG['min_iv_percentile']
        checks_total += 1
        if iv_percentile >= min_iv:
            checks_passed += 1
            notes.append(f"✅ IV percentile {iv_percentile:.0f}% (adequate credit for selling, min {min_iv}%)")
        else:
            rejection_reasons.append(f"[{RejectionCode.REJECT_IV_UNFAVORABLE.value}] IV {iv_percentile:.0f}% < {min_iv}%")
            notes.append(f"❌ IV percentile {iv_percentile:.0f}% too low — options selling unviable (premiums too cheap)")

        # 2. Market Regime (Sideways / Mean-Reverting required)
        trend_15m = indicators.get('trend_15m', 'SIDEWAYS')
        checks_total += 1
        if 'SIDEWAYS' in trend_15m or 'WEAK' in trend_15m:
            checks_passed += 1
            notes.append(f"✅ Market regime is range-bound ({trend_15m}) — favorable for theta decay")
        else:
            notes.append(f"⚠️ Market trending ({trend_15m}) — higher risk for naked selling")
            checks_passed += 0.3

        # 3. RSI Mean-Reversion Extremes
        rsi_5m = indicators.get('rsi_5m', 50.0)
        checks_total += 1
        if direction == 'SHORT':  # Call selling (bearish/neutral underlying)
            if rsi_5m >= 65.0:
                checks_passed += 1
                notes.append(f"✅ RSI overbought ({rsi_5m:.1f}) — favorable for call selling")
            else:
                notes.append(f"⚠️ RSI {rsi_5m:.1f} not stretched enough for call selling")
        elif direction == 'LONG':  # Put selling (bullish/neutral underlying)
            if rsi_5m <= 35.0:
                checks_passed += 1
                notes.append(f"✅ RSI oversold ({rsi_5m:.1f}) — favorable for put selling")
            else:
                notes.append(f"⚠️ RSI {rsi_5m:.1f} not stretched enough for put selling")

        # 4. PCR Confirmation
        pcr = indicators.get('pcr', 1.0)
        checks_total += 1
        if direction == 'SHORT' and pcr < 0.85:
            checks_passed += 1
            notes.append(f"✅ PCR {pcr:.2f} bearish — supports call selling")
        elif direction == 'LONG' and pcr > 1.15:
            checks_passed += 1
            notes.append(f"✅ PCR {pcr:.2f} bullish — supports put selling")
        else:
            checks_passed += 0.5
            notes.append(f"⚠️ PCR {pcr:.2f} neutral")

        # 5. Risk/Reward Ratio Check
        checks_total += 1
        min_rr = OPTIONS_SELLING_CONFIG['min_rr_ratio']
        if signal.risk_reward_ratio >= min_rr:
            checks_passed += 1
            notes.append(f"✅ R:R ratio {signal.risk_reward_ratio:.2f}:1 acceptable for option selling")
        else:
            rejection_reasons.append(f"[{RejectionCode.REJECT_INSUFFICIENT_RR.value}] R:R {signal.risk_reward_ratio:.2f}:1 < {min_rr}:1")
            notes.append(f"❌ R:R ratio {signal.risk_reward_ratio:.2f}:1 insufficient")

        min_required = 3.0
        is_valid = (checks_passed >= min_required) and (len(rejection_reasons) == 0)

        score_note = f"Quantitative Score: {checks_passed:.1f}/{checks_total} (min {min_required} required)"
        notes.insert(0, score_note)

        if is_valid:
            notes.insert(1, "✅ OPTION SELLING SIGNAL VALIDATED")
        else:
            notes.insert(1, f"❌ SIGNAL REJECTED: {'; '.join(rejection_reasons) if rejection_reasons else 'Conditions not met'}")
            signal.rejection_codes.extend([r.split(']')[0].replace('[', '') for r in rejection_reasons])

        return is_valid, notes

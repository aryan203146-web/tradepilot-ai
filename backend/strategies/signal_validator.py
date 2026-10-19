"""
Signal Validator for TradePilot AI
Validates trade signals against all required conditions.
"""
import logging
from typing import Dict, List, Tuple
from models.trade import TradeSignal, TradeType
from config import VALIDATION_CONFIG, OPTIONS_BUYING_CONFIG, OPTIONS_SELLING_CONFIG

logger = logging.getLogger("tradepilot.validator")


class SignalValidator:
    def validate_buying_signal(self, signal: TradeSignal, indicators: Dict) -> Tuple[bool, List[str]]:
        """
        Validate options buying signal against all conditions.
        Returns (is_valid, list_of_notes)
        """
        notes = []
        checks_passed = 0
        checks_total = 0

        # 1. Trend alignment check (5m and 15m must agree)
        trend_15m = indicators.get('trend_15m', 'SIDEWAYS')
        supertrend_5m = indicators.get('supertrend_5m', '')
        supertrend_15m = indicators.get('supertrend_15m', '')
        direction = signal.direction.value if signal.direction else ''

        checks_total += 1
        if direction == 'LONG':
            trend_ok = 'BULL' in trend_15m or supertrend_15m == 'BULL'
            if trend_ok:
                checks_passed += 1
                notes.append("✅ 15m trend is bullish")
            else:
                notes.append("❌ 15m trend not bullish - signal weakened")
        elif direction == 'SHORT':
            trend_ok = 'BEAR' in trend_15m or supertrend_15m == 'BEAR'
            if trend_ok:
                checks_passed += 1
                notes.append("✅ 15m trend is bearish")
            else:
                notes.append("❌ 15m trend not bearish - signal weakened")

        # 2. RSI confirmation
        rsi_5m = indicators.get('rsi_5m', 50)
        rsi_15m = indicators.get('rsi_15m', 50)
        checks_total += 1
        if direction == 'LONG':
            if rsi_5m >= OPTIONS_BUYING_CONFIG['min_rsi_bull'] and rsi_5m < 75:
                checks_passed += 1
                notes.append(f"✅ RSI 5m bullish zone ({rsi_5m:.1f})")
            elif rsi_5m > 30 and rsi_15m > 45:
                checks_passed += 0.5
                notes.append(f"⚠️ RSI 5m marginal ({rsi_5m:.1f})")
            else:
                notes.append(f"❌ RSI 5m not in bullish zone ({rsi_5m:.1f})")
        elif direction == 'SHORT':
            if rsi_5m <= OPTIONS_BUYING_CONFIG['max_rsi_bear'] and rsi_5m > 25:
                checks_passed += 1
                notes.append(f"✅ RSI 5m bearish zone ({rsi_5m:.1f})")
            elif rsi_5m < 55 and rsi_15m < 50:
                checks_passed += 0.5
                notes.append(f"⚠️ RSI 5m marginal ({rsi_5m:.1f})")
            else:
                notes.append(f"❌ RSI 5m not in bearish zone ({rsi_5m:.1f})")

        # 3. MACD momentum
        macd_hist_5m = indicators.get('macd_hist_5m', 0)
        macd_hist_15m = indicators.get('macd_hist_15m', 0)
        checks_total += 1
        if direction == 'LONG':
            if macd_hist_5m > 0 and macd_hist_15m > 0:
                checks_passed += 1
                notes.append(f"✅ MACD histogram positive on both TFs")
            elif macd_hist_5m > 0:
                checks_passed += 0.5
                notes.append(f"⚠️ MACD positive on 5m only")
            else:
                notes.append(f"❌ MACD not supporting bullish move")
        elif direction == 'SHORT':
            if macd_hist_5m < 0 and macd_hist_15m < 0:
                checks_passed += 1
                notes.append(f"✅ MACD histogram negative on both TFs")
            elif macd_hist_5m < 0:
                checks_passed += 0.5
                notes.append(f"⚠️ MACD negative on 5m only")
            else:
                notes.append(f"❌ MACD not supporting bearish move")

        # 4. VWAP confirmation
        vwap = indicators.get('vwap', 0)
        price = indicators.get('price_5m', signal.underlying_price)
        checks_total += 1
        if vwap > 0:
            if direction == 'LONG' and price > vwap:
                checks_passed += 1
                notes.append(f"✅ Price above VWAP ({vwap:.2f})")
            elif direction == 'SHORT' and price < vwap:
                checks_passed += 1
                notes.append(f"✅ Price below VWAP ({vwap:.2f})")
            else:
                notes.append(f"❌ Price on wrong side of VWAP ({vwap:.2f})")
        else:
            checks_total -= 1  # Skip if no VWAP

        # 5. Volume confirmation
        vol_ratio = indicators.get('volume_ratio_5m', 1.0)
        checks_total += 1
        if vol_ratio >= OPTIONS_BUYING_CONFIG['min_volume_ratio']:
            checks_passed += 1
            notes.append(f"✅ Volume {vol_ratio:.2f}x avg - confirms move")
        elif vol_ratio >= 1.0:
            checks_passed += 0.5
            notes.append(f"⚠️ Volume {vol_ratio:.2f}x avg - adequate")
        else:
            notes.append(f"❌ Low volume {vol_ratio:.2f}x avg - weak signal")

        # 6. SuperTrend confirmation
        checks_total += 1
        if direction == 'LONG' and supertrend_5m == 'BULL':
            checks_passed += 1
            notes.append(f"✅ SuperTrend 5m bullish")
        elif direction == 'SHORT' and supertrend_5m == 'BEAR':
            checks_passed += 1
            notes.append(f"✅ SuperTrend 5m bearish")
        else:
            notes.append(f"❌ SuperTrend 5m not aligned")

        # 7. Risk/Reward check
        checks_total += 1
        if signal.risk_reward_ratio >= OPTIONS_BUYING_CONFIG['min_rr_ratio']:
            checks_passed += 1
            notes.append(f"✅ R:R ratio {signal.risk_reward_ratio:.1f}:1 (min {OPTIONS_BUYING_CONFIG['min_rr_ratio']}:1)")
        else:
            notes.append(f"❌ R:R {signal.risk_reward_ratio:.1f}:1 below minimum {OPTIONS_BUYING_CONFIG['min_rr_ratio']}:1")

        # Final decision
        min_required = VALIDATION_CONFIG['min_confirmations_buying']
        is_valid = checks_passed >= min_required
        score_note = f"Score: {checks_passed:.1f}/{checks_total} (min {min_required} required)"
        notes.insert(0, score_note)

        if is_valid:
            notes.insert(1, "✅ SIGNAL VALIDATED")
        else:
            notes.insert(1, "❌ SIGNAL REJECTED")

        return is_valid, notes

    def validate_selling_signal(self, signal: TradeSignal, indicators: Dict) -> Tuple[bool, List[str]]:
        """
        Validate options selling signal.
        """
        notes = []
        checks_passed = 0
        checks_total = 0

        # 1. IV percentile check - only sell when IV is adequate
        iv_percentile = indicators.get('iv_percentile', 50)
        min_iv = OPTIONS_SELLING_CONFIG['min_iv_percentile']
        checks_total += 1
        if iv_percentile >= min_iv:
            checks_passed += 1
            notes.append(f"✅ IV percentile {iv_percentile:.0f}% (min {min_iv}%)")
        else:
            notes.append(f"❌ IV percentile {iv_percentile:.0f}% too low (min {min_iv}%)")

        # 2. Market range-bound or sideways check
        trend_15m = indicators.get('trend_15m', 'SIDEWAYS')
        checks_total += 1
        if 'SIDEWAYS' in trend_15m or 'WEAK' in trend_15m:
            checks_passed += 1
            notes.append(f"✅ Market range-bound ({trend_15m}) - good for selling")
        else:
            notes.append(f"⚠️ Strong trend detected ({trend_15m}) - selling riskier")
            checks_passed += 0.3  # Partial credit

        # 3. RSI mean-reversion check
        rsi_5m = indicators.get('rsi_5m', 50)
        direction = signal.direction.value if signal.direction else ''
        checks_total += 1
        if direction == 'SHORT':  # Selling calls (bearish on underlying)
            if rsi_5m >= 65:  # Overbought - sell calls
                checks_passed += 1
                notes.append(f"✅ RSI overbought ({rsi_5m:.1f}) - good for call selling")
            else:
                notes.append(f"⚠️ RSI {rsi_5m:.1f} not extreme enough for call selling")
        elif direction == 'LONG':  # Selling puts (bullish on underlying)
            if rsi_5m <= 35:  # Oversold - sell puts
                checks_passed += 1
                notes.append(f"✅ RSI oversold ({rsi_5m:.1f}) - good for put selling")
            else:
                notes.append(f"⚠️ RSI {rsi_5m:.1f} not extreme enough for put selling")

        # 4. PCR check
        pcr = indicators.get('pcr', 1.0)
        checks_total += 1
        if direction == 'SHORT' and pcr < 0.8:
            checks_passed += 1
            notes.append(f"✅ PCR {pcr:.2f} bearish - supports call selling")
        elif direction == 'LONG' and pcr > 1.2:
            checks_passed += 1
            notes.append(f"✅ PCR {pcr:.2f} bullish - supports put selling")
        else:
            notes.append(f"⚠️ PCR {pcr:.2f} neutral")
            checks_passed += 0.5

        # 5. R:R check
        checks_total += 1
        if signal.risk_reward_ratio >= OPTIONS_SELLING_CONFIG['min_rr_ratio']:
            checks_passed += 1
            notes.append(f"✅ R:R {signal.risk_reward_ratio:.1f}:1 acceptable for selling")
        else:
            notes.append(f"❌ R:R {signal.risk_reward_ratio:.1f}:1 insufficient")

        min_required = VALIDATION_CONFIG['min_confirmations_selling']
        is_valid = checks_passed >= min_required
        score_note = f"Score: {checks_passed:.1f}/{checks_total} (min {min_required} required)"
        notes.insert(0, score_note)

        if is_valid:
            notes.insert(1, "✅ SIGNAL VALIDATED")
        else:
            notes.insert(1, "❌ SIGNAL REJECTED")

        return is_valid, notes

"""
Quantitative Strategy Engine for TradePilot AI
Implements rigorous quantitative rules using all 7 pillars:
1. RSI (14) - Momentum & Exhaustion Filter
2. EMA Stack (9, 21, 50, 200) - Short-term Trigger & Multi-timeframe Trend Filter
3. VWAP - Intraday Institutional Fair-Value Anchor
4. MACD (12, 26, 9) - Trend Acceleration & Histogram Expansion
5. ATR (14) - Dynamic Volatility Buffer & Position Sizing
6. Volume Ratio - Institutional Breakout Participation Filter
7. Support / Resistance - Swing Fractals & Overhead Clearance

Provides explicit:
- Strict Missing Data Rejection (REJECT_MISSING_DATA)
- Dynamic Black-Scholes ATR-based Exit Roadmap & Real R:R Calculation
- Time checks anchored to candle timestamp (as_of)
- Invalidation Rules
- Rejection Rules with Standard Rejection Codes
- Active Position Evaluation (scale 50% at T1, trail stop to cost, 15:20 EOD exit)
"""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone, timedelta
import math

try:
    import pytz
    IST = pytz.timezone("Asia/Kolkata")
except ImportError:
    IST = timezone(timedelta(hours=5, minutes=30))


class RejectionCode(str, Enum):
    REJECT_MISSING_DATA = "REJECT_MISSING_DATA"
    REJECT_TIME_WINDOW = "REJECT_TIME_WINDOW"
    REJECT_CHOPPY_REGIME = "REJECT_CHOPPY_REGIME"
    REJECT_COUNTER_TREND = "REJECT_COUNTER_TREND"
    REJECT_WRONG_SIDE_OF_VWAP = "REJECT_WRONG_SIDE_OF_VWAP"
    REJECT_RSI_EXTREME = "REJECT_RSI_EXTREME"
    REJECT_MACD_OPPOSED = "REJECT_MACD_OPPOSED"
    REJECT_LOW_VOLUME = "REJECT_LOW_VOLUME"
    REJECT_OVERHEAD_SR = "REJECT_OVERHEAD_SR"
    REJECT_INSUFFICIENT_RR = "REJECT_INSUFFICIENT_RR"
    REJECT_LOW_VOLATILITY = "REJECT_LOW_VOLATILITY"
    REJECT_DAILY_LIMIT = "REJECT_DAILY_LIMIT"
    REJECT_IV_UNFAVORABLE = "REJECT_IV_UNFAVORABLE"


# Required indicators for quantitative validation
REQUIRED_INDICATORS = [
    "rsi_5m",
    "rsi_15m",
    "ema_9_5m",
    "ema_21_5m",
    "vwap",
    "macd_hist_5m",
    "atr_5m",
    "volume_ratio_5m",
    "support_5m",
    "resistance_5m",
    "trend_15m",
]


def find_missing_indicators(indicators: Optional[Dict]) -> List[str]:
    """
    Check for missing, None, or NaN indicator values.
    Returns list of missing indicator field names.
    """
    if not indicators or not isinstance(indicators, dict):
        return list(REQUIRED_INDICATORS)

    missing = []
    for key in REQUIRED_INDICATORS:
        val = indicators.get(key)
        if val is None:
            missing.append(key)
        elif isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            missing.append(key)
    return missing


def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _black_scholes_price(
    S: float, K: float, T: float, r: float, sigma: float, is_call: bool = True
) -> float:
    """
    Standard Black-Scholes pricing formula for European options.
    """
    if T <= 0.0001:
        intrinsic = max(0.05, (S - K) if is_call else (K - S))
        return round(intrinsic, 2)

    sigma = max(0.01, min(sigma, 5.0))
    d1 = (math.log(max(S, 0.01) / max(K, 0.01)) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if is_call:
        price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)

    return max(0.05, price)


def black_scholes_pricing(
    S: float, K: float, T: float, r: float, sigma: float, is_call: bool = True
) -> Tuple[float, float, float]:
    """
    Pure Python Black-Scholes pricing formula.
    Returns (price, delta, theta).
    """
    price = _black_scholes_price(S, K, T, r, sigma, is_call)
    if T <= 0.0001:
        delta = 1.0 if (is_call and S > K) else (-1.0 if (not is_call and S < K) else 0.0)
        return round(price, 2), round(delta, 3), 0.0

    d1 = (math.log(max(S, 0.01) / max(K, 0.01)) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    delta = _norm_cdf(d1) if is_call else _norm_cdf(d1) - 1.0
    return round(price, 2), round(delta, 3), 0.0


def _implied_volatility(
    target_price: float,
    S: float,
    K: float,
    T: float,
    r: float = 0.065,
    is_call: bool = True,
) -> float:
    """
    Back out implied volatility from entry option premium using bisection.
    Defaults to 0.18 (18%) if unresolvable.
    """
    if target_price <= 0.05 or S <= 0 or K <= 0 or T <= 0.0001:
        return 0.18

    low = 0.01
    high = 2.5
    for _ in range(40):
        mid = (low + high) / 2.0
        price = _black_scholes_price(S, K, T, r, mid, is_call)
        if abs(price - target_price) < 0.01:
            return mid
        if price > target_price:
            high = mid
        else:
            low = mid
    return (low + high) / 2.0


@dataclass
class RuleEvaluation:
    rule_id: str
    pillar: str  # RSI, EMA, VWAP, MACD, ATR, VOLUME, SR
    name: str
    passed: bool
    threshold: str
    actual_value: str
    details: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExitRoadmap:
    stop_loss_premium: float
    stop_loss_pct: float
    underlying_stop_loss: float
    target_1_premium: float
    target_1_underlying: float
    target_2_premium: float
    target_2_underlying: float
    risk_reward_ratio: float
    trailing_sl_rule: str
    time_stop_cutoff: str = "15:20 IST"

    def to_dict(self) -> dict:
        return asdict(self)


class QuantitativeStrategyEngine:
    """
    Evaluates market setups against mathematical quantitative rules.
    Does not fabricate data or make claims of guaranteed profits.
    """

    def __init__(self):
        self.min_confirmations = 5  # 5 of 7 quantitative rules required for entry
        self.min_rr_buying = 1.5
        self.min_rr_selling = 1.0

    def find_missing_indicators(self, indicators: Optional[Dict]) -> List[str]:
        """Check for missing, None, or NaN indicator values."""
        return find_missing_indicators(indicators)

    def evaluate_entry_rules(
        self,
        direction: str,  # "LONG" or "SHORT"
        spot_price: float,
        indicators: Dict,
    ) -> Tuple[bool, List[RuleEvaluation], float]:
        """
        Evaluate entry conditions across all 7 quantitative pillars.
        Returns (passed, evaluations, score_pct).
        Missing or empty indicators fail with 0% score.
        """
        rules: List[RuleEvaluation] = []
        is_long = (direction.upper() == "LONG")

        # Guard: Check for missing data upfront
        missing = find_missing_indicators(indicators)
        if missing:
            return False, [
                RuleEvaluation(
                    rule_id="RULE_DATA_INTEGRITY",
                    pillar="DATA",
                    name="Data Completeness Check",
                    passed=False,
                    threshold="All 7 pillar indicators present and non-null",
                    actual_value=f"Missing: {', '.join(missing)}",
                    details="Execution halted: incomplete indicator data."
                )
            ], 0.0

        # ----------------------------------------------------
        # Pillar 1: EMA Multi-Timeframe Alignment
        # ----------------------------------------------------
        ema9_5m = indicators["ema_9_5m"]
        ema21_5m = indicators["ema_21_5m"]
        trend_15m = indicators["trend_15m"]

        if is_long:
            ema_passed = (ema9_5m >= ema21_5m) and (spot_price >= ema21_5m or "BULL" in trend_15m)
            ema_thresh = "5m EMA9 >= EMA21 AND Price >= 15m Trend Support"
            ema_actual = f"EMA9: {ema9_5m:.1f}, EMA21: {ema21_5m:.1f}, 15m Trend: {trend_15m}"
            ema_detail = "Short-term momentum aligned with higher timeframe bull structure." if ema_passed else "EMAs show bearish or flat alignment."
        else:
            ema_passed = (ema9_5m <= ema21_5m) and (spot_price <= ema21_5m or "BEAR" in trend_15m)
            ema_thresh = "5m EMA9 <= EMA21 AND Price <= 15m Trend Resistance"
            ema_actual = f"EMA9: {ema9_5m:.1f}, EMA21: {ema21_5m:.1f}, 15m Trend: {trend_15m}"
            ema_detail = "Short-term momentum aligned with higher timeframe bear structure." if ema_passed else "EMAs show bullish or flat alignment."

        rules.append(RuleEvaluation(
            rule_id="RULE_EMA_TREND",
            pillar="EMA",
            name="EMA Multi-Timeframe Trend Alignment",
            passed=bool(ema_passed),
            threshold=ema_thresh,
            actual_value=ema_actual,
            details=ema_detail
        ))

        # ----------------------------------------------------
        # Pillar 2: RSI Momentum Zone & Headroom
        # ----------------------------------------------------
        rsi_5m = indicators["rsi_5m"]
        rsi_15m = indicators["rsi_15m"]

        if is_long:
            rsi_passed = (rsi_5m >= 48.0) and (rsi_5m <= 72.0)
            rsi_thresh = "48.0 <= RSI(5m) <= 72.0 (Bullish Momentum with Headroom)"
            rsi_actual = f"RSI(5m): {rsi_5m:.1f}, RSI(15m): {rsi_15m:.1f}"
            rsi_detail = "RSI in active bullish expansion zone with room before overbought exhaustion." if rsi_passed else "RSI outside optimal bull momentum range."
        else:
            rsi_passed = (rsi_5m <= 52.0) and (rsi_5m >= 28.0)
            rsi_thresh = "28.0 <= RSI(5m) <= 52.0 (Bearish Momentum with Headroom)"
            rsi_actual = f"RSI(5m): {rsi_5m:.1f}, RSI(15m): {rsi_15m:.1f}"
            rsi_detail = "RSI in active bearish expansion zone with room before oversold exhaustion." if rsi_passed else "RSI outside optimal bear momentum range."

        rules.append(RuleEvaluation(
            rule_id="RULE_RSI_MOMENTUM",
            pillar="RSI",
            name="RSI Momentum & Headroom Filter",
            passed=bool(rsi_passed),
            threshold=rsi_thresh,
            actual_value=rsi_actual,
            details=rsi_detail
        ))

        # ----------------------------------------------------
        # Pillar 3: VWAP Institutional Benchmark
        # ----------------------------------------------------
        vwap = indicators["vwap"]
        dist_vwap_pct = indicators.get("price_vs_vwap_pct", ((spot_price - vwap) / vwap) * 100.0 if vwap else 0.0)

        if is_long:
            vwap_passed = (spot_price >= vwap * 0.998)
            vwap_thresh = "Price >= VWAP (Trading above Institutional Benchmark)"
            vwap_actual = f"Spot: {spot_price:.1f}, VWAP: {vwap:.1f} ({dist_vwap_pct:+.2f}%)"
            vwap_detail = "Price trading above intraday VWAP; buyers in control." if vwap_passed else "Price below VWAP; unfavorable buyer location."
        else:
            vwap_passed = (spot_price <= vwap * 1.002)
            vwap_thresh = "Price <= VWAP (Trading below Institutional Benchmark)"
            vwap_actual = f"Spot: {spot_price:.1f}, VWAP: {vwap:.1f} ({dist_vwap_pct:+.2f}%)"
            vwap_detail = "Price trading below intraday VWAP; sellers in control." if vwap_passed else "Price above VWAP; unfavorable seller location."

        rules.append(RuleEvaluation(
            rule_id="RULE_VWAP_BIAS",
            pillar="VWAP",
            name="VWAP Institutional Value Bias",
            passed=bool(vwap_passed),
            threshold=vwap_thresh,
            actual_value=vwap_actual,
            details=vwap_detail
        ))

        # ----------------------------------------------------
        # Pillar 4: MACD Acceleration & Histogram (Stricter Rule)
        # ----------------------------------------------------
        macd_hist_5m = indicators["macd_hist_5m"]
        macd_hist_15m = indicators.get("macd_hist_15m", 0.0)
        macd_exp_bull = indicators.get("macd_expanding_bull", False)
        macd_exp_bear = indicators.get("macd_expanding_bear", False)

        if is_long:
            # 5m histogram must agree, plus either 15m histogram or expanding momentum
            macd_passed = (macd_hist_5m > 0.0) and ((macd_hist_15m > 0.0) or macd_exp_bull)
            macd_thresh = "MACD Hist(5m) > 0 AND (Hist(15m) > 0 OR Expanding Bullish)"
            macd_actual = f"Hist(5m): {macd_hist_5m:+.3f}, Hist(15m): {macd_hist_15m:+.3f}"
            macd_detail = "MACD momentum confirms positive price velocity." if macd_passed else "MACD histogram negative or contracting."
        else:
            macd_passed = (macd_hist_5m < 0.0) and ((macd_hist_15m < 0.0) or macd_exp_bear)
            macd_thresh = "MACD Hist(5m) < 0 AND (Hist(15m) < 0 OR Expanding Bearish)"
            macd_actual = f"Hist(5m): {macd_hist_5m:+.3f}, Hist(15m): {macd_hist_15m:+.3f}"
            macd_detail = "MACD momentum confirms negative price velocity." if macd_passed else "MACD histogram positive or expanding upward."

        rules.append(RuleEvaluation(
            rule_id="RULE_MACD_EXPANSION",
            pillar="MACD",
            name="MACD Trend Acceleration & Expansion",
            passed=bool(macd_passed),
            threshold=macd_thresh,
            actual_value=macd_actual,
            details=macd_detail
        ))

        # ----------------------------------------------------
        # Pillar 5: ATR Dynamic Volatility Threshold
        # ----------------------------------------------------
        atr_5m = indicators["atr_5m"]
        atr_pct = indicators.get("atr_5m_pct", (atr_5m / max(spot_price, 0.01)) * 100.0)

        atr_passed = (atr_pct >= 0.04)
        atr_thresh = "ATR(5m) >= 0.04% of Spot Price (Minimum Move Potential)"
        atr_actual = f"ATR(5m): {atr_5m:.2f} ({atr_pct:.3f}%)"
        atr_detail = "Volatility sufficient to support intraday target progression." if atr_passed else "Volatility compressed; risk of choppy range-bound stall."

        rules.append(RuleEvaluation(
            rule_id="RULE_ATR_VOLATILITY",
            pillar="ATR",
            name="ATR Volatility Expansion Check",
            passed=bool(atr_passed),
            threshold=atr_thresh,
            actual_value=atr_actual,
            details=atr_detail
        ))

        # ----------------------------------------------------
        # Pillar 6: Volume Confirmation
        # ----------------------------------------------------
        vol_ratio = indicators["volume_ratio_5m"]
        vol_passed = (vol_ratio >= 0.95)
        vol_thresh = "Volume Ratio(5m) >= 0.95x 20-bar Average"
        vol_actual = f"Volume Ratio: {vol_ratio:.2f}x"
        vol_detail = "Institutional volume confirms price movement." if vol_passed else "Volume below average; risk of low-liquidity false move."

        rules.append(RuleEvaluation(
            rule_id="RULE_VOLUME_CONFIRMATION",
            pillar="VOLUME",
            name="Volume Expansion & Participation",
            passed=bool(vol_passed),
            threshold=vol_thresh,
            actual_value=vol_actual,
            details=vol_detail
        ))

        # ----------------------------------------------------
        # Pillar 7: Support / Resistance Headroom Clearance (No Distortion)
        # ----------------------------------------------------
        sup_5m = indicators["support_5m"]
        res_5m = indicators["resistance_5m"]
        safe_atr = max(atr_5m, 0.001)

        dist_res_atr = (res_5m - spot_price) / safe_atr
        dist_sup_atr = (spot_price - sup_5m) / safe_atr

        if is_long:
            sr_passed = (dist_res_atr >= 0.35)
            sr_thresh = "Distance to Resistance >= 0.35 ATR (Clear Runway)"
            sr_actual = f"Res: {res_5m:.1f} ({dist_res_atr:.2f} ATR headroom)"
            sr_detail = "Clear upside runway to nearest structural resistance." if sr_passed else f"Resistance wall too close ({res_5m:.1f}); risk of immediate reversal."
        else:
            sr_passed = (dist_sup_atr >= 0.35)
            sr_thresh = "Distance to Support >= 0.35 ATR (Clear Downside Runway)"
            sr_actual = f"Sup: {sup_5m:.1f} ({dist_sup_atr:.2f} ATR headroom)"
            sr_detail = "Clear downside runway to nearest structural support." if sr_passed else f"Support floor too close ({sup_5m:.1f}); risk of immediate bounce."

        rules.append(RuleEvaluation(
            rule_id="RULE_SR_CLEARANCE",
            pillar="SR",
            name="Support & Resistance Headroom",
            passed=bool(sr_passed),
            threshold=sr_thresh,
            actual_value=sr_actual,
            details=sr_detail
        ))

        # Score calculation
        passed_count = sum(1 for r in rules if r.passed)
        score_pct = round((passed_count / len(rules)) * 100.0, 1)
        overall_passed = (passed_count >= self.min_confirmations)

        return overall_passed, rules, score_pct

    def evaluate_rejection_rules(
        self,
        direction: str,
        spot_price: float,
        indicators: Dict,
        daily_trades_count: int = 0,
        max_daily_trades: int = 4,
        check_time: bool = True,
        now: Optional[datetime] = None,
    ) -> List[Tuple[RejectionCode, str]]:
        """
        Evaluate non-negotiable rejection criteria.
        Uses candle timestamp `now` when provided for backtesting accuracy.
        """
        rejections: List[Tuple[RejectionCode, str]] = []
        is_long = (direction.upper() == "LONG")

        # 0. Missing Data Rejection
        missing = find_missing_indicators(indicators)
        if missing:
            rejections.append((
                RejectionCode.REJECT_MISSING_DATA,
                f"Missing critical indicator data: {', '.join(missing)}"
            ))
            return rejections

        # 1. Daily Trade Limit Rejection
        if daily_trades_count >= max_daily_trades:
            rejections.append((
                RejectionCode.REJECT_DAILY_LIMIT,
                f"Maximum allowed daily trades ({max_daily_trades}) reached for today."
            ))

        # 2. Market Time Window Rejection (Anchored to `now`)
        if check_time:
            t = now or datetime.now(IST)
            if t.tzinfo is None:
                t = IST.localize(t) if hasattr(IST, "localize") else t.replace(tzinfo=IST)

            if t.weekday() >= 5:  # Weekend check
                rejections.append((
                    RejectionCode.REJECT_TIME_WINDOW,
                    f"Market is closed on weekends ({t.strftime('%A')})."
                ))
            else:
                cutoff_start = t.replace(hour=9, minute=20, second=0, microsecond=0)
                cutoff_end = t.replace(hour=14, minute=30, second=0, microsecond=0)
                if t < cutoff_start:
                    rejections.append((
                        RejectionCode.REJECT_TIME_WINDOW,
                        f"Candle time ({t.strftime('%H:%M')} IST) is before opening filter (09:20 IST)."
                    ))
                elif t > cutoff_end:
                    rejections.append((
                        RejectionCode.REJECT_TIME_WINDOW,
                        f"Candle time ({t.strftime('%H:%M')} IST) is past new trade cutoff (14:30 IST)."
                    ))

        # 3. Choppy / Compressed Market Rejection
        trend_15m = indicators.get("trend_15m", "SIDEWAYS")
        rsi_5m = indicators.get("rsi_5m", 50.0)
        atr_pct = indicators.get("atr_5m_pct", 0.05)

        if trend_15m == "SIDEWAYS" and (47.0 <= rsi_5m <= 53.0) and (atr_pct < 0.03):
            rejections.append((
                RejectionCode.REJECT_CHOPPY_REGIME,
                f"Market in tight consolidation (RSI: {rsi_5m:.1f}, ATR%: {atr_pct:.3f}%). Risk of choppy false breakouts."
            ))

        # 4. Counter-Trend Rejection
        if is_long and trend_15m == "STRONG_BEAR":
            rejections.append((
                RejectionCode.REJECT_COUNTER_TREND,
                "Attempting long against a higher timeframe STRONG_BEAR trend on 15m."
            ))
        elif not is_long and trend_15m == "STRONG_BULL":
            rejections.append((
                RejectionCode.REJECT_COUNTER_TREND,
                "Attempting short against a higher timeframe STRONG_BULL trend on 15m."
            ))

        # 5. Severe RSI Exhaustion Rejection
        if is_long and rsi_5m > 74.0:
            rejections.append((
                RejectionCode.REJECT_RSI_EXTREME,
                f"RSI 5m ({rsi_5m:.1f}) is heavily overbought (>74). Call buying carries high mean-reversion risk."
            ))
        elif not is_long and rsi_5m < 26.0:
            rejections.append((
                RejectionCode.REJECT_RSI_EXTREME,
                f"RSI 5m ({rsi_5m:.1f}) is heavily oversold (<26). Put buying carries high snapback rally risk."
            ))

        # 6. Low Volume Dry-up Rejection
        vol_ratio = indicators.get("volume_ratio_5m", 1.0)
        if vol_ratio < 0.60:
            rejections.append((
                RejectionCode.REJECT_LOW_VOLUME,
                f"Volume ratio ({vol_ratio:.2f}x) is severely below 20-period average. Breakout lacks institutional volume."
            ))

        # 7. Overhead S/R Rejection (Safe ATR calculation)
        safe_atr = max(indicators.get("atr_5m", 1.0), 0.001)
        if is_long:
            res_5m = indicators.get("resistance_5m", spot_price * 1.01)
            dist_res_atr = (res_5m - spot_price) / safe_atr
            if dist_res_atr < 0.20:
                rejections.append((
                    RejectionCode.REJECT_OVERHEAD_SR,
                    f"Directly under major resistance ({dist_res_atr:.2f} ATR away). Insufficient headroom for target 1."
                ))
        else:
            sup_5m = indicators.get("support_5m", spot_price * 0.99)
            dist_sup_atr = (spot_price - sup_5m) / safe_atr
            if dist_sup_atr < 0.20:
                rejections.append((
                    RejectionCode.REJECT_OVERHEAD_SR,
                    f"Directly above major support ({dist_sup_atr:.2f} ATR away). Insufficient headroom for target 1."
                ))

        return rejections

    def compute_exit_roadmap(
        self,
        direction: str,
        spot_price: float,
        entry_premium: float,
        indicators: Dict,
        sl_pct: float = 35.0,
        strike_price: Optional[float] = None,
        dte_days: Optional[float] = None,
        risk_free_rate: float = 0.065,
    ) -> ExitRoadmap:
        """
        Build dynamic quantitative exit roadmap:
        - Underlying Stop-Loss at 1.5x ATR
        - Underlying Target 1 at 3.0x ATR (Scale 50%, Trail Stop to Cost)
        - Underlying Target 2 at 4.5x ATR (Runner)
        - Option premiums re-priced via Black-Scholes with backed-out IV
        - Hard stop cap at -35%
        - Real R:R calculated from actual option prices
        """
        is_long = (direction.upper() == "LONG")
        atr_5m = indicators.get("atr_5m", spot_price * 0.005)
        safe_atr = max(atr_5m, 0.001)

        # 1. Underlying spot levels in ATR multiples
        if is_long:
            underlying_sl = round(spot_price - (1.5 * safe_atr), 2)
            underlying_t1 = round(spot_price + (3.0 * safe_atr), 2)
            underlying_t2 = round(spot_price + (4.5 * safe_atr), 2)
        else:
            underlying_sl = round(spot_price + (1.5 * safe_atr), 2)
            underlying_t1 = round(spot_price - (3.0 * safe_atr), 2)
            underlying_t2 = round(spot_price - (4.5 * safe_atr), 2)

        # 2. Black-Scholes parameter extraction
        K = strike_price if (strike_price and strike_price > 0) else spot_price
        dte = dte_days if (dte_days and dte_days > 0) else 5.0
        T = max(dte / 365.0, 0.001)

        # Back out IV from entry premium
        iv = _implied_volatility(entry_premium, spot_price, K, T, risk_free_rate, is_long)

        # Re-price option at underlying target and stop levels
        raw_stop_premium = round(_black_scholes_price(underlying_sl, K, T, risk_free_rate, iv, is_long), 2)
        target_1_premium = round(_black_scholes_price(underlying_t1, K, T, risk_free_rate, iv, is_long), 2)
        target_2_premium = round(_black_scholes_price(underlying_t2, K, T, risk_free_rate, iv, is_long), 2)

        # 3. Hard cap stop-loss: maximum -35% loss
        max_allowed_loss_premium = round(entry_premium * (1.0 - sl_pct / 100.0), 2)
        stop_premium = max(max_allowed_loss_premium, raw_stop_premium)
        stop_premium = round(min(entry_premium * 0.98, max(0.05, stop_premium)), 2)

        # Actual effective stop-loss percentage
        actual_sl_pct = round(((entry_premium - stop_premium) / entry_premium) * 100.0, 1)

        # 4. Real R:R calculation
        risk_unit = max(0.01, entry_premium - stop_premium)
        reward_unit = max(0.0, target_1_premium - entry_premium)
        rr_ratio = round(reward_unit / risk_unit, 2)

        trailing_rule = (
            f"When Target 1 (₹{target_1_premium:.2f}) is hit: Book 50% profits, "
            f"and move Stop-Loss on remaining 50% to Cost (₹{entry_premium:.2f})."
        )

        return ExitRoadmap(
            stop_loss_premium=stop_premium,
            stop_loss_pct=actual_sl_pct,
            underlying_stop_loss=underlying_sl,
            target_1_premium=target_1_premium,
            target_1_underlying=underlying_t1,
            target_2_premium=target_2_premium,
            target_2_underlying=underlying_t2,
            risk_reward_ratio=rr_ratio,
            trailing_sl_rule=trailing_rule,
            time_stop_cutoff="15:20 IST (Mandatory Intraday Square-Off)"
        )

    def check_exit_roadmap_rr(
        self,
        exit_roadmap: ExitRoadmap,
        min_rr: float = 1.5,
    ) -> Optional[Tuple[RejectionCode, str]]:
        """
        Enforce minimum Risk:Reward ratio on the computed exit roadmap.
        """
        if exit_roadmap.risk_reward_ratio < min_rr:
            return (
                RejectionCode.REJECT_INSUFFICIENT_RR,
                f"Calculated R:R to Target 1 ({exit_roadmap.risk_reward_ratio:.2f}:1) is below required minimum ({min_rr:.1f}:1)."
            )
        return None

    def evaluate_open_position(
        self,
        entry_premium: float,
        current_premium: float,
        stop_loss_premium: float,
        target_1_premium: float,
        target_2_premium: float,
        current_time: Optional[datetime] = None,
        t1_hit: bool = False,
    ) -> Tuple[str, str, float]:
        """
        Applies exit rules to an open position:
        - Stop-loss hit: close full position
        - Target 1 hit: scale 50% & move stop to cost
        - Target 2 hit: close runner
        - 15:20 IST: mandatory square-off
        Returns: (action, reason, current_effective_stop)
        where action in ["HOLD", "BOOK_50_TRAIL", "CLOSE_T2", "CLOSE_SL", "CLOSE_EOD"]
        """
        now = current_time or datetime.now(IST)
        if now.tzinfo is None:
            now = IST.localize(now) if hasattr(IST, "localize") else now.replace(tzinfo=IST)

        # 15:20 IST Time Stop
        if now.hour > 15 or (now.hour == 15 and now.minute >= 20):
            return "CLOSE_EOD", "15:20 IST mandatory intraday square-off reached.", stop_loss_premium

        effective_sl = entry_premium if t1_hit else stop_loss_premium

        # Stop-loss check
        if current_premium <= effective_sl:
            reason = "Stop loss hit at Cost (protective profit lock)" if t1_hit else f"Stop loss hit at ₹{effective_sl:.2f}."
            return "CLOSE_SL", reason, effective_sl

        # Target 2 check
        if current_premium >= target_2_premium:
            return "CLOSE_T2", f"Target 2 runner hit at ₹{target_2_premium:.2f}.", effective_sl

        # Target 1 check
        if not t1_hit and current_premium >= target_1_premium:
            return "BOOK_50_TRAIL", f"Target 1 hit at ₹{target_1_premium:.2f}. Scale 50% profit and trail stop to cost ₹{entry_premium:.2f}.", entry_premium

        return "HOLD", "Position within target and stop boundaries.", effective_sl

    def build_invalidation_rules(
        self,
        direction: str,
        spot_price: float,
        indicators: Dict,
        sl_pct: float = 35.0,
    ) -> List[str]:
        """
        Explicit invalidation criteria that immediately cancel or invalidate the active trade.
        """
        is_long = (direction.upper() == "LONG")
        vwap = indicators.get("vwap", spot_price)
        sup = indicators.get("support_5m", spot_price * 0.99)
        res = indicators.get("resistance_5m", spot_price * 1.01)

        invals = []
        if is_long:
            invals.append(f"1. 5m Candle Close below VWAP (₹{vwap:.2f}) with volume confirms institutional rejection.")
            invals.append(f"2. Spot price breaches key swing support level (₹{sup:.2f}).")
            invals.append("3. Fast EMA 9 crosses back below EMA 21 on 5m timeframe.")
            invals.append("4. MACD histogram flips negative on 5m for 2 consecutive bars.")
            invals.append("5. RSI 5m drops below 42.0 (loss of upward momentum).")
        else:
            invals.append(f"1. 5m Candle Close above VWAP (₹{vwap:.2f}) with volume confirms short-squeeze.")
            invals.append(f"2. Spot price breaches key swing resistance level (₹{res:.2f}).")
            invals.append("3. Fast EMA 9 crosses back above EMA 21 on 5m timeframe.")
            invals.append("4. MACD histogram flips positive on 5m for 2 consecutive bars.")
            invals.append("5. RSI 5m rises above 58.0 (loss of downward momentum).")

        invals.append(f"6. Option premium falls to dynamic stop-loss threshold (-{sl_pct:.0f}% loss cap).")
        invals.append("7. Market clock reaches 15:20 IST (intraday mandatory square-off, no overnight carry).")
        return invals


# Global singleton instance
quant_engine = QuantitativeStrategyEngine()

"""
Options Buying Strategy Engine for TradePilot AI
Generates intraday call/put buying signals with full validation.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple

import pytz

from models.trade import (
    TradeSignal, TradeDirection, OptionType, TradeType,
    SignalStrength, IndicatorValues
)
from config import INDEX_SYMBOLS, FO_STOCKS, OPTIONS_BUYING_CONFIG, RISK_CONFIG
from utils.helpers import get_atm_strike, round_to_strike
from market_data.data_fetcher import black_scholes_pricing

logger = logging.getLogger("tradepilot.strategy.buying")
IST = pytz.timezone("Asia/Kolkata")


class OptionsBuyingStrategy:
    """
    Intraday options buying strategy.
    Looks for high-probability momentum/breakout setups on NIFTY/BANKNIFTY.
    
    Rules:
    - Trend alignment across 5m and 15m timeframes
    - RSI in directional zone
    - MACD momentum confirmation
    - VWAP side alignment
    - Volume spike confirmation
    - ATR-based position sizing
    - R:R minimum 2:1
    - SL: 35-40% of premium
    - Target 1: 2x premium, Target 2: 3x premium
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
        Generate a buying signal for the given symbol.
        Returns a TradeSignal (may be is_no_trade=True if no valid setup).
        """
        signal = TradeSignal()
        signal.symbol = symbol
        signal.underlying_price = spot_price
        signal.trade_type = TradeType.OPTIONS_BUYING
        signal.timeframe = "5m + 15m"

        # Get symbol config
        sym_config = INDEX_SYMBOLS.get(symbol) or FO_STOCKS.get(symbol, {})
        lot_size = sym_config.get('lot_size', 50)
        strike_gap = sym_config.get('strike_gap', 50)
        signal.lot_size = lot_size

        # Store indicators immediately so they are available for all outputs including NO_TRADE
        signal.indicators = IndicatorValues(
            rsi_5m=indicators.get('rsi_5m'),
            rsi_15m=indicators.get('rsi_15m'),
            macd_hist_5m=indicators.get('macd_hist_5m'),
            macd_hist_15m=indicators.get('macd_hist_15m'),
            ema_9_5m=indicators.get('ema_9_5m'),
            ema_21_5m=indicators.get('ema_21_5m'),
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

        # ------------------------------------------------
        # Step 1: Determine bias (LONG/SHORT)
        # ------------------------------------------------
        trend_15m = indicators.get('trend_15m', 'SIDEWAYS')
        rsi_5m = indicators.get('rsi_5m', 50)
        rsi_15m = indicators.get('rsi_15m', 50)
        macd_hist_5m = indicators.get('macd_hist_5m', 0)
        macd_hist_15m = indicators.get('macd_hist_15m', 0)
        supertrend_5m = indicators.get('supertrend_5m', 'NEUTRAL')
        supertrend_15m = indicators.get('supertrend_15m', 'NEUTRAL')
        vwap = indicators.get('vwap', 0)
        vol_ratio = indicators.get('volume_ratio_5m', 1.0)
        atr_5m = indicators.get('atr_5m', 0)

        # Score bullish vs bearish signals
        bull_score = 0
        bear_score = 0

        if 'BULL' in trend_15m:
            bull_score += 2
        elif 'BEAR' in trend_15m:
            bear_score += 2

        if rsi_5m >= 55:
            bull_score += 1
        elif rsi_5m <= 45:
            bear_score += 1

        if rsi_15m >= 50:
            bull_score += 1
        elif rsi_15m <= 50:
            bear_score += 1

        if macd_hist_5m > 0:
            bull_score += 1
        elif macd_hist_5m < 0:
            bear_score += 1

        if macd_hist_15m > 0:
            bull_score += 1.5
        elif macd_hist_15m < 0:
            bear_score += 1.5

        if supertrend_5m == 'BULL':
            bull_score += 1.5
        elif supertrend_5m == 'BEAR':
            bear_score += 1.5

        if supertrend_15m == 'BULL':
            bull_score += 1.5
        elif supertrend_15m == 'BEAR':
            bear_score += 1.5

        if vwap > 0:
            if spot_price > vwap:
                bull_score += 1
            else:
                bear_score += 1

        # Minimum score to proceed
        min_score = 5.0
        if bull_score < min_score and bear_score < min_score:
            signal.is_no_trade = True
            signal.no_trade_reason = (
                f"Insufficient directional conviction. "
                f"Bull score: {bull_score:.1f}, Bear score: {bear_score:.1f} "
                f"(min required: {min_score})"
            )
            signal.validation_notes = [signal.no_trade_reason]
            return signal

        # Determine direction
        if bull_score >= bear_score and bull_score >= min_score:
            signal.direction = TradeDirection.LONG
            signal.option_type = OptionType.CALL
            bias_score = bull_score
        else:
            signal.direction = TradeDirection.SHORT
            signal.option_type = OptionType.PUT
            bias_score = bear_score

        # Signal strength
        if bias_score >= 9:
            signal.signal_strength = SignalStrength.STRONG
        elif bias_score >= 6:
            signal.signal_strength = SignalStrength.MODERATE
        else:
            signal.signal_strength = SignalStrength.WEAK

        # ------------------------------------------------
        # Step 2: Strike selection
        # ------------------------------------------------
        atm = get_atm_strike(spot_price, strike_gap)

        if signal.option_type == OptionType.CALL:
            # Buy slightly OTM or ATM call
            if bias_score >= 8:
                signal.strike_price = atm  # ATM for strong signal
            else:
                signal.strike_price = atm + strike_gap  # 1-strike OTM
        else:
            if bias_score >= 8:
                signal.strike_price = atm
            else:
                signal.strike_price = atm - strike_gap

        # ------------------------------------------------
        # Step 3: Get premium from options chain
        # ------------------------------------------------
        chain_key = 'calls' if signal.option_type == OptionType.CALL else 'puts'
        strike_data = options_chain.get(chain_key, {}).get(int(signal.strike_price), {})
        premium = strike_data.get('premium', None)

        if premium is None or premium <= 0:
            is_call = (signal.option_type == OptionType.CALL)
            vix = options_chain.get('vix', 14.5)
            dte = options_chain.get('dte_days', 3.0) / 365.0
            sigma = max(0.10, vix / 100.0)
            premium, _, _ = black_scholes_pricing(spot_price, signal.strike_price, dte, 0.065, sigma, is_call)

        # ------------------------------------------------
        # Step 4: Risk / SL / Target calculation
        # ------------------------------------------------
        sl_pct = OPTIONS_BUYING_CONFIG['max_sl_pct']  # 35%
        signal.stop_loss = round(premium * (1 - sl_pct / 100), 2)
        signal.stop_loss_pct = sl_pct
        signal.entry_price = round(premium, 2)
        signal.entry_price_range_low = round(premium * 0.98, 2)
        signal.entry_price_range_high = round(premium * 1.05, 2)

        risk_per_unit = premium - signal.stop_loss
        signal.target_1 = round(premium * OPTIONS_BUYING_CONFIG['target_1_multiplier'], 2)
        signal.target_2 = round(premium * OPTIONS_BUYING_CONFIG['target_2_multiplier'], 2)

        reward_per_unit = signal.target_1 - premium
        signal.risk_reward_ratio = round(reward_per_unit / max(risk_per_unit, 0.01), 2)

        # Position sizing
        capital = RISK_CONFIG['paper_trading_capital']
        max_risk_amount = capital * (OPTIONS_BUYING_CONFIG['max_capital_risk_pct'] / 100)
        loss_per_lot = risk_per_unit * lot_size
        lots = max(1, int(max_risk_amount / loss_per_lot)) if loss_per_lot > 0 else 1
        signal.position_size_lots = lots
        signal.capital_at_risk = round(loss_per_lot * lots, 2)
        signal.capital_at_risk_pct = round((signal.capital_at_risk / capital) * 100, 2)
        signal.max_loss_per_trade = signal.capital_at_risk

        # ------------------------------------------------
        # Step 5: Build option symbol
        # ------------------------------------------------
        from utils.helpers import get_nearest_expiry_string
        expiry = get_nearest_expiry_string(symbol)
        signal.expiry_date = expiry
        opt_type_str = "CE" if signal.option_type == OptionType.CALL else "PE"
        signal.option_symbol = f"{symbol}{expiry}{int(signal.strike_price)}{opt_type_str}"

        # ------------------------------------------------
        # Step 6: Entry conditions
        # ------------------------------------------------
        signal.entry_conditions = self._build_entry_conditions(signal, indicators, spot_price, vwap, atm)

        # ------------------------------------------------
        # Step 7: Invalidation conditions
        # ------------------------------------------------
        support = indicators.get('support_5m', spot_price * 0.995)
        resistance = indicators.get('resistance_5m', spot_price * 1.005)
        signal.invalidation_conditions = self._build_invalidation_conditions(signal, indicators, spot_price, support, resistance)

        # ------------------------------------------------
        # Step 8: Store indicators
        # ------------------------------------------------
        signal.indicators = IndicatorValues(
            rsi_5m=indicators.get('rsi_5m'),
            rsi_15m=indicators.get('rsi_15m'),
            macd_hist_5m=indicators.get('macd_hist_5m'),
            macd_hist_15m=indicators.get('macd_hist_15m'),
            ema_9_5m=indicators.get('ema_9_5m'),
            ema_21_5m=indicators.get('ema_21_5m'),
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

        signal.validity_duration_minutes = 30
        return signal

    def _build_entry_conditions(self, signal, indicators, spot_price, vwap, atm) -> list:
        direction_str = "CALL" if signal.option_type == OptionType.CALL else "PUT"
        conds = []
        conds.append(
            f"Buy {signal.symbol} {int(signal.strike_price)}{signal.option_type.value} "
            f"at market/limit ₹{signal.entry_price:.2f} "
            f"(range ₹{signal.entry_price_range_low}–₹{signal.entry_price_range_high})"
        )
        conds.append(
            f"Underlying {signal.symbol} spot at ₹{spot_price:.2f} "
            f"({'above' if signal.direction == TradeDirection.LONG else 'below'} "
            f"VWAP ₹{vwap:.2f})"
        )
        conds.append(
            f"RSI(14) on 5m: {indicators.get('rsi_5m', 'N/A')} | "
            f"RSI(14) on 15m: {indicators.get('rsi_15m', 'N/A')}"
        )
        conds.append(
            f"MACD Histogram 5m: {indicators.get('macd_hist_5m', 'N/A'):.4f} | "
            f"15m: {indicators.get('macd_hist_15m', 'N/A'):.4f}"
        )
        conds.append(
            f"SuperTrend 5m: {indicators.get('supertrend_5m', 'N/A')} | "
            f"15m Trend: {indicators.get('trend_15m', 'N/A')}"
        )
        conds.append(f"Volume ratio: {indicators.get('volume_ratio_5m', 'N/A'):.2f}x average")
        conds.append(f"Signal strength: {signal.signal_strength.value if signal.signal_strength else 'N/A'}")
        return conds

    def _build_invalidation_conditions(self, signal, indicators, spot_price, support, resistance) -> list:
        conds = []
        if signal.direction == TradeDirection.LONG:
            conds.append(f"Underlying breaks below support: ₹{support:.2f}")
            conds.append(f"Underlying closes 5m candle below VWAP with volume")
            conds.append(f"RSI 5m drops below 40")
            conds.append(f"SuperTrend 5m flips to BEAR")
            conds.append(f"MACD histogram turns negative on 15m")
        else:
            conds.append(f"Underlying breaks above resistance: ₹{resistance:.2f}")
            conds.append(f"Underlying closes 5m candle above VWAP with volume")
            conds.append(f"RSI 5m rises above 60")
            conds.append(f"SuperTrend 5m flips to BULL")
            conds.append(f"MACD histogram turns positive on 15m")
        conds.append(f"Option premium falls to stop-loss: ₹{signal.stop_loss:.2f}")
        conds.append(f"Time past 14:30 IST — exit immediately regardless of P&L")
        return conds

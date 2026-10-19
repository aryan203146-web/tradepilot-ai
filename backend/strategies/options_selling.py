"""
Options Selling Strategy Engine for TradePilot AI
Generates intraday options selling signals (covered / credit strategies).

Rules:
- Only sell when IV percentile >= 40%
- Prefer sideways or range-bound market
- Sell OTM options (delta < 0.35)
- Target: keep 50-70% of premium received
- SL: exit if premium doubles (2x received)
- Stricter capital risk: max 1.5% per trade
- Time decay works in our favor (theta positive)
"""
import logging
import math
from typing import Optional, Dict

import pytz

from models.trade import (
    TradeSignal, TradeDirection, OptionType, TradeType,
    SignalStrength, IndicatorValues
)
from config import INDEX_SYMBOLS, FO_STOCKS, OPTIONS_SELLING_CONFIG, RISK_CONFIG
from utils.helpers import get_atm_strike
from market_data.data_fetcher import black_scholes_pricing

logger = logging.getLogger("tradepilot.strategy.selling")
IST = pytz.timezone("Asia/Kolkata")


class OptionsSellingStrategy:
    """
    Intraday options selling strategy.
    Sells OTM options in high-IV, range-bound conditions.
    Uses premium decay (theta) as profit driver.
    """

    def generate_signal(
        self,
        symbol: str,
        spot_price: float,
        indicators: Dict,
        options_chain: Dict,
    ) -> TradeSignal:
        """
        Generate an options selling signal.
        Returns TradeSignal (may be is_no_trade=True).
        """
        signal = TradeSignal()
        signal.symbol = symbol
        signal.underlying_price = spot_price
        signal.trade_type = TradeType.OPTIONS_SELLING
        signal.timeframe = "5m + 15m"

        sym_config = INDEX_SYMBOLS.get(symbol) or FO_STOCKS.get(symbol, {})
        lot_size = sym_config.get('lot_size', 50)
        strike_gap = sym_config.get('strike_gap', 50)
        signal.lot_size = lot_size

        # Populate indicators immediately for complete reporting
        signal.indicators = IndicatorValues(
            rsi_5m=indicators.get('rsi_5m'),
            rsi_15m=indicators.get('rsi_15m'),
            macd_hist_5m=indicators.get('macd_hist_5m'),
            macd_hist_15m=indicators.get('macd_hist_15m'),
            ema_9_5m=indicators.get('ema_9_5m'),
            ema_21_5m=indicators.get('ema_21_5m'),
            vwap=indicators.get('vwap'),
            atr_5m=indicators.get('atr_5m'),
            volume_ratio=indicators.get('volume_ratio_5m'),
            supertrend_5m=indicators.get('supertrend_5m'),
            supertrend_15m=indicators.get('supertrend_15m'),
            pcr=options_chain.get('pcr'),
            iv_percentile=options_chain.get('iv_percentile'),
            support_level=indicators.get('support_5m'),
            resistance_level=indicators.get('resistance_5m'),
        )

        # ------------------------------------------------
        # Step 1: IV check — prerequisite for selling
        # ------------------------------------------------
        iv_percentile = options_chain.get('iv_percentile', 0)
        min_iv = OPTIONS_SELLING_CONFIG['min_iv_percentile']

        if iv_percentile < min_iv:
            signal.is_no_trade = True
            signal.no_trade_reason = (
                f"IV percentile {iv_percentile:.0f}% below minimum {min_iv}%. "
                f"Options selling not viable — premium too cheap. "
                f"Wait for IV spike or look for buying opportunities instead."
            )
            signal.validation_notes = [signal.no_trade_reason]
            return signal

        # ------------------------------------------------
        # Step 2: Determine which side to sell
        # ------------------------------------------------
        trend_15m = indicators.get('trend_15m', 'SIDEWAYS')
        rsi_5m = indicators.get('rsi_5m', 50)
        rsi_15m = indicators.get('rsi_15m', 50)
        pcr = options_chain.get('pcr', 1.0)
        vwap = indicators.get('vwap', 0)
        supertrend_5m = indicators.get('supertrend_5m', '')

        # Selling strategy selection
        # - Sell calls when: overbought RSI, bearish/sideways trend, price near resistance
        # - Sell puts when: oversold RSI, bullish/sideways trend, price near support

        sell_call_score = 0
        sell_put_score = 0

        # Market must be sideways or weakly trending for selling
        if 'SIDEWAYS' in trend_15m or 'WEAK' in trend_15m:
            sell_call_score += 1
            sell_put_score += 1
        elif 'STRONG_BEAR' in trend_15m:
            sell_call_score += 2  # Strong bear → sell calls
        elif 'STRONG_BULL' in trend_15m:
            sell_put_score += 2  # Strong bull → sell puts (but risky)

        # RSI extremes favor selling
        if rsi_5m >= 68:
            sell_call_score += 2
        elif rsi_5m <= 32:
            sell_put_score += 2
        elif rsi_5m >= 60:
            sell_call_score += 1
        elif rsi_5m <= 40:
            sell_put_score += 1

        # PCR
        if pcr <= 0.8:
            sell_call_score += 1  # Low PCR = bearish sentiment
        elif pcr >= 1.2:
            sell_put_score += 1   # High PCR = bullish sentiment

        # VWAP
        if vwap > 0:
            if spot_price < vwap:
                sell_call_score += 0.5
            else:
                sell_put_score += 0.5

        min_selling_score = 3.0
        if sell_call_score < min_selling_score and sell_put_score < min_selling_score:
            signal.is_no_trade = True
            signal.no_trade_reason = (
                f"No clear options selling setup. "
                f"Call-sell score: {sell_call_score:.1f}, Put-sell score: {sell_put_score:.1f}. "
                f"Market structure not ideal for premium collection."
            )
            signal.validation_notes = [signal.no_trade_reason]
            return signal

        # Choose which to sell
        if sell_call_score >= sell_put_score and sell_call_score >= min_selling_score:
            signal.direction = TradeDirection.SHORT  # Bearish on underlying
            signal.option_type = OptionType.CALL     # Sell Call
            bias_score = sell_call_score
        else:
            signal.direction = TradeDirection.LONG   # Bullish on underlying
            signal.option_type = OptionType.PUT      # Sell Put
            bias_score = sell_put_score

        # Signal strength
        if bias_score >= 6:
            signal.signal_strength = SignalStrength.STRONG
        elif bias_score >= 4:
            signal.signal_strength = SignalStrength.MODERATE
        else:
            signal.signal_strength = SignalStrength.WEAK

        # ------------------------------------------------
        # Step 3: Strike selection — sell OTM (delta < 0.35)
        # ------------------------------------------------
        atm = get_atm_strike(spot_price, strike_gap)

        if signal.option_type == OptionType.CALL:
            # Sell 1-2 strikes OTM call
            signal.strike_price = atm + (2 * strike_gap)  # ~0.3 delta typically
        else:
            # Sell 1-2 strikes OTM put
            signal.strike_price = atm - (2 * strike_gap)

        # ------------------------------------------------
        # Step 4: Get premium
        # ------------------------------------------------
        chain_key = 'calls' if signal.option_type == OptionType.CALL else 'puts'
        strike_data = options_chain.get(chain_key, {}).get(int(signal.strike_price), {})
        premium = strike_data.get('premium', None)
        delta = abs(strike_data.get('delta', 0.25))
        theta = strike_data.get('theta', -5.0)

        if premium is None or premium <= 0:
            is_call = (signal.option_type == OptionType.CALL)
            vix = options_chain.get('vix', 14.5)
            dte = options_chain.get('dte_days', 3.0) / 365.0
            sigma = max(0.10, vix / 100.0)
            premium, delta, theta = black_scholes_pricing(spot_price, signal.strike_price, dte, 0.065, sigma, is_call)
            delta = abs(delta)

        # ------------------------------------------------
        # Step 5: SL and Target for selling
        # ------------------------------------------------
        # Selling: we RECEIVE premium. SL = exit when premium doubles.
        # Target = keep 50-70% of received premium
        sl_multiplier = OPTIONS_SELLING_CONFIG['sl_premium_multiplier']  # 2.0x
        target_1_pct = OPTIONS_SELLING_CONFIG['target_pct']    # 50%
        target_2_pct = OPTIONS_SELLING_CONFIG['target_2_pct']  # 70%

        signal.entry_price = round(premium, 2)
        signal.stop_loss = round(premium * sl_multiplier, 2)    # Exit if doubles
        signal.stop_loss_pct = ((signal.stop_loss - premium) / premium) * 100
        signal.target_1 = round(premium * (1 - target_1_pct / 100), 2)  # Keep 50%
        signal.target_2 = round(premium * (1 - target_2_pct / 100), 2)  # Keep 70%

        # R:R for selling: reward = premium received, risk = additional loss
        reward_per_unit = premium * (target_1_pct / 100)  # 50% of premium
        risk_per_unit = premium * (sl_multiplier - 1)     # 100% additional loss
        signal.risk_reward_ratio = round(reward_per_unit / max(risk_per_unit, 0.01), 2)

        signal.entry_price_range_low = round(premium * 0.95, 2)
        signal.entry_price_range_high = round(premium * 1.03, 2)

        # Position sizing (conservative for selling)
        capital = RISK_CONFIG['paper_trading_capital']
        max_risk_pct = OPTIONS_SELLING_CONFIG['max_capital_risk_pct']
        max_risk_amount = capital * (max_risk_pct / 100)
        loss_per_lot = risk_per_unit * lot_size
        lots = max(1, int(max_risk_amount / loss_per_lot)) if loss_per_lot > 0 else 1
        signal.position_size_lots = lots
        signal.capital_at_risk = round(loss_per_lot * lots, 2)
        signal.capital_at_risk_pct = round((signal.capital_at_risk / capital) * 100, 2)
        signal.max_loss_per_trade = signal.capital_at_risk

        # ------------------------------------------------
        # Step 6: Option symbol
        # ------------------------------------------------
        from utils.helpers import get_nearest_expiry_string
        expiry = get_nearest_expiry_string(symbol)
        signal.expiry_date = expiry
        opt_type_str = "CE" if signal.option_type == OptionType.CALL else "PE"
        signal.option_symbol = f"{symbol}{expiry}{int(signal.strike_price)}{opt_type_str}"

        # ------------------------------------------------
        # Step 7: Entry conditions
        # ------------------------------------------------
        signal.entry_conditions = self._build_entry_conditions(
            signal, indicators, spot_price, vwap, premium, delta, theta, iv_percentile, pcr
        )

        # ------------------------------------------------
        # Step 8: Invalidation conditions
        # ------------------------------------------------
        support = indicators.get('support_5m', spot_price * 0.995)
        resistance = indicators.get('resistance_5m', spot_price * 1.005)
        signal.invalidation_conditions = self._build_invalidation_conditions(
            signal, indicators, spot_price, support, resistance
        )

        # ------------------------------------------------
        # Step 9: Store indicators
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
            volume_ratio=indicators.get('volume_ratio_5m'),
            supertrend_5m=indicators.get('supertrend_5m'),
            supertrend_15m=indicators.get('supertrend_15m'),
            pcr=pcr,
            iv_percentile=iv_percentile,
            support_level=indicators.get('support_5m'),
            resistance_level=indicators.get('resistance_5m'),
        )

        signal.validity_duration_minutes = 45  # Selling signals can wait longer
        return signal

    def _build_entry_conditions(self, signal, indicators, spot_price, vwap, premium, delta, theta, iv_pct, pcr) -> list:
        conds = []
        action = "SELL" if signal.option_type == OptionType.CALL else "SELL"
        conds.append(
            f"SELL {signal.symbol} {int(signal.strike_price)}{signal.option_type.value} "
            f"at ₹{signal.entry_price:.2f} (collect premium)"
        )
        conds.append(f"IV Percentile: {iv_pct:.0f}% — premium collection justified")
        conds.append(f"Option Delta: ~{delta:.2f} (OTM, limited probability of assignment)")
        conds.append(f"Daily Theta: ₹{abs(theta):.2f}/lot — time decay working in our favor")
        conds.append(f"PCR: {pcr:.2f} | RSI 5m: {indicators.get('rsi_5m', 'N/A')} | 15m Trend: {indicators.get('trend_15m', 'N/A')}")
        conds.append(f"Underlying spot: ₹{spot_price:.2f} | VWAP: ₹{vwap:.2f}")
        conds.append(f"SuperTrend 5m: {indicators.get('supertrend_5m', 'N/A')}")
        conds.append(
            f"Profit target: Exit when premium falls to ₹{signal.target_1:.2f} (50% profit) "
            f"or ₹{signal.target_2:.2f} (70% profit)"
        )
        return conds

    def _build_invalidation_conditions(self, signal, indicators, spot_price, support, resistance) -> list:
        conds = []
        if signal.option_type == OptionType.CALL:
            conds.append(f"Underlying breaks above resistance ₹{resistance:.2f} with strong volume")
            conds.append(f"Premium rises above ₹{signal.stop_loss:.2f} (exit immediately — 2x received)")
            conds.append(f"RSI 5m rises above 65 (momentum building against position)")
            conds.append(f"SuperTrend 5m flips to BULL")
            conds.append(f"Large gap-up or sudden spike above strike ₹{int(signal.strike_price)}")
        else:
            conds.append(f"Underlying breaks below support ₹{support:.2f} with strong volume")
            conds.append(f"Premium rises above ₹{signal.stop_loss:.2f} (exit immediately — 2x received)")
            conds.append(f"RSI 5m falls below 35 (momentum building against position)")
            conds.append(f"SuperTrend 5m flips to BEAR")
            conds.append(f"Large gap-down or sudden drop below strike ₹{int(signal.strike_price)}")
        conds.append(f"Force exit at 15:20 IST regardless of P&L")
        return conds

"""
Signal Orchestrator for TradePilot AI
Coordinates data fetching, indicator computation, strategy execution,
validation, and signal delivery.
"""
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import pytz

from market_data.data_fetcher import fetch_market_data, get_options_chain_mock
from indicators.technical import compute_all_indicators
from strategies.options_buying import OptionsBuyingStrategy
from strategies.options_selling import OptionsSellingStrategy
from strategies.signal_validator import SignalValidator
from models.trade import TradeSignal
from utils.helpers import is_market_open, is_new_trade_allowed
from config import INDEX_SYMBOLS, FO_STOCKS, RISK_CONFIG

logger = logging.getLogger("tradepilot.orchestrator")
IST = pytz.timezone("Asia/Kolkata")


class SignalOrchestrator:
    """
    Orchestrates the full signal generation pipeline:
    1. Fetch market data (5m + 15m)
    2. Compute all indicators
    3. Run options buying strategy
    4. Run options selling strategy
    5. Validate signals
    6. Return best validated signals (max 3-4/day)
    """

    def __init__(self, daily_trades_count: int = 0):
        self.buying_strategy = OptionsBuyingStrategy()
        self.selling_strategy = OptionsSellingStrategy()
        self.validator = SignalValidator()
        self.daily_trades_count = daily_trades_count
        self._cache: Dict[str, dict] = {}
        self._cache_time: Dict[str, datetime] = {}
        # Keep live LTPs responsive when the dashboard is set to auto-refresh.
        self._cache_ttl_seconds = 5

    def _is_cache_valid(self, key: str) -> bool:
        if key not in self._cache_time:
            return False
        age = (datetime.now(IST) - self._cache_time[key]).total_seconds()
        return age < self._cache_ttl_seconds

    def analyze_symbol(self, symbol: str) -> Tuple[Optional[TradeSignal], Optional[TradeSignal], Dict]:
        """
        Run full analysis for a single symbol.
        Returns (buying_signal, selling_signal, market_data_dict)
        """
        logger.info(f"Analyzing {symbol}...")

        # Check cache
        cache_key = f"{symbol}"
        if self._is_cache_valid(cache_key):
            cached = self._cache[cache_key]
            return cached.get('buying'), cached.get('selling'), cached.get('market_data', {})

        # 1. Fetch market data
        market_data = fetch_market_data(symbol)
        if not market_data or market_data.get('spot_price') is None:
            logger.error(f"No market data for {symbol}")
            return None, None, {}

        spot_price = market_data['spot_price']
        df_5m = market_data.get('df_5m')
        df_15m = market_data.get('df_15m')
        strike_gap = market_data.get('strike_gap', 50)
        lot_size = market_data.get('lot_size', 50)

        # 2. Compute indicators
        indicators = compute_all_indicators(df_5m, df_15m)
        indicators['spot_price'] = spot_price

        # 3. Get options chain
        options_chain = get_options_chain_mock(symbol, spot_price, strike_gap)

        # Add PCR and IV to indicators for validator
        indicators['pcr'] = options_chain.get('pcr', 1.0)
        indicators['iv_percentile'] = options_chain.get('iv_percentile', 50)

        # Candle timestamp for backtest / session time alignment
        as_of = None
        if df_5m is not None and len(df_5m) > 0:
            try:
                last_dt = df_5m.index[-1]
                if hasattr(last_dt, 'to_pydatetime'):
                    as_of = last_dt.to_pydatetime()
                    if as_of.tzinfo is None:
                        as_of = IST.localize(as_of)
            except Exception:
                as_of = None

        # 4. Generate buying signal
        buying_signal = self.buying_strategy.generate_signal(
            symbol=symbol,
            spot_price=spot_price,
            indicators=indicators,
            options_chain=options_chain,
            daily_trades_count=self.daily_trades_count,
            as_of=as_of,
        )

        # 5. Validate buying signal
        if not buying_signal.is_no_trade:
            valid, notes = self.validator.validate_buying_signal(buying_signal, indicators)
            buying_signal.validation_passed = valid
            buying_signal.validation_notes = notes
            if not valid:
                buying_signal.is_no_trade = True
                buying_signal.no_trade_reason = "Buying signal failed validation checks"

        # 6. Generate selling signal
        selling_signal = self.selling_strategy.generate_signal(
            symbol=symbol,
            spot_price=spot_price,
            indicators=indicators,
            options_chain=options_chain,
        )

        # 7. Validate selling signal
        if not selling_signal.is_no_trade:
            valid, notes = self.validator.validate_selling_signal(selling_signal, indicators)
            selling_signal.validation_passed = valid
            selling_signal.validation_notes = notes
            if not valid:
                selling_signal.is_no_trade = True
                selling_signal.no_trade_reason = "Selling signal failed validation checks"

        market_info = {
            'symbol': symbol,
            'spot_price': spot_price,
            'lot_size': lot_size,
            'strike_gap': strike_gap,
            'price_source': market_data.get('price_source', 'Unknown'),
            'price_updated_at': market_data.get('price_updated_at', ''),
            'indicators': indicators,
            'options_chain_summary': {
                'pcr': options_chain.get('pcr'),
                'iv_percentile': options_chain.get('iv_percentile'),
                'atm_call_premium': self._get_atm_premium(options_chain, spot_price, strike_gap, 'calls'),
                'atm_put_premium': self._get_atm_premium(options_chain, spot_price, strike_gap, 'puts'),
            },
            'data_bars_5m': len(df_5m) if df_5m is not None else 0,
            'data_bars_15m': len(df_15m) if df_15m is not None else 0,
            'fetched_at': market_data.get('fetched_at', ''),
        }

        # Cache results
        self._cache[cache_key] = {
            'buying': buying_signal,
            'selling': selling_signal,
            'market_data': market_info,
        }
        self._cache_time[cache_key] = datetime.now(IST)

        return buying_signal, selling_signal, market_info

    def _get_atm_premium(self, chain: dict, spot: float, gap: int, side: str) -> Optional[float]:
        atm = int(round(spot / gap) * gap)
        return chain.get(side, {}).get(atm, {}).get('premium')

    def scan_all_symbols(
        self,
        symbols: List[str] = None,
        daily_trades_count: int = 0
    ) -> Dict:
        """
        Scan all configured symbols and return best signals.
        
        Returns dict with:
        - signals: list of all valid signals
        - no_trade_reasons: list of rejection reasons
        - market_data: dict by symbol
        - scan_time: timestamp
        - trading_allowed: bool
        """
        self.daily_trades_count = daily_trades_count

        if symbols is None:
            symbols = list(INDEX_SYMBOLS.keys())

        results = {
            'scan_time': datetime.now(IST).isoformat(),
            'market_open': is_market_open(),
            'new_trade_allowed': is_new_trade_allowed(),
            'daily_trades_count': daily_trades_count,
            'max_trades_per_day': RISK_CONFIG['max_trades_per_day'],
            'signals': [],
            'no_trade_symbols': [],
            'market_data': {},
        }

        if daily_trades_count >= RISK_CONFIG['max_trades_per_day']:
            results['system_message'] = f"Daily trade limit ({RISK_CONFIG['max_trades_per_day']}) reached. No new signals."

        for symbol in symbols:
            try:
                buying, selling, mdata = self.analyze_symbol(symbol)
                results['market_data'][symbol] = mdata

                signals_for_symbol = []

                if buying and not buying.is_no_trade:
                    signals_for_symbol.append(buying.to_dict())
                    logger.info(f"✅ BUYING signal for {symbol}: {buying.option_symbol}")

                if selling and not selling.is_no_trade:
                    signals_for_symbol.append(selling.to_dict())
                    logger.info(f"✅ SELLING signal for {symbol}: {selling.option_symbol}")

                if signals_for_symbol:
                    results['signals'].extend(signals_for_symbol)
                else:
                    no_trade_reasons = []
                    rej_codes = []
                    if buying and buying.no_trade_reason:
                        no_trade_reasons.append(f"Buying: {buying.no_trade_reason}")
                        rej_codes.extend(buying.rejection_codes or [])
                    if selling and selling.no_trade_reason:
                        no_trade_reasons.append(f"Selling: {selling.no_trade_reason}")
                        rej_codes.extend(selling.rejection_codes or [])
                    results['no_trade_symbols'].append({
                        'symbol': symbol,
                        'spot_price': mdata.get('spot_price'),
                        'reasons': no_trade_reasons or ["No valid setup found"],
                        'rejection_codes': list(dict.fromkeys(rej_codes)),
                        'indicators': mdata.get('indicators', {})
                    })
                    logger.info(f"⛔ NO TRADE for {symbol}: {', '.join(no_trade_reasons)}")

            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}", exc_info=True)
                results['no_trade_symbols'].append({
                    'symbol': symbol,
                    'reasons': [f"Analysis error: {str(e)}"],
                })

        # Sort signals by signal strength
        strength_order = {'STRONG': 0, 'MODERATE': 1, 'WEAK': 2}
        results['signals'].sort(key=lambda s: strength_order.get(s.get('signal_strength', 'WEAK'), 2))

        # Enforce max trades limit
        remaining_trades = RISK_CONFIG['max_trades_per_day'] - daily_trades_count
        if len(results['signals']) > remaining_trades:
            results['signals'] = results['signals'][:remaining_trades]
            results['signals_truncated'] = True

        results['total_valid_signals'] = len(results['signals'])
        results['no_trade'] = len(results['signals']) == 0

        return results

"""
Trade and Signal data models for TradePilot AI
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from enum import Enum
import uuid


class TradeDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class OptionType(Enum):
    CALL = "CE"
    PUT = "PE"


class TradeType(Enum):
    OPTIONS_BUYING = "OPTIONS_BUYING"
    OPTIONS_SELLING = "OPTIONS_SELLING"


class TradeStatus(Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    NO_TRADE = "NO_TRADE"


class SignalStrength(Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


@dataclass
class IndicatorValues:
    rsi_5m: Optional[float] = None
    rsi_15m: Optional[float] = None
    macd_5m: Optional[float] = None
    macd_signal_5m: Optional[float] = None
    macd_hist_5m: Optional[float] = None
    macd_15m: Optional[float] = None
    macd_signal_15m: Optional[float] = None
    macd_hist_15m: Optional[float] = None
    bb_upper_5m: Optional[float] = None
    bb_middle_5m: Optional[float] = None
    bb_lower_5m: Optional[float] = None
    bb_upper_15m: Optional[float] = None
    bb_middle_15m: Optional[float] = None
    bb_lower_15m: Optional[float] = None
    ema_9_5m: Optional[float] = None
    ema_21_5m: Optional[float] = None
    ema_50_15m: Optional[float] = None
    ema_200_15m: Optional[float] = None
    vwap: Optional[float] = None
    atr_5m: Optional[float] = None
    atr_15m: Optional[float] = None
    volume_ratio: Optional[float] = None  # current vol vs 20-bar avg
    supertrend_5m: Optional[str] = None  # "BULL" or "BEAR"
    supertrend_15m: Optional[str] = None
    pcr: Optional[float] = None  # Put-Call Ratio
    iv_percentile: Optional[float] = None  # IV percentile
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None


@dataclass
class TradeSignal:
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8].upper())
    generated_at: datetime = field(default_factory=datetime.now)
    symbol: str = ""  # e.g. NIFTY, BANKNIFTY
    underlying_price: float = 0.0
    strike_price: float = 0.0
    option_type: Optional[OptionType] = None
    expiry_date: str = ""
    option_symbol: str = ""  # Full option symbol
    direction: Optional[TradeDirection] = None
    trade_type: Optional[TradeType] = None
    signal_strength: Optional[SignalStrength] = None

    # Entry conditions
    entry_price: float = 0.0
    entry_price_range_low: float = 0.0
    entry_price_range_high: float = 0.0
    entry_conditions: List[str] = field(default_factory=list)

    # Risk management
    stop_loss: float = 0.0
    stop_loss_pct: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    risk_reward_ratio: float = 0.0
    max_loss_per_trade: float = 0.0
    position_size_lots: int = 1
    lot_size: int = 0
    capital_at_risk: float = 0.0
    capital_at_risk_pct: float = 0.0

    # Invalidation
    invalidation_conditions: List[str] = field(default_factory=list)
    validity_duration_minutes: int = 30

    # Explicit Quantitative Engine structures
    entry_rules: List[dict] = field(default_factory=list)
    exit_roadmap: Optional[dict] = None
    rejection_codes: List[str] = field(default_factory=list)
    score_pct: float = 0.0

    # Indicators at signal time
    indicators: IndicatorValues = field(default_factory=IndicatorValues)

    # Timeframe
    timeframe: str = "5m"  # Primary timeframe

    # Validation
    validation_passed: bool = False
    validation_notes: List[str] = field(default_factory=list)
    is_no_trade: bool = False
    no_trade_reason: str = ""

    def to_dict(self):
        return {
            "signal_id": self.signal_id,
            "generated_at": self.generated_at.isoformat(),
            "symbol": self.symbol,
            "underlying_price": self.underlying_price,
            "strike_price": self.strike_price,
            "option_type": self.option_type.value if self.option_type else None,
            "expiry_date": self.expiry_date,
            "option_symbol": self.option_symbol,
            "direction": self.direction.value if self.direction else None,
            "trade_type": self.trade_type.value if self.trade_type else None,
            "signal_strength": self.signal_strength.value if self.signal_strength else None,
            "entry_price": self.entry_price,
            "entry_price_range": [self.entry_price_range_low, self.entry_price_range_high],
            "entry_conditions": self.entry_conditions,
            "stop_loss": self.stop_loss,
            "stop_loss_pct": self.stop_loss_pct,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "risk_reward_ratio": self.risk_reward_ratio,
            "position_size_lots": self.position_size_lots,
            "lot_size": self.lot_size,
            "capital_at_risk": self.capital_at_risk,
            "capital_at_risk_pct": self.capital_at_risk_pct,
            "max_loss_per_trade": self.max_loss_per_trade,
            "invalidation_conditions": self.invalidation_conditions,
            "validity_duration_minutes": self.validity_duration_minutes,
            "entry_rules": self.entry_rules,
            "exit_roadmap": self.exit_roadmap,
            "rejection_codes": self.rejection_codes,
            "score_pct": self.score_pct,
            "timeframe": self.timeframe,
            "validation_passed": self.validation_passed,
            "validation_notes": self.validation_notes,
            "is_no_trade": self.is_no_trade,
            "no_trade_reason": self.no_trade_reason,
            "indicators": {
                "rsi_5m": self.indicators.rsi_5m,
                "rsi_15m": self.indicators.rsi_15m,
                "macd_hist_5m": self.indicators.macd_hist_5m,
                "macd_hist_15m": self.indicators.macd_hist_15m,
                "ema_9_5m": self.indicators.ema_9_5m,
                "ema_21_5m": self.indicators.ema_21_5m,
                "vwap": self.indicators.vwap,
                "atr_5m": self.indicators.atr_5m,
                "volume_ratio": self.indicators.volume_ratio,
                "supertrend_5m": self.indicators.supertrend_5m,
                "supertrend_15m": self.indicators.supertrend_15m,
                "pcr": self.indicators.pcr,
                "iv_percentile": self.indicators.iv_percentile,
                "support_level": self.indicators.support_level,
                "resistance_level": self.indicators.resistance_level,
                "bb_upper_5m": self.indicators.bb_upper_5m,
                "bb_lower_5m": self.indicators.bb_lower_5m,
            }
        }


@dataclass
class PaperTrade:
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4())[:10].upper())
    signal_id: str = ""
    symbol: str = ""
    option_symbol: str = ""
    underlying_price_at_entry: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    quantity: int = 0  # lots
    lot_size: int = 0
    trade_type: Optional[TradeType] = None
    option_type: Optional[OptionType] = None
    direction: Optional[TradeDirection] = None
    status: TradeStatus = TradeStatus.PENDING
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    notes: str = ""
    capital_deployed: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0

    def to_dict(self):
        return {
            "trade_id": self.trade_id,
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "option_symbol": self.option_symbol,
            "underlying_price_at_entry": self.underlying_price_at_entry,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "stop_loss": self.stop_loss,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "quantity": self.quantity,
            "lot_size": self.lot_size,
            "trade_type": self.trade_type.value if self.trade_type else None,
            "option_type": self.option_type.value if self.option_type else None,
            "direction": self.direction.value if self.direction else None,
            "status": self.status.value,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct, 2),
            "capital_deployed": self.capital_deployed,
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "notes": self.notes,
        }

"""
Risk Management Engine for TradePilot AI
Enforces all risk rules for intraday F&O trading
"""
import logging
from datetime import datetime
from typing import List, Optional, Tuple
import pytz

from models.trade import PaperTrade, TradeStatus, TradeType
from config import RISK_CONFIG, OPTIONS_BUYING_CONFIG, OPTIONS_SELLING_CONFIG

logger = logging.getLogger("tradepilot.risk")
IST = pytz.timezone("Asia/Kolkata")


class RiskManager:
    def __init__(self, capital: float = None):
        self.capital = capital or RISK_CONFIG['paper_trading_capital']
        self.max_trades_per_day = RISK_CONFIG['max_trades_per_day']
        self.max_total_risk_pct = RISK_CONFIG['max_total_capital_risk']
        self.max_daily_loss_pct = RISK_CONFIG['max_daily_loss_pct']
        self.daily_trades_count = 0
        self.daily_pnl = 0.0
        self.daily_trade_date = datetime.now(IST).date()
        self.real_trading_enabled = RISK_CONFIG['real_trading_enabled']

    def reset_daily_stats(self):
        """Reset daily statistics at market open."""
        today = datetime.now(IST).date()
        if self.daily_trade_date != today:
            self.daily_trades_count = 0
            self.daily_pnl = 0.0
            self.daily_trade_date = today
            logger.info(f"Daily stats reset for {today}")

    def update_daily_pnl(self, pnl: float):
        """Update daily PnL."""
        self.daily_pnl += pnl

    def can_take_new_trade(self, open_trades: List[PaperTrade], check_time: bool = False) -> Tuple[bool, str]:
        """
        Check if a new trade is allowed based on risk rules.
        Returns (allowed, reason)
        """
        self.reset_daily_stats()

        # Check real trading guard
        if self.real_trading_enabled:
            return False, "REAL TRADING IS DISABLED. Enable explicitly after testing."

        # Check daily trade limit
        if self.daily_trades_count >= self.max_trades_per_day:
            return False, f"Daily trade limit reached ({self.max_trades_per_day} trades/day)"

        # Check daily loss limit
        daily_loss_pct = abs(min(0, self.daily_pnl)) / self.capital * 100
        if daily_loss_pct >= self.max_daily_loss_pct:
            return False, f"Daily loss limit breached ({daily_loss_pct:.1f}% >= {self.max_daily_loss_pct}%)"

        # Check total capital at risk
        total_risk = sum(
            t.capital_deployed for t in open_trades
            if t.status == TradeStatus.OPEN
        )
        total_risk_pct = (total_risk / self.capital) * 100
        if total_risk_pct >= self.max_total_risk_pct:
            return False, f"Max total risk reached ({total_risk_pct:.1f}% >= {self.max_total_risk_pct}%)"

        # Check market timing if requested
        if check_time:
            now = datetime.now(IST)
            no_new_trade_time = now.replace(hour=14, minute=30, second=0)
            market_open_time = now.replace(hour=9, minute=15, second=0)
            if now > no_new_trade_time:
                return False, "No new trades after 14:30 IST (approaching EOD)"
            if now < market_open_time:
                return False, "Market not yet open"

        return True, "OK"

    def calculate_buying_position_size(
        self,
        capital: float,
        premium: float,
        lot_size: int,
        sl_pct: float = None
    ) -> Tuple[int, float, float]:
        """
        Calculate position size for options buying.
        Returns (lots, capital_at_risk, capital_at_risk_pct)
        """
        sl_pct = sl_pct or OPTIONS_BUYING_CONFIG['max_sl_pct']
        max_risk_pct = OPTIONS_BUYING_CONFIG['max_capital_risk_pct']
        max_risk_amount = capital * (max_risk_pct / 100)

        # Loss per lot = premium * lot_size * sl_pct / 100
        loss_per_lot = premium * lot_size * (sl_pct / 100)
        if loss_per_lot <= 0:
            return 1, premium * lot_size, (premium * lot_size / capital) * 100

        lots = int(max_risk_amount / loss_per_lot)
        lots = max(1, lots)

        capital_deployed = lots * lot_size * premium
        capital_at_risk = lots * loss_per_lot
        capital_at_risk_pct = (capital_at_risk / capital) * 100

        return lots, capital_at_risk, min(capital_at_risk_pct, max_risk_pct)

    def calculate_selling_position_size(
        self,
        capital: float,
        premium: float,
        lot_size: int
    ) -> Tuple[int, float, float]:
        """
        Calculate position size for options selling.
        More conservative - risk = potential loss if sl hit.
        Returns (lots, capital_at_risk, capital_at_risk_pct)
        """
        max_risk_pct = OPTIONS_SELLING_CONFIG['max_capital_risk_pct']
        sl_multiplier = OPTIONS_SELLING_CONFIG['sl_premium_multiplier']
        max_risk_amount = capital * (max_risk_pct / 100)

        # If premium doubles, loss = premium_received * lot_size * 1 (net loss = additional premium)
        loss_per_lot = premium * lot_size * (sl_multiplier - 1)
        if loss_per_lot <= 0:
            return 1, premium * lot_size, (premium * lot_size / capital) * 100

        lots = int(max_risk_amount / loss_per_lot)
        lots = max(1, lots)

        capital_at_risk = lots * loss_per_lot
        capital_at_risk_pct = (capital_at_risk / capital) * 100

        return lots, capital_at_risk, min(capital_at_risk_pct, max_risk_pct)

    def check_stop_loss_hit(self, trade: PaperTrade, current_price: float) -> bool:
        """Check if stop loss is hit."""
        if trade.trade_type == TradeType.OPTIONS_BUYING:
            # Bought option: price falls below SL
            return current_price <= trade.stop_loss
        else:
            # Sold option: price rises above SL
            return current_price >= trade.stop_loss

    def check_target_hit(self, trade: PaperTrade, current_price: float) -> Tuple[bool, int]:
        """Check if target is hit. Returns (hit, target_number)."""
        if trade.trade_type == TradeType.OPTIONS_BUYING:
            if current_price >= trade.target_2:
                return True, 2
            elif current_price >= trade.target_1:
                return True, 1
        else:
            # Sold option: profit when premium decays
            if current_price <= trade.target_2:
                return True, 2
            elif current_price <= trade.target_1:
                return True, 1
        return False, 0

    def should_squareoff(self) -> bool:
        """Check if forced square-off time reached."""
        now = datetime.now(IST)
        squareoff_time = now.replace(hour=15, minute=20, second=0, microsecond=0)
        return now >= squareoff_time

    def get_risk_summary(self, open_trades: List[PaperTrade]) -> dict:
        """Get current risk metrics."""
        self.reset_daily_stats()
        total_deployed = sum(t.capital_deployed for t in open_trades if t.status == TradeStatus.OPEN)
        unrealized_pnl = sum(t.unrealized_pnl for t in open_trades if t.status == TradeStatus.OPEN)

        return {
            "capital": self.capital,
            "daily_trades_used": self.daily_trades_count,
            "daily_trades_max": self.max_trades_per_day,
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_pnl_pct": round((self.daily_pnl / self.capital) * 100, 2),
            "daily_loss_limit_pct": self.max_daily_loss_pct,
            "total_capital_deployed": round(total_deployed, 2),
            "total_capital_deployed_pct": round((total_deployed / self.capital) * 100, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "max_capital_risk_pct": self.max_total_risk_pct,
            "real_trading_enabled": self.real_trading_enabled,
            "mode": "PAPER TRADING",
        }

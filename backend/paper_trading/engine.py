"""
Paper Trading Engine for TradePilot AI
Manages paper trades, tracks P&L, handles auto square-off.
All real-money execution is DISABLED.
"""
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional
import pytz

from models.trade import (
    PaperTrade, TradeSignal, TradeStatus, TradeType,
    OptionType, TradeDirection
)
from risk.risk_manager import RiskManager

logger = logging.getLogger("tradepilot.paper_trading")
IST = pytz.timezone("Asia/Kolkata")

TRADES_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "paper_trades.json")
JOURNAL_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "trade_journal.json")


class PaperTradingEngine:
    """
    Paper Trading Engine — simulates trade execution without real money.

    ⚠️  REAL MONEY EXECUTION IS PERMANENTLY DISABLED IN THIS VERSION.
         Do not connect to any broker API until fully tested and approved.
    """

    REAL_TRADING_ENABLED = False  # HARD LOCK

    def __init__(self, risk_manager: RiskManager):
        self.risk_manager = risk_manager
        self.open_trades: List[PaperTrade] = []
        self.closed_trades: List[PaperTrade] = []
        self.all_signals: List[Dict] = []
        self._load_state()

    # ----------------------------------------------------------------
    # State persistence
    # ----------------------------------------------------------------

    def _load_state(self):
        """Load saved paper trades from disk."""
        try:
            os.makedirs(os.path.dirname(TRADES_FILE), exist_ok=True)
            if os.path.exists(TRADES_FILE):
                with open(TRADES_FILE, 'r') as f:
                    data = json.load(f)
                    # Restore open trades
                    for td in data.get('open_trades', []):
                        trade = self._dict_to_trade(td)
                        if trade:
                            self.open_trades.append(trade)
                    for td in data.get('closed_trades', []):
                        trade = self._dict_to_trade(td)
                        if trade:
                            self.closed_trades.append(trade)
                logger.info(f"Loaded {len(self.open_trades)} open, {len(self.closed_trades)} closed trades")
        except Exception as e:
            logger.warning(f"Could not load state: {e}")

    def _save_state(self):
        """Persist current trades to disk."""
        try:
            os.makedirs(os.path.dirname(TRADES_FILE), exist_ok=True)
            data = {
                'saved_at': datetime.now(IST).isoformat(),
                'open_trades': [t.to_dict() for t in self.open_trades],
                'closed_trades': [t.to_dict() for t in self.closed_trades[-100:]],  # Keep last 100
            }
            with open(TRADES_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save state: {e}")

    def _dict_to_trade(self, d: dict) -> Optional[PaperTrade]:
        """Reconstruct PaperTrade from dict."""
        try:
            trade = PaperTrade()
            trade.trade_id = d.get('trade_id', '')
            trade.signal_id = d.get('signal_id', '')
            trade.symbol = d.get('symbol', '')
            trade.option_symbol = d.get('option_symbol', '')
            trade.entry_price = d.get('entry_price', 0)
            trade.current_price = d.get('current_price', d.get('entry_price', 0))
            trade.stop_loss = d.get('stop_loss', 0)
            trade.target_1 = d.get('target_1', 0)
            trade.target_2 = d.get('target_2', 0)
            trade.quantity = d.get('quantity', 1)
            trade.lot_size = d.get('lot_size', 1)
            trade.capital_deployed = d.get('capital_deployed', 0)
            trade.underlying_price_at_entry = d.get('underlying_price_at_entry', 0)

            tt = d.get('trade_type')
            trade.trade_type = TradeType[tt] if tt else None
            ot = d.get('option_type')
            trade.option_type = OptionType[ot] if ot and ot in ('CE', 'PE') else (
                OptionType.CALL if ot == 'CE' else OptionType.PUT if ot == 'PE' else None
            )
            # Handle both enum value and enum name
            try:
                trade.option_type = OptionType(ot) if ot else None
            except (ValueError, KeyError):
                pass

            dr = d.get('direction')
            trade.direction = TradeDirection[dr] if dr else None

            st = d.get('status', 'PENDING')
            trade.status = TradeStatus[st] if st else TradeStatus.PENDING

            if d.get('entry_time'):
                try:
                    trade.entry_time = datetime.fromisoformat(d['entry_time'])
                except:
                    trade.entry_time = None
            trade.exit_price = d.get('exit_price', 0)
            trade.exit_reason = d.get('exit_reason', '')
            trade.pnl = d.get('pnl', 0)
            trade.pnl_pct = d.get('pnl_pct', 0)
            return trade
        except Exception as e:
            logger.warning(f"Could not restore trade: {e}")
            return None

    # ----------------------------------------------------------------
    # Trade execution (paper only)
    # ----------------------------------------------------------------

    def execute_paper_trade(self, signal: TradeSignal) -> Optional[PaperTrade]:
        """
        Execute a paper trade based on validated signal.
        ⚠️  NO REAL MONEY INVOLVED — PAPER TRADING ONLY
        """
        if self.REAL_TRADING_ENABLED:
            raise RuntimeError("REAL TRADING IS NOT IMPLEMENTED. This is paper trading only.")

        if signal.is_no_trade or not signal.validation_passed:
            logger.info(f"Signal {signal.signal_id} not executed: validation failed")
            return None

        # Check if we can take trade
        allowed, reason = self.risk_manager.can_take_new_trade(self.open_trades)
        if not allowed:
            logger.info(f"Trade blocked: {reason}")
            return None

        # Create paper trade
        trade = PaperTrade()
        trade.signal_id = signal.signal_id
        trade.symbol = signal.symbol
        trade.option_symbol = signal.option_symbol
        trade.underlying_price_at_entry = signal.underlying_price
        trade.entry_price = signal.entry_price
        trade.current_price = signal.entry_price
        trade.stop_loss = signal.stop_loss
        trade.target_1 = signal.target_1
        trade.target_2 = signal.target_2
        trade.quantity = signal.position_size_lots
        trade.lot_size = signal.lot_size
        trade.trade_type = signal.trade_type
        trade.option_type = signal.option_type
        trade.direction = signal.direction
        trade.status = TradeStatus.OPEN
        trade.entry_time = datetime.now(IST)
        trade.capital_deployed = signal.entry_price * signal.lot_size * signal.position_size_lots
        trade.notes = f"Paper trade | Signal: {signal.signal_id} | Mode: PAPER TRADING"

        self.open_trades.append(trade)
        self.risk_manager.daily_trades_count += 1
        self._save_state()

        logger.info(
            f"📄 PAPER TRADE OPENED: {trade.trade_id} | "
            f"{trade.option_symbol} | Entry: ₹{trade.entry_price} | "
            f"Qty: {trade.quantity} lots"
        )
        return trade

    def update_trade_price(self, trade: PaperTrade, current_option_price: float):
        """Update current price and unrealized P&L for an open trade."""
        if trade.status != TradeStatus.OPEN:
            return

        trade.current_price = current_option_price
        price_diff = current_option_price - trade.entry_price
        if trade.trade_type == TradeType.OPTIONS_SELLING:
            # Selling: profit when price goes DOWN
            price_diff = trade.entry_price - current_option_price

        trade.unrealized_pnl = price_diff * trade.lot_size * trade.quantity

    def close_trade(self, trade: PaperTrade, exit_price: float, reason: str) -> float:
        """
        Close a paper trade and calculate realized P&L.
        Returns realized P&L.
        """
        if trade.status != TradeStatus.OPEN:
            return 0.0

        trade.exit_price = exit_price
        trade.exit_time = datetime.now(IST)
        trade.exit_reason = reason
        trade.status = TradeStatus.CLOSED

        price_diff = exit_price - trade.entry_price
        if trade.trade_type == TradeType.OPTIONS_SELLING:
            price_diff = trade.entry_price - exit_price  # Profit when premium falls

        trade.pnl = price_diff * trade.lot_size * trade.quantity
        trade.pnl_pct = (price_diff / trade.entry_price) * 100 if trade.entry_price > 0 else 0
        trade.unrealized_pnl = 0.0

        # Move to closed
        if trade in self.open_trades:
            self.open_trades.remove(trade)
        self.closed_trades.append(trade)

        self.risk_manager.update_daily_pnl(trade.pnl)
        self._save_state()

        pnl_emoji = "✅" if trade.pnl >= 0 else "❌"
        logger.info(
            f"{pnl_emoji} PAPER TRADE CLOSED: {trade.trade_id} | "
            f"{trade.option_symbol} | Exit: ₹{exit_price} | "
            f"P&L: ₹{trade.pnl:.2f} ({trade.pnl_pct:.1f}%) | "
            f"Reason: {reason}"
        )
        return trade.pnl

    def monitor_and_update(self, price_lookup: dict):
        """
        Check all open trades against current prices.
        Triggers SL/target exits as needed.
        
        Args:
            price_lookup: Dict of {option_symbol: current_price}
        """
        trades_to_close = []

        # Force squareoff check
        force_squareoff = self.risk_manager.should_squareoff()

        for trade in list(self.open_trades):
            current_price = price_lookup.get(trade.option_symbol)
            if current_price is None:
                # Estimate from underlying movement
                current_price = trade.current_price

            self.update_trade_price(trade, current_price)

            if force_squareoff:
                trades_to_close.append((trade, current_price, "FORCE SQUAREOFF — 15:20 IST"))
                continue

            # Check stop loss
            if self.risk_manager.check_stop_loss_hit(trade, current_price):
                trades_to_close.append((trade, current_price, "STOP LOSS HIT"))
                continue

            # Check targets
            target_hit, target_num = self.risk_manager.check_target_hit(trade, current_price)
            if target_hit:
                trades_to_close.append((trade, current_price, f"TARGET {target_num} HIT"))
                continue

        for trade, price, reason in trades_to_close:
            self.close_trade(trade, price, reason)

    # ----------------------------------------------------------------
    # Analytics
    # ----------------------------------------------------------------

    def get_portfolio_summary(self) -> dict:
        """Get current portfolio snapshot."""
        capital = self.risk_manager.capital
        open_count = len(self.open_trades)
        closed_count = len(self.closed_trades)

        # Today's closed trades
        today = datetime.now(IST).date()
        today_trades = [t for t in self.closed_trades if t.exit_time and t.exit_time.date() == today]
        today_pnl = sum(t.pnl for t in today_trades)
        total_pnl = sum(t.pnl for t in self.closed_trades)

        # Win rate
        winning = [t for t in self.closed_trades if t.pnl > 0]
        losing = [t for t in self.closed_trades if t.pnl <= 0]
        win_rate = (len(winning) / closed_count * 100) if closed_count > 0 else 0

        unrealized_pnl = sum(t.unrealized_pnl for t in self.open_trades)

        return {
            "mode": "PAPER TRADING",
            "real_trading_enabled": self.REAL_TRADING_ENABLED,
            "capital": capital,
            "available_capital": round(capital + total_pnl, 2),
            "open_trades": open_count,
            "closed_trades_total": closed_count,
            "today_trades": len(today_trades),
            "today_pnl": round(today_pnl, 2),
            "today_pnl_pct": round((today_pnl / capital) * 100, 2) if capital > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round((total_pnl / capital) * 100, 2) if capital > 0 else 0,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "win_rate_pct": round(win_rate, 1),
            "total_wins": len(winning),
            "total_losses": len(losing),
            "risk_summary": self.risk_manager.get_risk_summary(self.open_trades),
            "open_trades_detail": [t.to_dict() for t in self.open_trades],
            "recent_closed": [t.to_dict() for t in self.closed_trades[-10:]],
        }

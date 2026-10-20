"""
Unit tests for Risk Management Engine.
Enforces intraday F&O capital protection, position sizing, and loss limits.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from risk.risk_manager import RiskManager
from models.trade import PaperTrade, TradeStatus, TradeType


class TestRiskManager:
    def test_default_paper_capital(self):
        rm = RiskManager(capital=500000.0)
        assert rm.capital == 500000.0
        assert rm.real_trading_enabled is False

    def test_daily_loss_limit_breached(self):
        """If daily loss reaches 3%, new trades must be barred."""
        rm = RiskManager(capital=500000.0)
        # Breached by 3.5% loss = -₹17,500
        rm.daily_pnl = -18000.0
        allowed, reason = rm.can_take_new_trade([])
        assert allowed is False
        assert "loss limit" in reason.lower()

    def test_daily_trade_limit(self):
        """Max 4 trades per day."""
        rm = RiskManager(capital=500000.0)
        rm.daily_trades_count = 4
        allowed, reason = rm.can_take_new_trade([])
        assert allowed is False
        assert "limit reached" in reason.lower()

    def test_buying_position_sizing(self):
        """Risk per trade capped at 2% of capital (₹10,000 max risk)."""
        rm = RiskManager(capital=500000.0)
        # NIFTY lot size 25, premium 200, 35% SL = loss 70 per qty = 1750 per lot
        # Max risk ₹10,000 / ₹1,750 = 5 lots
        lots, at_risk, risk_pct = rm.calculate_buying_position_size(
            capital=500000.0,
            premium=200.0,
            lot_size=25,
            sl_pct=35.0
        )
        assert lots == 5
        assert at_risk == 5 * (200.0 * 25 * 0.35)
        assert risk_pct <= 2.0

    def test_stop_loss_hit_detection(self):
        rm = RiskManager()
        trade = PaperTrade(
            trade_type=TradeType.OPTIONS_BUYING,
            entry_price=200.0,
            stop_loss=130.0,
            target_1=400.0,
            target_2=600.0,
        )
        assert rm.check_stop_loss_hit(trade, 130.0) is True
        assert rm.check_stop_loss_hit(trade, 125.0) is True
        assert rm.check_stop_loss_hit(trade, 150.0) is False

    def test_target_hit_detection(self):
        rm = RiskManager()
        trade = PaperTrade(
            trade_type=TradeType.OPTIONS_BUYING,
            entry_price=200.0,
            stop_loss=130.0,
            target_1=400.0,
            target_2=600.0,
        )
        hit, t_num = rm.check_target_hit(trade, 405.0)
        assert hit is True
        assert t_num == 1

        hit2, t2_num = rm.check_target_hit(trade, 610.0)
        assert hit2 is True
        assert t2_num == 2

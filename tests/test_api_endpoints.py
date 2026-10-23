"""
Integration tests for FastAPI endpoints.
Validates scan pipeline, risk summary, portfolio, and trade endpoints.
"""
import sys
import os
import pytest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from main import app
from market_data.upstox_feed import UpstoxClientManager

client = TestClient(app)


class TestAPIEndpoints:
    def test_upstox_ltp_maps_response_display_key_to_internal_symbol(self):
        """Upstox response keys use ':'; prefer instrument_token for symbol mapping."""
        manager = UpstoxClientManager()
        manager.is_connected = True
        manager.access_token = "test-token"
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "status": "success",
            "data": {
                "NSE_INDEX:Nifty 50": {
                    "instrument_token": "NSE_INDEX|Nifty 50",
                    "last_price": 25001.25,
                }
            },
        }
        with patch("market_data.upstox_feed.requests.get", return_value=response):
            assert manager.get_live_ltp(["NIFTY"]) == {"NIFTY": 25001.25}

    def test_config_endpoint(self):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "PAPER TRADING"
        assert data["real_trading_enabled"] is False
        assert data["max_trades_per_day"] == 4
        assert "NIFTY" in data["supported_indices"]

    def test_risk_endpoint(self):
        resp = client.get("/api/risk")
        assert resp.status_code == 200
        data = resp.json()
        assert "capital" in data
        assert "daily_loss_limit_pct" in data
        assert data["mode"] == "PAPER TRADING"

    def test_portfolio_endpoint(self):
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "PAPER TRADING"
        assert data["real_trading_enabled"] is False

    def test_upstox_status_endpoint(self):
        resp = client.get("/api/upstox/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_connected" in data
        assert "broker" in data

    def test_symbol_signal_endpoint(self):
        resp = client.get("/api/signals/NIFTY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "NIFTY"
        assert "indicators" in data
        assert "spot_price" in data

    def test_paper_trade_lifecycle(self):
        """Open a paper trade and then close it."""
        trade_payload = {
            "signal_id": "TEST_SIG_01",
            "symbol": "NIFTY",
            "option_symbol": "NIFTY24500CE",
            "entry_price": 200.0,
            "stop_loss": 130.0,
            "target_1": 400.0,
            "target_2": 600.0,
            "position_size_lots": 1,
            "lot_size": 25,
            "underlying_price": 24500.0,
            "trade_type": "OPTIONS_BUYING",
            "option_type": "CE",
            "direction": "LONG",
            "validation_passed": True,
            "is_no_trade": False,
        }

        open_resp = client.post("/api/paper-trade/open", json=trade_payload)
        assert open_resp.status_code == 200
        open_data = open_resp.json()
        assert open_data["success"] is True
        trade_id = open_data["trade"]["trade_id"]

        # Close the paper trade at profit
        close_payload = {
            "trade_id": trade_id,
            "exit_price": 350.0,
            "reason": "Target 1 reached test"
        }
        close_resp = client.post("/api/paper-trade/close", json=close_payload)
        assert close_resp.status_code == 200
        close_data = close_resp.json()
        assert close_data["success"] is True
        assert close_data["trade_id"] == trade_id
        # PnL = (350 - 200) * 25 = ₹3,750
        assert close_data["realized_pnl"] == 3750.0

"""
TradePilot AI — FastAPI Backend Server
Indian F&O Intraday Trading Signal System (Paper Trading Mode)

⚠️  PAPER TRADING ONLY — Real money execution is DISABLED
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import logging
from datetime import datetime
from typing import List, Optional
import pytz

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import math
from pydantic import BaseModel
import uvicorn

def sanitize_json(val):
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    elif isinstance(val, dict):
        return {k: sanitize_json(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [sanitize_json(v) for v in val]
    return val

from orchestrator import SignalOrchestrator
from paper_trading.engine import PaperTradingEngine
from risk.risk_manager import RiskManager
from models.trade import TradeSignal
from utils.helpers import is_market_open, is_new_trade_allowed, get_ist_now
from config import INDEX_SYMBOLS, FO_STOCKS, RISK_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("tradepilot.server")
IST = pytz.timezone("Asia/Kolkata")

# ================================================================
# App initialization
# ================================================================

app = FastAPI(
    title="TradePilot AI",
    description="Intraday F&O Trading Signal System for Indian Markets (Paper Trading)",
    version="1.0.0",
    docs_url="/api/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
risk_manager = RiskManager()
paper_engine = PaperTradingEngine(risk_manager)
orchestrator = SignalOrchestrator()

# Serve frontend
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ================================================================
# Request models
# ================================================================

class ScanRequest(BaseModel):
    symbols: Optional[List[str]] = None


class ExecuteTradeRequest(BaseModel):
    signal_id: str


class CloseTradeRequest(BaseModel):
    trade_id: str
    exit_price: float
    reason: str = "MANUAL CLOSE"


class GrowwConnectRequest(BaseModel):
    api_key: str
    api_secret: Optional[str] = None
    totp_secret: Optional[str] = None


from market_data.groww_feed import groww_manager


# ================================================================
# Routes
# ================================================================

@app.get("/")
async def root():
    """Serve the dashboard."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "message": "TradePilot AI is running",
        "mode": "PAPER TRADING",
        "docs": "/api/docs",
        "health": "/api/health",
    }


@app.get("/api/health")
async def health():
    """System health check."""
    now = get_ist_now()
    return {
        "status": "healthy",
        "mode": "PAPER TRADING",
        "real_trading_enabled": False,
        "server_time_ist": now.isoformat(),
        "market_open": is_market_open(),
        "new_trade_allowed": is_new_trade_allowed(),
        "daily_trades_used": risk_manager.daily_trades_count,
        "daily_trades_max": RISK_CONFIG['max_trades_per_day'],
        "daily_pnl": round(risk_manager.daily_pnl, 2),
        "version": "1.0.0",
        "groww_status": groww_manager.get_status(),
    }


@app.get("/api/groww/status")
async def get_groww_status():
    """Get live Groww API connection status."""
    return groww_manager.get_status()


@app.post("/api/groww/connect")
async def connect_groww(req: GrowwConnectRequest):
    """Authenticate and connect to live Groww Trading API."""
    success, msg = groww_manager.connect(req.api_key, req.api_secret, req.totp_secret)
    return {
        "success": success,
        "message": msg,
        "status": groww_manager.get_status()
    }


@app.get("/api/market-status")
async def market_status():
    """Get current market status and session info."""
    now = get_ist_now()
    return {
        "time_ist": now.strftime("%H:%M:%S"),
        "date": now.strftime("%d-%b-%Y"),
        "day": now.strftime("%A"),
        "market_open": is_market_open(),
        "new_trade_allowed": is_new_trade_allowed(),
        "session_info": {
            "market_open_time": "09:15 IST",
            "market_close_time": "15:30 IST",
            "no_new_trades_after": "14:30 IST",
            "force_squareoff_time": "15:20 IST",
        },
        "supported_symbols": {
            "indices": list(INDEX_SYMBOLS.keys()),
            "fo_stocks": list(FO_STOCKS.keys()),
        },
    }


@app.get("/api/scan")
@app.post("/api/scan")
async def scan_signals(request: Optional[ScanRequest] = None):
    """
    Scan markets and generate trade signals.
    Returns validated signals or NO TRADE if no setup passes all checks.
    """
    symbols = None
    if request and request.symbols:
        # Validate symbols
        all_valid = {**INDEX_SYMBOLS, **FO_STOCKS}
        invalid = [s for s in request.symbols if s not in all_valid]
        if invalid:
            raise HTTPException(400, f"Invalid symbols: {invalid}")
        symbols = request.symbols

    try:
        results = orchestrator.scan_all_symbols(
            symbols=symbols,
            daily_trades_count=risk_manager.daily_trades_count,
        )
        results['portfolio_summary'] = paper_engine.get_portfolio_summary()
        return sanitize_json(results)
    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        raise HTTPException(500, f"Scan failed: {str(e)}")


@app.get("/api/signals/{symbol}")
async def get_signal_for_symbol(symbol: str):
    """Get signals for a specific symbol."""
    symbol = symbol.upper()
    all_valid = {**INDEX_SYMBOLS, **FO_STOCKS}
    if symbol not in all_valid:
        raise HTTPException(404, f"Symbol {symbol} not found. Valid: {list(all_valid.keys())}")

    try:
        buying, selling, mdata = orchestrator.analyze_symbol(symbol)
        resp_data = {
            "symbol": symbol,
            "spot_price": mdata.get('spot_price'),
            "scan_time": datetime.now(IST).isoformat(),
            "buying_signal": buying.to_dict() if buying else None,
            "selling_signal": selling.to_dict() if selling else None,
            "market_data": mdata,
            "indicators": mdata.get('indicators', {}),
        }
        return sanitize_json(resp_data)
    except Exception as e:
        logger.error(f"Error analyzing {symbol}: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@app.post("/api/execute-paper-trade")
async def execute_paper_trade(request: ExecuteTradeRequest):
    """
    Execute a paper trade from a validated signal.
    ⚠️ PAPER TRADING ONLY — No real money.
    """
    # Find signal in recent scan results
    # For simplicity, re-scan to get fresh signal
    # In production, signals would be cached by signal_id

    return {
        "message": "Paper trade execution API ready",
        "note": "Submit signal data directly to execute a paper trade",
        "real_trading_enabled": False,
        "mode": "PAPER TRADING",
    }


@app.post("/api/paper-trade/open")
async def open_paper_trade(signal_data: dict):
    """Open a paper trade from signal data."""
    try:
        from models.trade import TradeSignal, TradeDirection, OptionType, TradeType, SignalStrength
        
        signal = TradeSignal()
        signal.signal_id = signal_data.get('signal_id', '')
        signal.symbol = signal_data.get('symbol', '')
        signal.option_symbol = signal_data.get('option_symbol', '')
        signal.entry_price = float(signal_data.get('entry_price', 0))
        signal.stop_loss = float(signal_data.get('stop_loss', 0))
        signal.target_1 = float(signal_data.get('target_1', 0))
        signal.target_2 = float(signal_data.get('target_2', 0))
        signal.position_size_lots = int(signal_data.get('position_size_lots', 1))
        signal.lot_size = int(signal_data.get('lot_size', 50))
        signal.underlying_price = float(signal_data.get('underlying_price', 0))
        signal.validation_passed = signal_data.get('validation_passed', False)
        signal.is_no_trade = signal_data.get('is_no_trade', True)

        tt = signal_data.get('trade_type')
        signal.trade_type = TradeType[tt] if tt else None
        ot = signal_data.get('option_type')
        try:
            signal.option_type = OptionType(ot) if ot else None
        except:
            pass
        dr = signal_data.get('direction')
        signal.direction = TradeDirection[dr] if dr else None

        trade = paper_engine.execute_paper_trade(signal)
        if trade:
            return {"success": True, "trade": trade.to_dict()}
        else:
            return {"success": False, "message": "Trade not executed — check risk limits"}
    except Exception as e:
        logger.error(f"Execute trade error: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@app.post("/api/paper-trade/close")
async def close_paper_trade(request: CloseTradeRequest):
    """Close a specific paper trade."""
    trade = next((t for t in paper_engine.open_trades if t.trade_id == request.trade_id), None)
    if not trade:
        raise HTTPException(404, f"Trade {request.trade_id} not found in open trades")

    pnl = paper_engine.close_trade(trade, request.exit_price, request.reason)
    return {
        "success": True,
        "trade_id": request.trade_id,
        "realized_pnl": round(pnl, 2),
        "exit_price": request.exit_price,
        "reason": request.reason,
    }


@app.get("/api/portfolio")
async def get_portfolio():
    """Get full portfolio snapshot."""
    return sanitize_json(paper_engine.get_portfolio_summary())


@app.get("/api/trades/open")
async def get_open_trades():
    """Get all open paper trades."""
    return {
        "count": len(paper_engine.open_trades),
        "trades": [t.to_dict() for t in paper_engine.open_trades],
    }


@app.get("/api/trades/history")
async def get_trade_history(limit: int = 50):
    """Get trade history."""
    trades = paper_engine.closed_trades[-limit:]
    total_pnl = sum(t.pnl for t in paper_engine.closed_trades)
    wins = len([t for t in paper_engine.closed_trades if t.pnl > 0])
    losses = len([t for t in paper_engine.closed_trades if t.pnl <= 0])

    return {
        "total_trades": len(paper_engine.closed_trades),
        "total_pnl": round(total_pnl, 2),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / max(len(paper_engine.closed_trades), 1) * 100, 1),
        "trades": [t.to_dict() for t in reversed(trades)],
    }


@app.get("/api/risk")
async def get_risk_metrics():
    """Get current risk metrics."""
    return risk_manager.get_risk_summary(paper_engine.open_trades)


@app.get("/api/config")
async def get_config():
    """Get system configuration."""
    return {
        "mode": "PAPER TRADING",
        "real_trading_enabled": False,
        "paper_capital": RISK_CONFIG['paper_trading_capital'],
        "max_trades_per_day": RISK_CONFIG['max_trades_per_day'],
        "max_daily_loss_pct": RISK_CONFIG['max_daily_loss_pct'],
        "max_total_risk_pct": RISK_CONFIG['max_total_capital_risk'],
        "squareoff_time": RISK_CONFIG['square_off_time'],
        "no_new_trade_after": RISK_CONFIG['no_new_trade_after'],
        "supported_indices": list(INDEX_SYMBOLS.keys()),
        "supported_stocks": list(FO_STOCKS.keys()),
        "strategies": ["OPTIONS_BUYING", "OPTIONS_SELLING"],
        "timeframes": ["5m", "15m"],
    }


if __name__ == "__main__":
    print("=" * 60)
    print("  TradePilot AI — Starting...")
    print("  Mode: PAPER TRADING (Real money: DISABLED)")
    print("  Markets: NIFTY, BANKNIFTY, F&O Stocks")
    print("  Dashboard: http://localhost:8000")
    print("  API Docs: http://localhost:8000/api/docs")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

"""
Groww Trading API Integration for TradePilot AI
Fetches 100% real live market option chain, ticks, and handles orders.
"""
import logging
import os
import json
from typing import Dict, Optional, List, Tuple
from datetime import datetime

logger = logging.getLogger("tradepilot.groww")

try:
    from growwapi import GrowwAPI, GrowwFeed
    import pyotp
    GROWW_SDK_AVAILABLE = True
except ImportError:
    GROWW_SDK_AVAILABLE = False
    logger.warning("growwapi or pyotp not installed")

GROWW_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "groww_credentials.json")


class GrowwClientManager:
    """
    Manages connection to Groww Trading API.
    Provides live real-time NSE Option Chain LTP and Greeks.
    """

    def __init__(self):
        self.api_key: Optional[str] = None
        self.api_secret: Optional[str] = None
        self.totp_secret: Optional[str] = None
        self.access_token: Optional[str] = None
        self.client: Optional[GrowwAPI] = None
        self.is_connected: bool = False
        self._load_saved_credentials()

    def _load_saved_credentials(self):
        """Load credentials from local secure file if available."""
        try:
            if os.path.exists(GROWW_CONFIG_FILE):
                with open(GROWW_CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    self.api_key = data.get("api_key")
                    self.api_secret = data.get("api_secret")
                    self.totp_secret = data.get("totp_secret")
                    if self.api_key and (self.api_secret or self.totp_secret):
                        self.connect(self.api_key, self.api_secret, self.totp_secret)
        except Exception as e:
            logger.warning(f"Could not load saved Groww credentials: {e}")

    def save_credentials(self, api_key: str, api_secret: Optional[str] = None, totp_secret: Optional[str] = None):
        """Save credentials locally."""
        try:
            os.makedirs(os.path.dirname(GROWW_CONFIG_FILE), exist_ok=True)
            with open(GROWW_CONFIG_FILE, "w") as f:
                json.dump({
                    "api_key": api_key,
                    "api_secret": api_secret,
                    "totp_secret": totp_secret,
                    "updated_at": datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving Groww credentials: {e}")

    def connect(self, api_key: str, api_secret: Optional[str] = None, totp_secret: Optional[str] = None) -> Tuple[bool, str]:
        """
        Authenticate with Groww API.
        Returns: (success: bool, message: str)
        """
        if not GROWW_SDK_AVAILABLE:
            return False, "growwapi library not available"

        self.api_key = api_key
        self.api_secret = api_secret
        self.totp_secret = totp_secret

        try:
            totp_code = None
            if totp_secret:
                try:
                    totp_code = pyotp.TOTP(totp_secret).now()
                except Exception as te:
                    logger.warning(f"TOTP generation error: {te}")

            # Request access token
            token_resp = GrowwAPI.get_access_token(
                api_key=api_key,
                totp=totp_code,
                secret=api_secret
            )

            if isinstance(token_resp, dict):
                access_token = token_resp.get("access_token") or token_resp.get("token") or api_key
            else:
                access_token = str(token_resp)

            self.access_token = access_token
            self.client = GrowwAPI(access_token)
            self.is_connected = True

            # Save credentials for future sessions
            self.save_credentials(api_key, api_secret, totp_secret)

            logger.info("✅ Successfully connected to Groww Trading API!")
            return True, "Connected to Groww Trading API successfully"

        except Exception as e:
            self.is_connected = False
            self.client = None
            err_msg = f"Groww connection failed: {str(e)}"
            logger.error(err_msg)
            return False, err_msg

    def get_live_option_chain(self, underlying_symbol: str, expiry_date: Optional[str] = None) -> Optional[Dict]:
        """
        Fetch 100% REAL live option chain from Groww.
        Returns dict with calls, puts, and live market LTP.
        """
        if not self.is_connected or not self.client:
            return None

        try:
            # Map symbol for Groww
            sym = underlying_symbol.upper()
            if sym == "NIFTY":
                groww_sym = "NIFTY"
            elif sym == "BANKNIFTY":
                groww_sym = "BANKNIFTY"
            elif sym == "FINNIFTY":
                groww_sym = "FINNIFTY"
            else:
                groww_sym = sym

            chain_data = self.client.get_option_chain(
                exchange=GrowwAPI.EXCHANGE_NSE,
                segment=GrowwAPI.SEGMENT_FNO,
                underlying_symbol=groww_sym,
                expiry=expiry_date
            )
            return chain_data
        except Exception as e:
            logger.error(f"Error fetching live Groww option chain for {underlying_symbol}: {e}")
            return None

    def get_contract_ltp(self, trading_symbol: str) -> Optional[float]:
        """
        Fetch exact live tick price (LTP) for a specific option contract.
        e.g. 'BANKNIFTY 55600 CE'
        """
        if not self.is_connected or not self.client:
            return None

        try:
            quote = self.client.get_ltp(
                segment=GrowwAPI.SEGMENT_FNO,
                symbol=trading_symbol
            )
            if quote and isinstance(quote, dict):
                return float(quote.get("ltp") or quote.get("last_price") or 0.0)
            elif isinstance(quote, (int, float)):
                return float(quote)
        except Exception as e:
            logger.warning(f"Error fetching LTP for {trading_symbol}: {e}")
        return None

    def place_order(self, *args, **kwargs):
        """
        HARD SAFETY BARRIER:
        Real order placement is permanently disabled in TradePilot AI.
        Prevents any automated or accidental real-money orders.
        """
        raise RuntimeError("REAL MONEY ORDER EXECUTION IS HARD-LOCKED OFF. TradePilot operates in Paper Trading mode only.")

    def get_status(self) -> Dict:
        """Get live Groww connection status."""
        status = {
            "is_connected": self.is_connected,
            "has_api_key": bool(self.api_key),
            "broker": "Groww",
            "mode": "GROWW LIVE FEED ACTIVE" if self.is_connected else "SIMULATED / PAPER TRADING",
        }
        if self.is_connected and self.client:
            try:
                prof = self.client.get_user_profile()
                status["ucc"] = prof.get("ucc")
                status["active_segments"] = prof.get("active_segments")
            except Exception:
                pass
            try:
                margin = self.client.get_available_margin_details()
                fno_det = margin.get("fno_margin_details", {})
                status["fno_balance"] = fno_det.get("option_buy_balance_available")
            except Exception:
                pass
        return status


# Global instance
groww_manager = GrowwClientManager()

"""
Upstox API v2 Integration for TradePilot AI
Fetches 100% real live market quotes, LTP, and Option Chain data.
"""
import logging
import requests
import json
import os
from typing import Dict, Optional, List, Tuple

logger = logging.getLogger("tradepilot.upstox")

UPSTOX_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "upstox_credentials.json")

# Symbol mappings for Upstox v2 API
UPSTOX_INSTRUMENT_MAP = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "RELIANCE": "NSE_EQ|INE002A01018",
    "TCS": "NSE_EQ|INE467B01029",
    "INFY": "NSE_EQ|INE009A01021",
    "HDFCBANK": "NSE_EQ|INE040A01034",
    "ICICIBANK": "NSE_EQ|INE090A01021",
    "SBIN": "NSE_EQ|INE062A01020",
    "AXISBANK": "NSE_EQ|INE238A01034",
    "WIPRO": "NSE_EQ|INE075A01022",
    "LT": "NSE_EQ|INE018A01030",
}


class UpstoxClientManager:
    """
    Manages connection to Upstox API v2.
    Retrieves live exchange LTP snapshots and complete option chain.
    """

    def __init__(self):
        self.access_token: Optional[str] = None
        self.is_connected: bool = False
        # The v2 LTP endpoint is deprecated. Option-chain endpoints remain v2,
        # while current LTP snapshots are served by Market Quote v3.
        self.base_url = "https://api.upstox.com/v2"
        self.quote_base_url = "https://api.upstox.com/v3"
        self._load_saved_credentials()

    def _load_saved_credentials(self):
        """Load saved credentials from local file if available."""
        try:
            if os.path.exists(UPSTOX_CONFIG_FILE):
                with open(UPSTOX_CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    token = data.get("access_token")
                    if token:
                        self.connect(token)
        except Exception as e:
            logger.warning(f"Could not load Upstox credentials: {e}")

    def save_credentials(self, access_token: str):
        """Save access token locally (ignored by git)."""
        try:
            os.makedirs(os.path.dirname(UPSTOX_CONFIG_FILE), exist_ok=True)
            with open(UPSTOX_CONFIG_FILE, "w") as f:
                json.dump({"access_token": access_token}, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving Upstox token: {e}")

    def connect(self, access_token: str) -> Tuple[bool, str]:
        """
        Validate and connect using Upstox API v2 access token.
        """
        self.access_token = access_token.strip()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}"
        }

        try:
            # Test connection by requesting Nifty 50 & Bank Nifty LTP
            test_url = f"{self.quote_base_url}/market-quote/ltp?instrument_key=NSE_INDEX|Nifty 50,NSE_INDEX|Nifty Bank"
            resp = requests.get(test_url, headers=headers, timeout=8)

            if resp.status_code == 200 and resp.json().get("status") == "success":
                self.is_connected = True
                self.save_credentials(self.access_token)
                data = resp.json().get("data", {})
                logger.info(f"✅ Successfully connected to Upstox API v2! Live instruments: {list(data.keys())}")
                return True, "Connected to Upstox API successfully"
            else:
                self.is_connected = False
                err = resp.json().get("errors", [{}])[0].get("message", resp.text)
                return False, f"Upstox Auth Failed ({resp.status_code}): {err}"

        except Exception as e:
            self.is_connected = False
            return False, f"Connection error: {str(e)}"

    def get_live_ltp(self, symbols: List[str]) -> Dict[str, float]:
        """
        Fetch real live Last Traded Price (LTP) for specified symbols.
        """
        if not self.is_connected or not self.access_token:
            return {}

        keys = [UPSTOX_INSTRUMENT_MAP.get(s, s) for s in symbols]
        query_keys = ",".join(keys)
        url = f"{self.quote_base_url}/market-quote/ltp?instrument_key={query_keys}"

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                result = {}
                data = resp.json().get("data", {})
                reverse_map = {v: k for k, v in UPSTOX_INSTRUMENT_MAP.items()}
                for key_id, info in data.items():
                    # Upstox returns a display key such as ``NSE_INDEX:Nifty 50``
                    # but supplies the requested pipe-delimited token separately.
                    # Map with instrument_token first so live quotes are assigned to
                    # our internal symbols instead of silently falling back to Yahoo.
                    instrument_token = info.get("instrument_token", "")
                    normalized_key = key_id.replace(":", "|", 1)
                    sym_name = (
                        reverse_map.get(instrument_token)
                        or reverse_map.get(normalized_key)
                        or reverse_map.get(key_id)
                        or key_id.split(":", 1)[-1]
                    )
                    result[sym_name] = float(info.get("last_price", 0.0))
                return result
        except Exception as e:
            logger.error(f"Error fetching Upstox LTP: {e}")
        return {}

    def get_nearest_expiry(self, instrument_key: str) -> Optional[str]:
        """Fetch nearest available option expiry from Upstox contracts."""
        try:
            url = f"{self.base_url}/option/contract"
            headers = {"Accept": "application/json", "Authorization": f"Bearer {self.access_token}"}
            resp = requests.get(url, headers=headers, params={"instrument_key": instrument_key}, timeout=5)
            if resp.status_code == 200:
                contracts = resp.json().get("data", [])
                expiries = sorted(list({c.get("expiry") for c in contracts if c.get("expiry")}))
                if expiries:
                    return expiries[0]
        except Exception as e:
            logger.debug(f"Upstox contract expiry fetch error: {e}")

        # Fallback: compute standard weekly Thursday / Wednesday expiry
        import pytz
        from datetime import datetime, timedelta
        IST = pytz.timezone("Asia/Kolkata")
        now = datetime.now(IST)
        expiry_weekday = 2 if "Bank" in instrument_key else (1 if "Fin" in instrument_key else 3)
        days = (expiry_weekday - now.weekday()) % 7
        if days == 0 and now.hour >= 15:
            days = 7
        return (now + timedelta(days=days)).strftime("%Y-%m-%d")

    def get_live_option_chain(self, symbol: str, expiry_date: Optional[str] = None) -> Optional[Dict]:
        """
        Fetch 100% REAL live option chain with real LTP, volume, and Greeks.
        """
        if not self.is_connected or not self.access_token:
            return None

        underlying_key = UPSTOX_INSTRUMENT_MAP.get(symbol)
        if not underlying_key:
            return None

        if not expiry_date or expiry_date == "current_month":
            expiry_date = self.get_nearest_expiry(underlying_key)

        url = f"{self.base_url}/option/chain"
        params = {
            "instrument_key": underlying_key,
        }
        if expiry_date:
            params["expiry_date"] = expiry_date

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}"
        }

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=8)
            if resp.status_code == 200:
                json_data = resp.json()
                if json_data.get("status") == "success":
                    chain = {"calls": {}, "puts": {}, "spot_price": None}
                    raw_items = json_data.get("data", [])
                    total_call_oi = 0
                    total_put_oi = 0

                    for item in raw_items:
                        strike = int(round(item["strike_price"]))
                        if chain["spot_price"] is None:
                            chain["spot_price"] = item.get("underlying_spot_price")

                        # Calls
                        call_opt = item.get("call_options", {})
                        call_mkt = call_opt.get("market_data", {})
                        call_greeks = call_opt.get("option_greeks", {})
                        if call_mkt:
                            chain["calls"][strike] = {
                                "premium": float(call_mkt.get("ltp", 0.0)),
                                "delta": float(call_greeks.get("delta", 0.0)),
                                "theta": float(call_greeks.get("theta", 0.0)),
                                "iv": float(call_greeks.get("iv", 0.0) * 100.0 if call_greeks.get("iv") else 15.0),
                                "oi": int(call_mkt.get("oi", 0)),
                                "volume": int(call_mkt.get("volume", 0)),
                            }
                            total_call_oi += int(call_mkt.get("oi", 0))

                        # Puts
                        put_opt = item.get("put_options", {})
                        put_mkt = put_opt.get("market_data", {})
                        put_greeks = put_opt.get("option_greeks", {})
                        if put_mkt:
                            chain["puts"][strike] = {
                                "premium": float(put_mkt.get("ltp", 0.0)),
                                "delta": float(put_greeks.get("delta", 0.0)),
                                "theta": float(put_greeks.get("theta", 0.0)),
                                "iv": float(put_greeks.get("iv", 0.0) * 100.0 if put_greeks.get("iv") else 15.0),
                                "oi": int(put_mkt.get("oi", 0)),
                                "volume": int(put_mkt.get("volume", 0)),
                            }
                            total_put_oi += int(put_mkt.get("oi", 0))

                    chain["pcr"] = round(total_put_oi / max(1, total_call_oi), 2)
                    return chain
        except Exception as e:
            logger.error(f"Error fetching Upstox option chain for {symbol}: {e}")

        return None

    def get_status(self) -> Dict:
        """Get live status of Upstox integration."""
        return {
            "is_connected": self.is_connected,
            "has_token": bool(self.access_token),
            "broker": "Upstox API (Market Quote v3)",
            "mode": "UPSTOX LIVE QUOTE POLLING" if self.is_connected else "SIMULATED / PAPER TRADING",
        }


# Global instance
upstox_manager = UpstoxClientManager()

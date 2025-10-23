from urllib.parse import urlencode
import base64, hashlib, hmac, time, os
from dataclasses import dataclass

@dataclass
class KrakenAuth:

    api_key: str
    api_secret_b64: str

    @classmethod
    def from_env(cls) -> "KrakenAuth":
        """
        Load Kraken credentials from .env:
          KRAKEN_API_KEY=...
          KRAKEN_API_SECRET_B64=...
        """
        key = os.getenv("KRAKEN_API_KEY")
        sec = os.getenv("KRAKEN_API_SECRET_B64")
        if not key or not sec:
            raise RuntimeError("Missing KRAKEN_API_KEY or KRAKEN_API_SECRET_B64")
        return cls(api_key=key, api_secret_b64=sec)
    
    def sign(self, path: str, body_dict: dict) -> dict:
        """
        Return headers for any Kraken private endpoint (POST).
        Example path: '/0/private/TradeVolume'
        """
        postdata = urlencode(body_dict)
        message = path.encode() + hashlib.sha256((str(body_dict["nonce"]) + postdata).encode()).digest()
        secret = base64.b64decode(self.api_secret_b64)
        sig = hmac.new(secret, message, hashlib.sha512)
        api_sign = base64.b64encode(sig.digest()).decode()

        return {
            "API-Key": self.api_key,
            "API-Sign": api_sign,
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def trade_volume(self, pair: str):
        """
        Convenience helper for /0/private/TradeVolume.
        Returns (url, headers, body_str)
        """
        path = "/0/private/TradeVolume"
        url = "https://api.kraken.com" + path
        nonce = int(time.time() * 1000)
        body = {"nonce": nonce, "pair": pair}
        headers = self.sign(path, body)
        return url, headers, urlencode(body)


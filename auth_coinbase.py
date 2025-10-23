"""
Coinbase Advanced Trade (v3) API request signer (ECDSA).

Usage:
    from auth_coinbase import CoinbaseAdvAuth
    auth = CoinbaseAdvAuth(api_key_id=..., private_key_pem=...)
    headers = auth.sign(method="GET", path="/api/v3/brokerage/transaction_summary")
    # then: await session.get("https://api.coinbase.com/api/v3/brokerage/transaction_summary", headers=headers)

Notes:
- method: "GET", "POST", ...
- path: must be EXACTLY what you’ll request (no host, no query normalization added by you later).
- body: pass the raw string you'll send on the wire ("" for GET), or use json.dumps with separators=(",",":").
"""

from __future__ import annotations
import os
import time
import json
import hashlib
import base64
from dataclasses import dataclass
from typing import Optional

from ecdsa import SigningKey, NIST256p

COINBASE_API_HOST = "https://api.coinbase.com"

def _json_compact(obj) -> str:
    """Deterministic JSON String (no spaces) so the signed body matches what is sent. """
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

@dataclass
class CoinbaseAdvAuth:
    api_key_id: Optional[str] = None
    private_key_pem: Optional[str] = None

    @classmethod
    def from_env(cls) -> "CoinbaseAdvAuth":
        """
        Load from environment:
          CB_ADV_API_KEY=organizations/.../apiKeys/<id>
          CB_ADV_PRIVATE_KEY=<PEM with \n escaped>   
        """
        key_id = os.getenv("CB_ADV_API_KEY")
        pem = os.getenv("CB_ADV_PRIVATE_KEY")
        pem = pem.replace("\\n", "\n") #allow \n-escaped
        return cls(api_key_id=key_id, private_key_pem=pem)
    
    def _require(self):
        if not self.api_key_id or not self.private_key_pem:
            raise RuntimeError("Coinbase Advanced auth missing api_key_id or private_key_pem")
    
    def sign(self, method: str, path: str, body: str = "") -> dict:
        """
        Build Coinbase Advanced headers for a request.
        - method: "GET"/"POST"/...
        - path: e.g. "/api/v3/brokerage/transaction_summary" (MUST match the actual request)
        - body: EXACT raw string to be sent ("" for GET). If you're sending JSON, pass json.dumps(..., separators=(',', ':'))
        Returns headers dict 
        """
        self._require()
        ts = str(int(time.time())) #timestamp in seconds (as string)
        prehash = ts + method.upper() + path + (body or "")

        # Load EC private key and sign SHA-256(prehash)
        # Coinbase Advanced provides PEM like
        #"-----BEGIN EC PRIVATE KEY-----"
        sk = SigningKey.from_pem(self.private_key_pem)
        signature = sk.sign(prehash.encode("utf-8"), hashfunc=hashlib.sha256)
        sig_b64 = base64.b64encode(signature).decode("ascii")

        headers = {
            "CB-ACCESS-KEY": self.api_key_id,
            "CB-ACCESS-SIGN": sig_b64,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
            #optional: 
            #"User-Agent": "crypto-arbitrage/fee-fetcher"
        }
        return headers
    
    def sign_json(self, method: str, path: str, obj) -> tuple[dict, str]:
        """
        sign a JSON body and return (headers, body_str).
        Use this so the signed string is exactly what you send.
        """
        body_str = _json_compact(obj) if obj is not None else ""
        return self.sign(method, path, body_str), body_str

    def api_url(self, path: str) -> str:
        if not path.startswith('/'):
            raise ValueError("path must start wtih '/'")
        return COINBASE_API_HOST + path        


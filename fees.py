"""
fees.py
Unified fee retriever for:
  - Kraken (private /0/private/TradeVolume, HMAC-SHA512)
  - Coinbase Advanced v3 (private /api/v3/brokerage/transaction_summary, ECDSA)

• Async (aiohttp)
• 1-hour in-memory cache
• Conservative defaults if auth fails
• Reads creds from environment (.env)

Env expected:
  KRAKEN_API_KEY=...
  KRAKEN_API_SECRET_B64=...   # base64 Kraken secret

  CB_ADV_API_KEY=organizations/.../apiKeys/<id>
  CB_ADV_PRIVATE_KEY="-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----\n"
     # or CB_ADV_PRIVATE_KEY_PATH=~/.keys/coinbase_private.pem
"""


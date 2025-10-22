from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv(override=True)

@dataclass
class krakenCreds:
    api_key: str | None = os.getenv("KRAKEN_API_KEY")
    api_secret_b64: str | None = os.getenv("KRAKEN_API_SECRET_B64")

@dataclass
class CBExCreds:
    api_key: str | None = os.getenv("CB_EX_API_KEY")
    api_secret_b64: str | None = os.getenv("CB_EX_API_SECRET_b64")
    passphrase: str | None = os.getenv("CB_EX_PASSPHRASE")

class FeeDefaults:
    # conservative fallbacks 9verify vs current public schedules)
    kraken_taker: float = 0.0026 #26 bps
    kraken_maker: float = 0.0016 #16 bps
    cb_taker: float = 0.0060     #60 bps (retail worst-case)
    cb_maker: float = 0.0040

KRAKEN = krakenCreds()
CB_EX = CBExCreds()
DEFAULTS = FeeDefaults()
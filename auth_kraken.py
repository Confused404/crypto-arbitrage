from urllib.parse import urlencode
import base64, hashlib, hmac, time

def sign_trade_volume(pair: str, api_key: str, api_secret_b64: str):
    """
    Build headers+body for Kraken /0/private/TradeVolume (POST).
    Returns (headers: dict, body: str) ready for aiohttp.
    """
    path = "/0/private/TradeVolume"
    url = "https://api.kraken.com" + path

    nonce = str(int(time.time() * 1000))
    body_dict = {"nonce": nonce, "pair": pair}
    body_enc = urlencode(body_dict)

    sha = hashlib.sha256((nonce + body_enc).encode()).digest()
    secret = base64.b64decode(api_secret_b64)
    msg = path.encode() + sha 
    sig = hmac.new(secret, msg, hashlib.sha512).digest()
    api_sign = base64.b64encode(sig).decode()

    headers = {
        "API-Key": api_key,
        "API-Sign": api_sign,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    return url, headers, body_enc


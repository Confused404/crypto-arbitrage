# using two venues Coinbase and Kraken
# BTC-USDT
#compute gross spreads both ways:
#  buy on Binance - sell on Kraken
#  buy on Kraken - sell on Binance
#subtract hardcoded feees from the spreads for net spreads
#emit log line when net spread > 0
#stop after 10 minutes
#Teaches venue API's symbol normalization, fees, 
#and the fact most opportunities vanish after costs
""" 
 (taker: you take liquidity from the order book)
 most arbitrage bots are 'takers' because you need speed not patience, 
 if you wait for a 'maker' order (another order type) 
 to get filled, the price gap can disappear

 💰 Why taker fees are critical in arbitrage
Let’s say:
You see a $10 price gap between Binance and OKX.
You want to buy on one exchange and sell on the other.
But:
    Binance taker fee: 0.10%
    OKX taker fee: 0.10%
    Total fee round trip = 0.20%
On a $70,000 BTC, 0.20% = $140 in fees.
That means:
👉 if the spread is less than $140, you don’t make money, even if the prices look different.
👉 only spreads larger than your fees are true opportunities. """

""" A pro arbitrageur would remind you:
Taker fees eat most spreads. 
Many apparent opportunities vanish once fees are applied.
Some exchanges offer lower fees (e.g., VIP accounts or rebates). 
That’s why infrastructure and fee structure often matter more than spotting the gap itself. """

""" TOB = "Top of Book" 
    every crypto exchange maintains an order book -- basically a list of all:
    * Bids = what buyers are willing to pay (best is highest)
    * Asks = what sellers are asking for (best is lowest)
    So TOB is the best bid and the best ask 
    TOB is thought of as the "front door" of the market
    for small retail arbitrage TOB gives you the fastest and clearest signal
    *** Pro traders often subsrcibe to real time TOB streams (websockets) 
    *** to detect and react to microsecond price changes
"""

"""
    Tickers are:
        Lightweight: They don’t require subscribing to the full order book.
        Fast: You can stream or poll them to track price movements in near real-time.
        Enough for many use cases: dashboards, alerts, price checks, etc.

    For arbitrage bots, they’re often used as the first stage to:
        Detect spread opportunities between exchanges,
        Decide when to pull more detailed data (e.g., full order book),
        Estimate potential profitability quickly.
"""

import asyncio, json, time, math
import websockets
from dotenv import load_dotenv
from fees import FeeCache

load_dotenv()
fee_cache = FeeCache(ttl_seconds=3600)
# cache current fee dicts so we don't fetch every tick
_current_fees = {
    "kraken":   None,  # {"taker": float, "maker": float}
    "coinbase": None,
}
_last_fee_refresh = 0.0
_FEE_REFRESH_SECS  = 60.0   # check once per minute; FeeCache itself TTLs to 1h


# old hardcoded fees
# FEE_BP = 10 #10 bps per side (0.10%)
# FEE = FEE_BP / 10_000.0

PAIR_KRAKEN = "BTC/USD" #v1 uses XBT/USD and v2 uses BTC/USD
PAIR_COINBASE  = "BTC-USD" #Coinbase product id

state = {
    "kraken": {"bid": None, "ask":None, "last_ts": None, "msgs": 0, "connected": False},
    "coinbase": {"bid": None, "ask":None, "last_ts": None, "msgs": 0, "connected": False},
}
# print debug stuff
def ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")
def dbg(label, *args):
    print(f"[{ts()}] [{label}]", *args, flush=True)

#old hardcodeed  net_spread
# def net_spread_buyA_sellB(askA, bidB):
#     buy_cost = askA * (1 + FEE)
#     sell_recv = bidB * (1 - FEE)
#     return sell_recv - buy_cost

def net_spread_buyA_sellB(askA, taker_fee_A, bidB, taker_fee_B):
    """
    Net P&L perBTC when buying at A's ask (paying A's taker fee)
    and selling at B's bod (paying B's taker fee).
    """
    buy_cost = askA * (1 + taker_fee_A)
    sell_recv = bidB * (1 - taker_fee_B)
    return sell_recv - buy_cost

async def kraken_loop():
    url = "wss://ws.kraken.com/v2"
    reconnect_tries = 0
    while True:
        try:
            dbg("KRAKEN", f"connecting to {url} (attempt={reconnect_tries})")
            async with websockets.connect(url, ping_interval=20, ping_timeout=25) as ws:
                state["kraken"]["connected"] = True
                reconnect_tries = 0

                async def subscribe(depth=10):
                    sub = {
                        "method": "subscribe",
                        "params": {
                            "channel": "book",
                            "symbol": [PAIR_KRAKEN],
                            "depth": depth
                        }
                    }
                    await ws.send(json.dumps(sub))
                    dbg("KRAKEN", f"subscribed: {sub}")

                await subscribe(depth=10)

                async for raw in ws:
                    state["kraken"]["msgs"] += 1
                    try:
                        msg = json.loads(raw)
                    except Exception as e:
                        dbg("KRAKEN_ERR", "json decode failed:", e, "raw head:", raw[:160])
                        continue

                    # server-level errors (e.g., unsupported depth)
                    if "data" in msg and msg["data"]:
                        ob = msg["data"][0]
                        bids = ob.get("bids", [])
                        asks = ob.get("asks", [])

                        def top_price(levels):
                            if not levels: return None
                            head = levels[0]
                            # v2 sends dicts: {"price": ..., "qty": ...}
                            if isinstance(head, dict) and "price" in head:
                                return float(head["price"])
                            # be tolerant if some venues send [price, qty]
                            if isinstance(head, (list, tuple)) and len(head) > 0:
                                return float(head[0])
                            return None

                        new_bid = top_price(bids)
                        new_ask = top_price(asks)

                        updated = False
                        if new_bid is not None:
                            state["kraken"]["bid"] = new_bid
                            updated = True
                        if new_ask is not None:
                            state["kraken"]["ask"] = new_ask
                            updated = True

                        if updated:
                            state["kraken"]["last_ts"] = time.time()
                            if state["kraken"]["msgs"] % 50 == 0 and \
                                state["kraken"]["bid"] is not None and state["kraken"]["ask"] is not None:
                                dbg("KRAKEN", f"msg#{state['kraken']['msgs']} TOB {state['kraken']['bid']:.2f}/{state['kraken']['ask']:.2f}")
                        else:
                            # truly nothing usable in this packet
                            dbg("KRAKEN_WARN", "book update without bid/ask levels (ignored)")

                    elif isinstance(msg, dict) and (msg.get("method") == "heartbeat" or msg.get("type") in ("subscribe","subscribed")):
                        dbg("KRAKEN_EVT", msg)

        except (websockets.ConnectionClosedOK, websockets.ConnectionClosedError) as e:
            state["kraken"]["connected"] = False
            dbg("KRAKEN_DISC", "connection closed:", e)
        except Exception as e:
            state["kraken"]["connected"] = False
            dbg("KRAKEN_ERR", "outer loop exception:", repr(e))

        reconnect_tries += 1
        delay = min(5 + reconnect_tries, 20)
        dbg("KRAKEN", f"reconnecting in {delay}s …")
        await asyncio.sleep(delay)


async def coinbase_loop():
    url = "wss://advanced-trade-ws.coinbase.com"
    reconnect_tries = 0
    while True:
        try:
            dbg("COINBASE", f"connecting to {url} (attempt={reconnect_tries})")
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                state["coinbase"]["connected"] = True
                reconnect_tries = 0
                sub = {"type": "subscribe", "channel": "ticker", "product_ids": [PAIR_COINBASE]}
                await ws.send(json.dumps(sub))
                dbg("COINBASE", f"subscribed: {sub}")

                async for raw in ws:
                    state["coinbase"]["msgs"] += 1
                    try:
                        msg = json.loads(raw)
                    except Exception as e:
                        dbg("CB_ERR", "json decode failed:", e, "raw head:", raw[:160])
                        continue

                    # Expect channel 'ticker' with events list
                    if msg.get("channel") == "ticker" and "events" in msg:
                        updated = False
                        for ev in msg["events"]:
                            # two possible shapes: with 'tickers' list or direct fields
                            if "tickers" in ev:
                                for t in ev["tickers"]:
                                    bid, ask = t.get("best_bid"), t.get("best_ask")
                                    if bid and ask:
                                        try:
                                            state["coinbase"]["bid"] = float(bid)
                                            state["coinbase"]["ask"] = float(ask)
                                            updated = True
                                        except Exception as e:
                                            dbg("CB_ERR", "price parse failed:", e, "tick head:", str(t)[:160])
                            else:
                                bid, ask = ev.get("best_bid"), ev.get("best_ask")
                                if bid and ask:
                                    try:
                                        state["coinbase"]["bid"] = float(bid)
                                        state["coinbase"]["ask"] = float(ask)
                                        updated = True
                                    except Exception as e:
                                        dbg("CB_ERR", "price parse failed:", e, "ev head:", str(ev)[:160])
                        if updated:
                            state["coinbase"]["last_ts"] = time.time()
                            if state["coinbase"]["msgs"] % 50 == 0:
                                dbg("COINBASE", f"msg#{state['coinbase']['msgs']} TOB bid/ask={state['coinbase']['bid']:.2f}/{state['coinbase']['ask']:.2f}")
                    elif msg.get("type") in ("subscriptions", "error"):
                        dbg("COINBASE_EVT", msg)
                    # else: ignore unrelated messages

        except (websockets.ConnectionClosedOK, websockets.ConnectionClosedError) as e:
            state["coinbase"]["connected"] = False
            dbg("CB_DISC", "connection closed:", e)
        except Exception as e:
            state["coinbase"]["connected"] = False
            dbg("CB_ERR", "outer loop exception:", repr(e))
        # backoff
        reconnect_tries += 1
        delay = min(5 + reconnect_tries, 20)
        dbg("COINBASE", f"reconnecting in {delay}s …")
        await asyncio.sleep(delay)
        
async def ensure_fees():
    """
    Refresh fees at most once per _Fee_REFRESH_SECS (cheap check).
    The feeCache inside does the heavy lifting (1h TTL by default)
    """
    global _last_fee_refresh, _current_fees
    now = time.time()
    if now - _last_fee_refresh < _FEE_REFRESH_SECS:
        return 
    
    try:
        kr = await fee_cache.get_fees("kraken", PAIR_KRAKEN)
        cb = await fee_cache.get_fees("coinbase", PAIR_COINBASE)
        first = (_current_fees["kraken"]) is None or (_current_fees["coinbase"] is None)
        changed = (kr != _current_fees["kraken"]) or (cb != _current_fees["coinbase"])

        _current_fees["kraken"] = kr
        _current_fees["coinbase"] = cb
        _last_fee_refresh = now

        if first or changed:
            dbg("FEES",
                f"KRAKEN taker={kr['taker']:.4%} maker={kr['maker']:.4%} |"
                f"CB taker={cb['taker']:.4%} maker={cb['maker']:.4%}")
    except Exception as e:
        dbg("FEES_WARN", f"fee refresh failed: {e}")

async def reporter_loop():
    last_warn_missing = 0.0
    last_warn_stale   = 0.0
    last_hb           = 0.0
    STALE_SECS = 5.0
    PROFIT_ALERT = 0.0  # raise this to $5/$10 when you want fewer alerts

    while True:
        k = state["kraken"]
        c = state["coinbase"]

        # connection heartbeat every 5s
        if time.time() - last_hb > 5:
            last_hb = time.time()
            dbg("HEARTBEAT",
                f"KRAKEN conn={k['connected']} msgs={k['msgs']} "
                f"COINBASE conn={c['connected']} msgs={c['msgs']}")

        await ensure_fees()

        # warn if missing either TOB
        have_all = all(v is not None for v in (k["bid"], k["ask"], c["bid"], c["ask"]))
        if not have_all and time.time() - last_warn_missing > 3:
            dbg("WARN", "waiting for both TOBs …",
                f"kraken_bid={k['bid']} kraken_ask={k['ask']} "
                f"coinbase_bid={c['bid']} coinbase_ask={c['ask']}")            
            last_warn_missing = time.time()

        # warn if stale
        now = time.time()
        for ex, name in ((k, "KRAKEN"), (c, "COINBASE")):
            last_ts = ex.get("last_ts")
            if (last_ts is not None) and (now - last_ts > STALE_SECS) and (now - last_warn_stale > 3):
                dbg("STALE", f"{name} TOB stale: {now - last_ts:.1f}s without update")
                last_warn_stale = now

        if have_all and _current_fees["kraken"] and _current_fees["coinbase"]:
            kf = _current_fees["kraken"]["taker"]
            cbf = _current_fees["coinbase"]["taker"]

            # buy Kraken ask, sell Coinbase bid
            a_to_b = net_spread_buyA_sellB(k["ask"], kf, c["bid"], cbf)  # buy Kraken ask, sell Coinbase bid
            # buy Coinbase ask, sell Kraken bid
            b_to_a = net_spread_buyA_sellB(c["ask"], cbf, k["bid"], kf)  # buy Coinbase ask, sell Kraken bid
            
            if a_to_b > PROFIT_ALERT:
                dbg("ALERT 🚀", f"Profitable K->CB trade found! Net profit = ${a_to_b:.2f} per BTC "
                                f"(buy {k['ask']:.2f} sell {c['bid']:.2f})")

            if b_to_a > PROFIT_ALERT:
                dbg("ALERT 🚀", f"Profitable CB->K trade found! Net profit = ${b_to_a:.2f} per BTC "
                                f"(buy {c['ask']:.2f} sell {k['bid']:.2f})")
            dbg("SPREAD",
            f"KRAKEN {k['bid']:.2f}/{k['ask']:.2f}  |  "
            f"CB {c['bid']:.2f}/{c['ask']:.2f}  |  "
            f"A->B(K->CB)={a_to_b:.2f}  B->A(CB->K)={b_to_a:.2f}")
        await asyncio.sleep(0.25)


async def main():
    dbg("BOOT", f"starting with pairs: kraken={PAIR_KRAKEN}, coinbase={PAIR_COINBASE}")
    await asyncio.gather(kraken_loop(), coinbase_loop(), reporter_loop())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        dbg("EXIT", "Ctrl+C received, shutting down…")



                    



import time
import logging
import signal
import httpx
from config import get_trades

logger = logging.getLogger(__name__)
_running = True


def _handle_signal(signum, frame):
    global _running
    logger.info(f"Received signal {signum}, shutting down...")
    _running = False


ENTRY_PRICE = get_trades()["eth_short"]["entry"]
url = "https://api.coinbase.com/v2/prices/ETH-USD/spot"

logger.info(f"Monitoring ETH price... Target Entry: ${ENTRY_PRICE}")

while _running:
    try:
        res = httpx.get(url, timeout=5.0)
        if res.status_code == 200:
            price = float(res.json()["data"]["amount"])
            logger.info(f"ETH price: ${price:.2f}")
            if price >= ENTRY_PRICE:
                print(f"BINGO! ETH price hit ${price:.2f}.")
                print(f"Limit Sell at ${ENTRY_PRICE:.2f} FILLED!")
                break
    except Exception as e:
        logger.warning(f"Error fetching ETH price: {e}")

    for _ in range(15):
        if not _running:
            break
        time.sleep(1)

if not _running:
    logger.info("ETH monitor shut down gracefully.")

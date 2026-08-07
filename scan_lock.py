"""Shared single-instance locks.

The scan lock keeps aegis_bot.py and poll_scanner.py from scanning at the same
time. The trade lock keeps two trade_manager processes from reading the same
PENDING rows and both placing an order.
"""
import fcntl
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_PATH = os.path.join(_DIR, ".aegis_scan.lock")
TRADE_LOCK_PATH = os.path.join(_DIR, ".aegis_trade.lock")


class ScanLock:
    """Non-blocking exclusive lock; acquired = True when held."""

    def __init__(self, path: str = LOCK_PATH):
        self._file = None
        self._path = path

    def __enter__(self) -> "ScanLock":
        self._file = open(self._path, "w")
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._file.close()
            self._file = None
        return self

    def __exit__(self, *exc) -> None:
        if self._file is not None:
            fcntl.flock(self._file, fcntl.LOCK_UN)
            self._file.close()
            self._file = None

    @property
    def acquired(self) -> bool:
        return self._file is not None

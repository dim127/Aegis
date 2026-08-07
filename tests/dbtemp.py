"""Point every database path at a throwaway directory.

Tests used to override only DB_PATH and SIGNALS_DB_PATH. That silently stopped
isolating anything the moment aegis_config.json switched to testnet, because
db._active_paths() then returns the testnet pair instead — so tests wrote to the
real data/aegis_cache_testnet.db and accumulated each other's state.

Redirecting all four keeps a test's storage independent of whichever mode the
checked-in config happens to be in.
"""
import os
import tempfile

import db


def use_temp_dbs() -> str:
    """Redirect live and testnet db paths to a fresh temp dir. Returns the dir."""
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "cache.db")
    db.SIGNALS_DB_PATH = os.path.join(tmp, "signals.db")
    db.TESTNET_DB_PATH = os.path.join(tmp, "cache_testnet.db")
    db.TESTNET_SIGNALS_PATH = os.path.join(tmp, "signals_testnet.db")
    return tmp

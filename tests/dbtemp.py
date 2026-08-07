"""Point the database paths at a throwaway directory."""
import os
import tempfile

import db


def use_temp_dbs() -> str:
    """Redirect db paths to a fresh temp dir. Returns the dir."""
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "cache.db")
    db.SIGNALS_DB_PATH = os.path.join(tmp, "signals.db")
    return tmp

#duckdb_manager
#owns the duckdb connection, connect to the same DB file each run

import duckdb
from app.config import settings

class DuckDBManager:
    def __init__(self):
        self.con = None

    def connect(self):
        # This file persists across restarts.
        self.con = duckdb.connect(settings.DUCKDB_PATH)
        return self.con

    def close(self):
        if self.con:
            self.con.close()
            self.con = None

duckdb_manager = DuckDBManager()
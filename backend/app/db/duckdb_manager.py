#duckdb_manager
#owns the duckdb connection, connect to the same DB file each run

import duckdb
from app.config import settings #to use settings.DUCKDB_PATH to access data path

class DuckDBManager:
    def __init__(self): #constructor will run when object created
        self.con = None #no connection upon object creation

    def connect(self):
        # This file persists across restarts.
        self.con = duckdb.connect(settings.DUCKDB_PATH)
        self.con.execute(f"PRAGMA threads={settings.THREADS};")
        if not settings.PARQUET_KEY:
            raise RuntimeError(
                "PARQUET_KEY is not set. Set environment variable PARQUET_KEY to the given key."
            )
        self.con.execute(f"PRAGMA add_parquet_key('{settings.PARQUET_KEY_NAME}', '{settings.PARQUET_KEY}');")

        return self.con

    def close(self):
        if self.con:
            self.con.close()
            self.con = None

duckdb_manager = DuckDBManager()
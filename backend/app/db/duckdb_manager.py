#duckdb_manager
#owns the duckdb connection, connect to the same DB file each run

import duckdb
from app.config import settings #to use settings.DUCKDB_PATH to access data path

KEY_NAME = "cap26_key"

class DuckDBManager:
    def __init__(self): #constructor will run when object created
        self.con = None #no connection upon object creation

    def connect(self):
        self.con = duckdb.connect(settings.DUCKDB_PATH)
        self.con.execute(f"PRAGMA threads={settings.THREADS};")

        if not settings.PARQUET_KEY:
            raise RuntimeError("PARQUET_KEY is not set")
        key_name = KEY_NAME.replace("'", "''")
        key_val = settings.PARQUET_KEY.replace("'", "''")
        self.con.execute(f"PRAGMA add_parquet_key('{key_name}', '{key_val}');")

        return self.con

    def close(self):
        if self.con:
            self.con.close()
            self.con = None

duckdb_manager = DuckDBManager()
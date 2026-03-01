#config.py
#central place for settings e.g. paths

from pydantic import BaseModel
import os
from pathlib import Path

class Settings(BaseModel):
    DUCKDB_PATH: str = "data/nccs_cap26"
    PARQUET_DIR: str = "data/parquet"           # folder containing parquet files
    PARQUET_KEY_NAME: str = "cap26"
    #setting the key in windows powershell: setx PARQUET_KEY "YOUR_KEY"
    # or in VScode $env:PARQUET_KEY="YOUR_KEY"
    PARQUET_KEY: str | None = os.getenv("PARQUET_KEY") 
    MAX_ROWS_DEFAULT: int = 5000                # default LIMIT for results
    MAX_ROWS_HARD: int = 20000                  # hard cap to prevent abuse
    THREADS: int = 4                            # DuckDB parallelism

settings = Settings()

# Ensure folders exist so startup doesn't crash
Path("data").mkdir(exist_ok=True)
Path(settings.PARQUET_DIR).mkdir(parents=True, exist_ok=True)
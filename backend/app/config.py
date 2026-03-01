#config.py
#central place for settings e.g. paths

from pydantic import BaseModel
from pathlib import Path
from dotenv import load_dotenv
import os

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

class Settings(BaseModel):
    DUCKDB_PATH: str = "data/nccs_cap26.db"
    PARQUET_DIR: str = "data/parquet"           # folder containing parquet files
    MAX_ROWS_DEFAULT: int = 5000                # default LIMIT for results
    MAX_ROWS_HARD: int = 20000                  # hard cap to prevent abuse
    THREADS: int = 4                            # DuckDB parallelism
    PARQUET_KEY: str = os.getenv("PARQUET_KEY", "")

settings = Settings()

# Ensure folders exist so startup doesn't crash
Path("data").mkdir(exist_ok=True)
Path(settings.PARQUET_DIR).mkdir(parents=True, exist_ok=True)
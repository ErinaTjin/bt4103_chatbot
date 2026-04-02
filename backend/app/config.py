#config.py
#central place for settings e.g. paths

from pydantic import BaseModel
from pathlib import Path
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

class Settings(BaseModel):
    DUCKDB_PATH: str = str(BASE_DIR / "data" / "nl2sql_runtime.db") #system database created from parquet files
    PARQUET_DIR: str = str(BASE_DIR / "data" / "parquet")
    SEMANTIC_LAYER_DIR: str = str(BASE_DIR / "nl2sql" / "semantic")
    MAX_ROWS_DEFAULT: int = 5000
    MAX_ROWS_HARD: int = 20000
    THREADS: int = 4
    PARQUET_KEY: str = os.getenv("PARQUET_KEY", "")
    QUERY_TIMEOUT_SECONDS: int = 180 #max execution time for SQL queries

settings = Settings()
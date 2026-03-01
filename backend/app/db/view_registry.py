#view_registry.py
#converts raw parquet files into stable queryable objects
#query anchor_view.file_name instead of file paths e.g. SELECT * FROM anchor_view.file_name instead of SELECT * FROM read_parquet(file_path)

from pathlib import Path
from app.config import settings

# Maps view name to the physical parquet file
VIEW_SPECS = {
    "person": "person.parquet",
    "death": "death.parquet",
    "condition_occurrence": "condition_occurrence.parquet",
    "procedure_occurrence": "procedure_occurrence.parquet",
    "drug_exposure_cancerdrugs": "drug_exposure_cancerdrugs.parquet",
    "measurement_mutation": "measurement_mutation.parquet",
}

SCHEMA = "anchor_view"

#Accepts a duckdb connection and creates views inside duckdb; runs once during FastAPI startup
def register_views(con):
    # Create a namespace to keep things clean (schema = anchor)
    con.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}";')

    parquet_dir = Path(settings.PARQUET_DIR) #create Path object for data/parquet

    for view_name, file_name in VIEW_SPECS.items():
        file_path = (parquet_dir / file_name).as_posix() #creates file path for each view

        # Create stable view name anchor.<view_name>
        # Create OR REPLACE makes it safe to run repeatedly on restart
        sql = f"""
        CREATE OR REPLACE VIEW "{SCHEMA}"."{view_name}" AS
        SELECT * FROM read_parquet('{file_path}');
        """
        con.execute(sql)
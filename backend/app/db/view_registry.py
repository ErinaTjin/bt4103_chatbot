#view_registry.py
#converts raw parquet files into stable queryable objects
#users will query anchor.file_name instead of file paths

from pathlib import Path
from app.config import settings

# Your 6 datasets
VIEW_SPECS = {
    "person": "person.parquet",
    "death": "death.parquet",
    "condition_occurrence": "condition_occurrence.parquet",
    "procedure_occurrence": "procedure_occurrence.parquet",
    "drug_exposure_cancerdrugs": "drug_exposure_cancerdrugs.parquet",
    "measurement_mutation": "measurement_mutation.parquet",
}

def register_views(con):
    # Create a namespace to keep things clean (schema = anchor)
    con.execute("CREATE SCHEMA IF NOT EXISTS anchor;")

    parquet_dir = Path(settings.PARQUET_DIR)

    for view_name, file_name in VIEW_SPECS.items():
        file_path = (parquet_dir / file_name).as_posix()

        # Create stable view name anchor.<view_name>
        # Create OR REPLACE makes it safe to run repeatedly on restart
        sql = f"""
        CREATE OR REPLACE VIEW anchor.{view_name} AS
        SELECT * FROM read_parquet('{file_path}');
        """
        con.execute(sql)
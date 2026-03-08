import duckdb

db_path = 'nccs_cap26.db'

try:
    con = duckdb.connect(db_path)
    print("Database connection successful!")
    print("Tables in database:")
    tables = con.execute("SHOW TABLES").fetchall()
    print(tables)
    
    # Try to read the tables
    for table in tables:
        t_name = table[0]
        print("\nTable: " + t_name)
        df = con.execute("SELECT * FROM " + t_name + " LIMIT 5").df()
        print(df.head())
        
except Exception as e:
    print("Error opening database: " + str(e))

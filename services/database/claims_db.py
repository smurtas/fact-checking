import duckdb
import os

DB_PATH = "claim_history.duckdb"

# Make sure DB exists at startup

def init_db():
    if not os.path.exists(DB_PATH):
        duckdb.connect(DB_PATH).close()     
    con = duckdb.connect(DB_PATH)
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS history (
            id TEXT,
            claim TEXT,
            label INTEGER,
            model TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.close()
# Save a new claim check result
def save_check(claim, label, model):

    con = duckdb.connect(DB_PATH)
    con.execute(f"""
        INSERT INTO history (id, claim, label, model)
        VALUES (?, ?, ?, ?)
    """, (str(hash(claim)), claim, label, model))
    con.close()

# Load all saved checks
def load_history():
    con = duckdb.connect(DB_PATH)
    df = con.execute("SELECT * FROM history ORDER BY timestamp DESC").df()
    con.close()
    return df
   
# Clear the history table
def clear_history():
    con = duckdb.connect(DB_PATH)
    con.execute("DELETE FROM history")
    con.close()
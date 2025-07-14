import duckdb
import os

DB_PATH = "claim_history.duckdb"

# Make sure DB exists at startup
def init_db():
    duckdb.sql(f"""
        CREATE TABLE IF NOT EXISTS history (
            id TEXT,
            claim TEXT,
            label INTEGER,
            model TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

# Save a new claim check result
def save_check(claim, label, model):
    duckdb.sql("""
        INSERT INTO history (id, claim, label, model)
        VALUES (?, ?, ?, ?)
    """, (str(hash(claim)), claim, label, model))

# Load all saved checks
def load_history():
    return duckdb.sql("SELECT * FROM history ORDER BY timestamp DESC").df()

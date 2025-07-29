"""
claims_db.py

This module handles local logging and analytics of fact-checking results using DuckDB.
DuckDB is a lightweight, embedded analytics database — ideal for structured data storage
without requiring a separate DB server.

Features:
- Initialize and manage a persistent history table
- Store results of manual claim verifications
- Retrieve and clear the claim-check history
"""
import duckdb
import os

# Path to the DuckDB database file

DB_PATH = "claim_history.duckdb"

# Make sure DB exists at startup
# ======================
# Initialization Logic
# ======================
def init_db():
    """
    Initialize the DuckDB database.

    - If the database file doesn't exist, create it.
    - Create a table `history` if not already present, to store claim results.

    The `history` table stores:
    - id: Hash of the claim text
    - claim: The full text of the claim
    - label: Model prediction (e.g., 0 = false, 1 = true)
    - model: Which model(s) was used
    - timestamp: Auto-generated insert time
    """
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
# ==========================
# Save Check to DuckDB
# ==========================
def save_check(claim, label, model):
    """
    Save a new fact-checking result to the history table.

    Args:
        claim (str): The factual claim text
        label (int): NLP model's prediction (0 = False, 1 = True)
        model (str): Identifier for the model used (e.g., "roberta + deberta")
    """
    con = duckdb.connect(DB_PATH)
    con.execute(f"""
        INSERT INTO history (id, claim, label, model)
        VALUES (?, ?, ?, ?)
    """, (str(hash(claim)), claim, label, model))
    con.close()

# Load all saved checks
# ===========================
# Retrieve Saved History
# ===========================
def load_history():
    """
    Load the entire claim check history, ordered by timestamp.

    Returns:
        pd.DataFrame: A DataFrame containing all rows from the `history` table.
    """
    con = duckdb.connect(DB_PATH)
    df = con.execute("SELECT * FROM history ORDER BY timestamp DESC").df()
    con.close()
    return df
   
# =====================
# Clear All History
# =====================
def clear_history():
    """
    Delete all records from the history table.
    This is used for resetting or clearing the local log.
    """
    con = duckdb.connect(DB_PATH)
    con.execute("DELETE FROM history")
    con.close()
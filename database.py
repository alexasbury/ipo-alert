"""
SQLite persistence layer for IPO filing data.
"""

import os
import sqlite3
from typing import Optional

DB_PATH = os.environ.get("DB_PATH", "ipo_filings.db")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ipo_filings (
    id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name                        TEXT    NOT NULL,
    filing_date                         TEXT    NOT NULL,
    accession_number                    TEXT    UNIQUE NOT NULL,
    cik                                 TEXT    NOT NULL,
    transfer_agent                      TEXT,
    legal_counsel                       TEXT,
    dually_listed                       TEXT,
    lock_up_date                        TEXT,
    lock_up_expiration_date             TEXT,
    lock_up_terms                       TEXT,
    top_5_percent_shareholders          TEXT,
    top_5_percent_shareholders_footnotes TEXT,
    is_venture_backed                   TEXT,
    created_at                          TEXT    DEFAULT (datetime('now'))
)
"""


def init_db(db_path: str = DB_PATH) -> None:
    """Create the database and table if they don't already exist."""
    conn = sqlite3.connect(db_path)
    conn.execute(CREATE_TABLE_SQL)
    conn.commit()
    conn.close()


def filing_exists(accession_number: str, db_path: str = DB_PATH) -> bool:
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "SELECT 1 FROM ipo_filings WHERE accession_number = ?", (accession_number,)
    )
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def save_filing(filing_data, db_path: str = DB_PATH) -> bool:
    """
    Insert a FilingData (or dict) into the database.
    Returns True if saved, False if already present.
    """
    d = filing_data.to_dict() if hasattr(filing_data, "to_dict") else filing_data

    if filing_exists(d["accession_number"], db_path):
        return False

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT OR IGNORE INTO ipo_filings (
            company_name, filing_date, accession_number, cik,
            transfer_agent, legal_counsel, dually_listed,
            lock_up_date, lock_up_expiration_date, lock_up_terms,
            top_5_percent_shareholders, top_5_percent_shareholders_footnotes,
            is_venture_backed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            d["company_name"],
            d["filing_date"],
            d["accession_number"],
            d["cik"],
            d.get("transfer_agent"),
            d.get("legal_counsel"),
            d.get("dually_listed"),
            d.get("lock_up_date"),
            d.get("lock_up_expiration_date"),
            d.get("lock_up_terms"),
            d.get("top_5_percent_shareholders"),
            d.get("top_5_percent_shareholders_footnotes"),
            d.get("is_venture_backed"),
        ),
    )
    conn.commit()
    conn.close()
    return True


def get_filings_by_date_range(
    start_date: str, end_date: str, db_path: str = DB_PATH
) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT * FROM ipo_filings
        WHERE filing_date BETWEEN ? AND ?
        ORDER BY filing_date DESC
        """,
        (start_date, end_date),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_filing_by_accession(
    accession_number: str, db_path: str = DB_PATH
) -> Optional[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT * FROM ipo_filings WHERE accession_number = ?", (accession_number,)
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_filings(db_path: str = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM ipo_filings ORDER BY filing_date DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

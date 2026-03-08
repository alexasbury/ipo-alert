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
    filing_type                         TEXT,
    transfer_agent                      TEXT,
    transfer_agent_normalized           TEXT,
    legal_counsel                       TEXT,
    dually_listed                       TEXT,
    lock_up_date                        TEXT,
    lock_up_expiration_date             TEXT,
    lock_up_terms                       TEXT,
    top_5_percent_shareholders          TEXT,
    top_5_percent_shareholders_footnotes TEXT,
    is_venture_backed                   TEXT,
    is_venture_backed_validated         TEXT,
    -- prospectus_date stores the 424B4 filing date, which is the closest
    -- available proxy for the IPO date. No separate ipo_date field is
    -- available from EDGAR metadata.
    prospectus_date                     TEXT,
    document_priority                   TEXT,
    lock_up_days                        INTEGER,
    lock_up_expires_on                  TEXT,
    created_at                          TEXT    DEFAULT (datetime('now'))
)
"""


def init_db(db_path: str = DB_PATH) -> None:
    """Create the database and table if they don't already exist."""
    conn = sqlite3.connect(db_path)
    conn.execute(CREATE_TABLE_SQL)
    for col_def in [
        "prospectus_date TEXT",
        "lock_up_days INTEGER",
        "lock_up_expires_on TEXT",
        "filing_type TEXT",
        "document_priority TEXT",
        "transfer_agent_normalized TEXT",
        "is_venture_backed_validated TEXT",
    ]:
        try:
            conn.execute(f"ALTER TABLE ipo_filings ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()




_PRIORITY = {"S-1": 1, "S-1/A": 2, "424B4": 3}


def upsert_filing(filing_data, db_path: str = DB_PATH) -> str:
    """
    Insert or update a filing record, governed by document priority.

    Priority order: S-1 (1) < S-1/A (2) < 424B4 (3).

    - No record for this CIK → insert, return "inserted"
    - Record exists and incoming has higher priority → update enrichable
      fields (preserve original filing_date and accession_number),
      return "updated"
    - Record exists and incoming has equal or lower priority → skip,
      return "skipped"

    Args:
        filing_data: dict or object with a to_dict() method
        db_path:     path to the SQLite database file

    Returns:
        One of "inserted", "updated", or "skipped"
    """
    d = filing_data.to_dict() if hasattr(filing_data, "to_dict") else dict(filing_data)

    cik = d["cik"]
    incoming_priority_label = d.get("document_priority") or d.get("filing_type", "S-1")
    incoming_priority = _PRIORITY.get(incoming_priority_label, 0)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cur = conn.execute(
            "SELECT * FROM ipo_filings WHERE cik = ?", (cik,)
        )
        existing = cur.fetchone()

        if existing is None:
            # No record for this CIK — insert fresh
            conn.execute(
                """
                INSERT INTO ipo_filings (
                    company_name, filing_date, accession_number, cik,
                    transfer_agent, legal_counsel, dually_listed,
                    lock_up_date, lock_up_expiration_date, lock_up_terms,
                    top_5_percent_shareholders, top_5_percent_shareholders_footnotes,
                    is_venture_backed, filing_type, document_priority, prospectus_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    d["company_name"],
                    d["filing_date"],
                    d["accession_number"],
                    cik,
                    d.get("transfer_agent"),
                    d.get("legal_counsel"),
                    d.get("dually_listed"),
                    d.get("lock_up_date"),
                    d.get("lock_up_expiration_date"),
                    d.get("lock_up_terms"),
                    d.get("top_5_percent_shareholders"),
                    d.get("top_5_percent_shareholders_footnotes"),
                    d.get("is_venture_backed"),
                    incoming_priority_label,
                    incoming_priority_label,
                    d.get("prospectus_date"),
                ),
            )
            conn.commit()
            return "inserted"

        existing_priority_label = existing["document_priority"] or "S-1"
        existing_priority = _PRIORITY.get(existing_priority_label, 0)

        if incoming_priority > existing_priority:
            # Higher-priority filing arrived — update enrichable fields,
            # but preserve original filing_date and accession_number.
            conn.execute(
                """
                UPDATE ipo_filings SET
                    company_name=?,
                    transfer_agent=?, legal_counsel=?, dually_listed=?,
                    lock_up_date=?, lock_up_expiration_date=?, lock_up_terms=?,
                    top_5_percent_shareholders=?, top_5_percent_shareholders_footnotes=?,
                    is_venture_backed=?, filing_type=?, document_priority=?,
                    prospectus_date=?
                WHERE cik=?
                """,
                (
                    d["company_name"],
                    d.get("transfer_agent"),
                    d.get("legal_counsel"),
                    d.get("dually_listed"),
                    d.get("lock_up_date"),
                    d.get("lock_up_expiration_date"),
                    d.get("lock_up_terms"),
                    d.get("top_5_percent_shareholders"),
                    d.get("top_5_percent_shareholders_footnotes"),
                    d.get("is_venture_backed"),
                    incoming_priority_label,
                    incoming_priority_label,
                    d.get("prospectus_date"),
                    cik,
                ),
            )
            conn.commit()
            return "updated"

        return "skipped"

    finally:
        conn.close()


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




def apply_normalization(accession_number: str, derived: dict, db_path: str = DB_PATH) -> None:
    """
    Write derived/normalized fields back to an existing row by accession number.

    Writes: lock_up_days, lock_up_expires_on, transfer_agent_normalized,
            is_venture_backed_validated.

    Also updates is_venture_backed when the validated value is 'Yes' and the
    stored value is not already 'Yes' (i.e. cross-check upgraded the signal).
    """
    validated_vc = derived.get("is_venture_backed_validated")

    conn = sqlite3.connect(db_path)
    conn.execute(
        """UPDATE ipo_filings
           SET lock_up_days=?,
               lock_up_expires_on=?,
               transfer_agent_normalized=?,
               is_venture_backed_validated=?
           WHERE accession_number=?""",
        (
            derived.get("lock_up_days"),
            derived.get("lock_up_expires_on"),
            derived.get("transfer_agent_normalized"),
            validated_vc,
            accession_number,
        ),
    )

    # Upgrade is_venture_backed in-place if the VC cross-check produced a
    # stronger signal than Claude's original result.
    if validated_vc == "Yes":
        conn.execute(
            """UPDATE ipo_filings
               SET is_venture_backed=?
               WHERE accession_number=? AND (is_venture_backed IS NULL OR is_venture_backed != 'Yes')""",
            ("Yes", accession_number),
        )

    conn.commit()
    conn.close()


def get_filings_for_email(
    week_start: str, week_end: str, db_path: str = DB_PATH
) -> list[dict]:
    """
    Return all filings whose filing_date falls within [week_start, week_end].

    Ordered by filing_date DESC. Returns all columns needed for email rendering.

    Args:
        week_start: YYYY-MM-DD start of date range (inclusive)
        week_end:   YYYY-MM-DD end of date range (inclusive)
        db_path:    Path to the SQLite database file

    Returns:
        List of filing dicts with all columns, ordered by filing_date DESC.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT * FROM ipo_filings
            WHERE filing_date BETWEEN ? AND ?
            ORDER BY filing_date DESC
            """,
            (week_start, week_end),
        )
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    return rows


def audit_db(db_path: str = DB_PATH) -> None:
    """
    Print a summary of the database: total rows and NULL count per column.

    Useful for diagnosing extraction gaps. Output is written to stdout.

    Args:
        db_path: Path to the SQLite database file
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM ipo_filings")
        total = cur.fetchone()[0]
        print(f"[DB Audit] Total filings: {total}")

        col_cur = conn.execute("PRAGMA table_info(ipo_filings)")
        columns = [row[1] for row in col_cur.fetchall()]

        print("[DB Audit] NULL counts per column:")
        for col in columns:
            null_cur = conn.execute(
                f"SELECT COUNT(*) FROM ipo_filings WHERE \"{col}\" IS NULL"
            )
            null_count = null_cur.fetchone()[0]
            print(f"  {col:<40}: {null_count:>4} nulls")
    except sqlite3.Error as e:
        print(f"[DB Audit] Error reading database: {e}")
    finally:
        conn.close()


def get_upcoming_lockups(days_ahead: int = 30, db_path: str = DB_PATH) -> list[dict]:
    """Return filings whose lock-up expires within the next `days_ahead` days."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT * FROM ipo_filings
        WHERE lock_up_expires_on IS NOT NULL
          AND lock_up_expires_on BETWEEN date('now') AND date('now', ? || ' days')
        ORDER BY lock_up_expires_on
        """,
        (f"+{days_ahead}",),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows



#!/usr/bin/env python3
"""
Run this script to migrate an existing ipo_filings.db to the latest schema.
Safe to run multiple times — uses ALTER TABLE IF NOT EXISTS pattern.

Usage:
    python migrate_db.py
"""

import sys

from database import DB_PATH, audit_db, init_db


def main() -> None:
    """Apply all schema migrations to ipo_filings.db and print an audit summary."""
    print(f"[Migrate] Applying migrations to: {DB_PATH}")
    try:
        init_db(DB_PATH)
        print("[Migrate] Schema migration complete.")
    except Exception as e:
        print(f"[Migrate] ERROR during migration: {e}", file=sys.stderr)
        sys.exit(1)

    print()
    audit_db(DB_PATH)
    print()
    print("[Migrate] SUCCESS — database is up to date.")


if __name__ == "__main__":
    main()

-- IPO Filings — Query Reference
-- Run with: sqlite3 ipo_filings.db < queries.sql
--       or: sqlite3 ipo_filings.db
--              then: .read queries.sql
--              or paste individual blocks below

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. All filings — clean overview
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    company_name,
    filing_date,
    prospectus_date,
    is_venture_backed,
    dually_listed,
    lock_up_days,
    lock_up_expires_on,
    transfer_agent,
    legal_counsel
FROM ipo_filings
ORDER BY filing_date DESC;


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Full detail for a single company
-- ─────────────────────────────────────────────────────────────────────────────
SELECT *
FROM ipo_filings
WHERE company_name = 'CoreWeave, Inc.';   -- change search term as needed


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Upcoming lock-up expirations (next 90 days)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    company_name,
    prospectus_date,
    lock_up_days,
    lock_up_expires_on,
    lock_up_expiration_date     -- raw text from filing
FROM ipo_filings
WHERE lock_up_expires_on IS NOT NULL
  AND lock_up_expires_on BETWEEN date('now') AND date('now', '+90 days')
ORDER BY lock_up_expires_on;


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Already-expired lock-ups
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    company_name,
    prospectus_date,
    lock_up_days,
    lock_up_expires_on
FROM ipo_filings
WHERE lock_up_expires_on IS NOT NULL
  AND lock_up_expires_on < date('now')
ORDER BY lock_up_expires_on DESC;


-- ─────────────────────────────────────────────────────────────────────────────
-- 5. VC-backed IPOs only
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    company_name,
    filing_date,
    top_5_percent_shareholders,
    lock_up_days,
    lock_up_expires_on
FROM ipo_filings
WHERE is_venture_backed = 'Yes'
ORDER BY filing_date DESC;


-- ─────────────────────────────────────────────────────────────────────────────
-- 6. Dual / multi-class share structures
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    company_name,
    filing_date,
    dually_listed,
    top_5_percent_shareholders
FROM ipo_filings
WHERE dually_listed NOT IN ('Single class', 'Unknown')
ORDER BY filing_date DESC;


-- ─────────────────────────────────────────────────────────────────────────────
-- 7. Filings not yet enriched by a 424B4 prospectus
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    company_name,
    filing_date,
    accession_number,
    cik
FROM ipo_filings
WHERE prospectus_date IS NULL
ORDER BY filing_date DESC;


-- ─────────────────────────────────────────────────────────────────────────────
-- 8. Filings where lock-up duration could not be parsed (needs manual review)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    company_name,
    filing_date,
    lock_up_expiration_date     -- raw text — inspect to improve parser
FROM ipo_filings
WHERE lock_up_days IS NULL
  AND lock_up_expiration_date NOT IN ('Pending IPO', 'Not found', 'Unknown', '')
  AND lock_up_expiration_date IS NOT NULL
ORDER BY filing_date DESC;


-- ─────────────────────────────────────────────────────────────────────────────
-- 9. Summary stats
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    COUNT(*)                                        AS total_filings,
    SUM(CASE WHEN prospectus_date IS NOT NULL
             THEN 1 ELSE 0 END)                     AS enriched_with_424b4,
    SUM(CASE WHEN is_venture_backed = 'Yes'
             THEN 1 ELSE 0 END)                     AS vc_backed,
    SUM(CASE WHEN lock_up_days IS NOT NULL
             THEN 1 ELSE 0 END)                     AS lock_up_parsed,
    AVG(lock_up_days)                               AS avg_lock_up_days,
    MIN(lock_up_expires_on)                         AS earliest_expiry,
    MAX(lock_up_expires_on)                         AS latest_expiry
FROM ipo_filings;

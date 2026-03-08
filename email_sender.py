"""
Format and send the weekly IPO S-1 alert email via Gmail SMTP.

All CSS is inlined on HTML elements for maximum email-client compatibility.
No <style> block or external stylesheets are used.

Recipient handling: RECIPIENT_EMAIL in .env may contain a comma-separated list
of addresses (e.g. "alice@example.com,bob@example.com"). The line below splits
on commas so every address in that list receives the email.
"""

import os
import smtplib
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

GMAIL_USER = os.environ.get("GMAIL_USER", "alexanderasbury@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# RECIPIENT_EMAIL may be a comma-separated list; split handles both single and
# multiple addresses transparently.
_RECIPIENT_RAW = os.environ.get("RECIPIENT_EMAIL", "alexanderasbury@gmail.com")
RECIPIENT_EMAILS = [r.strip() for r in _RECIPIENT_RAW.split(",") if r.strip()]


# ---------------------------------------------------------------------------
# Filing status helpers
# ---------------------------------------------------------------------------

_STATUS_LABELS: dict[str, str] = {
    "S-1": "S-1 — IPO Pending",
    "S-1/A": "S-1/A — Amended",
    "424B4": "424B4 — IPO Confirmed",
}

# Inline badge styles keyed by document_priority
_STATUS_BADGE_STYLES: dict[str, str] = {
    "S-1": (
        "display:inline-block;padding:3px 10px;border-radius:4px;"
        "font-size:11px;font-weight:700;color:#fff;"
        "background:#e65100;margin-left:8px;vertical-align:middle;"
    ),
    "S-1/A": (
        "display:inline-block;padding:3px 10px;border-radius:4px;"
        "font-size:11px;font-weight:700;color:#fff;"
        "background:#1565c0;margin-left:8px;vertical-align:middle;"
    ),
    "424B4": (
        "display:inline-block;padding:3px 10px;border-radius:4px;"
        "font-size:11px;font-weight:700;color:#fff;"
        "background:#2e7d32;margin-left:8px;vertical-align:middle;"
    ),
}

# Inline styles for VC badges
_VC_BADGE_STYLES: dict[str, str] = {
    "Yes": (
        "display:inline-block;padding:3px 8px;border-radius:4px;"
        "font-size:11px;font-weight:700;color:#fff;background:#2e7d32;margin-left:6px;"
    ),
    "No": (
        "display:inline-block;padding:3px 8px;border-radius:4px;"
        "font-size:11px;font-weight:700;color:#fff;background:#757575;margin-left:6px;"
    ),
    "Unknown": (
        "display:inline-block;padding:3px 8px;border-radius:4px;"
        "font-size:11px;font-weight:700;color:#fff;background:#e65100;margin-left:6px;"
    ),
}

# Shared inline styles (used as Python constants, not a CSS block)
_BODY_STYLE = (
    "font-family:Arial,Helvetica,sans-serif;color:#222;max-width:860px;"
    "margin:0 auto;padding:24px;background:#f4f6f9;"
)
_H2_STYLE = "color:#1a1a2e;border-bottom:3px solid #4a90e2;padding-bottom:8px;"
_CARD_STYLE = (
    "background:#fff;border:1px solid #dde3ec;border-radius:10px;"
    "padding:22px;margin-bottom:24px;box-shadow:0 2px 6px rgba(0,0,0,.06);"
)
_CARD_H3_STYLE = "margin:0 0 4px;color:#1a1a2e;font-size:18px;"
_META_STYLE = "color:#666;font-size:12px;margin-bottom:14px;"
_TABLE_STYLE = "width:100%;border-collapse:collapse;"
_TD_STYLE = "padding:9px 12px;vertical-align:top;font-size:13px;border-bottom:1px solid #e8edf5;"
_TD_LABEL_STYLE = (
    "padding:9px 12px;vertical-align:top;font-size:13px;"
    "border-bottom:1px solid #e8edf5;font-weight:600;color:#444;"
    "width:210px;white-space:nowrap;"
)
_TD_EVEN_STYLE = (
    "padding:9px 12px;vertical-align:top;font-size:13px;"
    "border-bottom:1px solid #e8edf5;background:#f0f5ff;"
)
_TD_EVEN_LABEL_STYLE = (
    "padding:9px 12px;vertical-align:top;font-size:13px;"
    "border-bottom:1px solid #e8edf5;background:#f0f5ff;"
    "font-weight:600;color:#444;width:210px;white-space:nowrap;"
)
_FOOTER_STYLE = (
    "color:#999;font-size:11px;margin-top:20px;"
    "border-top:1px solid #dde3ec;padding-top:12px;"
)
_SECTION_H2_STYLE = (
    "color:#1a1a2e;border-bottom:3px solid #7b1fa2;padding-bottom:8px;margin-top:40px;"
)
_LOCKUP_TABLE_STYLE = "width:100%;border-collapse:collapse;margin-top:12px;"
_LOCKUP_TH_STYLE = (
    "padding:9px 12px;text-align:left;font-size:13px;font-weight:700;"
    "color:#fff;background:#7b1fa2;border-bottom:2px solid #6a1b9a;"
)
_LOCKUP_TD_STYLE = (
    "padding:9px 12px;vertical-align:top;font-size:13px;"
    "border-bottom:1px solid #e8edf5;"
)
_LOCKUP_TD_EVEN_STYLE = (
    "padding:9px 12px;vertical-align:top;font-size:13px;"
    "border-bottom:1px solid #e8edf5;background:#f9f4ff;"
)


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _status_badge(document_priority: str) -> str:
    """Return an inline-styled HTML badge for the given document_priority."""
    label = _STATUS_LABELS.get(document_priority, document_priority)
    style = _STATUS_BADGE_STYLES.get(
        document_priority,
        "display:inline-block;padding:3px 10px;border-radius:4px;"
        "font-size:11px;font-weight:700;color:#fff;background:#9e9e9e;margin-left:8px;",
    )
    return f'<span style="{style}">{escape(label)}</span>'


def _vc_badge(is_vc: str) -> str:
    """Return an inline-styled HTML badge for venture-backed status."""
    key = is_vc if is_vc in _VC_BADGE_STYLES else "Unknown"
    style = _VC_BADGE_STYLES[key]
    label = "VC Backed" if key == "Yes" else ("Not VC" if key == "No" else "VC Unknown")
    return f'<span style="{style}">{label}</span>'


def _row(label: str, value: str, even: bool = False) -> str:
    """Return a two-cell HTML table row with appropriate inline styles."""
    lbl_style = _TD_EVEN_LABEL_STYLE if even else _TD_LABEL_STYLE
    val_style = _TD_EVEN_STYLE if even else _TD_STYLE
    return (
        f'<tr><td style="{lbl_style}">{escape(label)}</td>'
        f'<td style="{val_style}">{escape(value)}</td></tr>'
    )


def _card(filing: dict) -> str:
    """
    Render a single filing as an HTML card with all extracted fields.

    Fields rendered:
    - Status badge (S-1 / S-1/A / 424B4) at the top
    - Filing Type, IPO Date, Transfer Agent (normalized fallback),
      Legal Counsel, Dual-Listed, Lock-Up Duration, Lock-Up Expiry,
      Lock-Up Terms, Top 5%+ Shareholders, Shareholder Footnotes,
      Venture Backed

    Args:
        filing: Dict of filing data from the database.

    Returns:
        HTML string for the card.
    """
    name = escape(filing.get("company_name", "Unknown"))
    cik = escape(filing.get("cik", ""))
    date_filed = escape(filing.get("filing_date", ""))
    acc = escape(filing.get("accession_number", ""))
    doc_priority = filing.get("document_priority") or filing.get("filing_type") or "S-1"

    edgar_url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&CIK={cik}&type=S-1&dateb=&owner=include&count=10"
    )

    # Status badge
    status_html = _status_badge(doc_priority)

    # VC badge — prefer validated value
    vc_raw = (
        filing.get("is_venture_backed_validated")
        or filing.get("is_venture_backed")
        or "Unknown"
    )
    vc_badge = _vc_badge(vc_raw)

    # Transfer agent — prefer normalized
    transfer_agent = (
        filing.get("transfer_agent_normalized")
        or filing.get("transfer_agent")
        or "N/A"
    )

    # IPO date — prospectus_date when available, else "Pending"
    ipo_date = filing.get("prospectus_date") or "Pending"

    # Lock-up duration
    lock_up_days = filing.get("lock_up_days")
    if lock_up_days is not None:
        lock_up_duration = f"{lock_up_days} days"
    else:
        lock_up_duration = filing.get("lock_up_expiration_date") or "N/A"

    # Lock-up expiry
    lock_up_expiry = filing.get("lock_up_expires_on") or "TBD"

    def val(key: str) -> str:
        return str(filing.get(key) or "N/A")

    rows_data = [
        ("Filing Type", doc_priority),
        ("IPO Date", ipo_date),
        ("Transfer Agent", transfer_agent),
        ("Legal Counsel", val("legal_counsel")),
        ("Dual-Listed / Share Classes", val("dually_listed")),
        ("Lock-Up Duration", lock_up_duration),
        ("Lock-Up Expiry Date", lock_up_expiry),
        ("Lock-Up Terms", val("lock_up_terms")),
        ("Top 5%+ Shareholders", val("top_5_percent_shareholders")),
        ("Shareholder Footnotes", val("top_5_percent_shareholders_footnotes")),
        ("Venture Backed", vc_raw),
    ]
    rows_html = "\n    ".join(
        _row(label, value, even=(i % 2 == 1))
        for i, (label, value) in enumerate(rows_data)
    )

    return f"""
<div style="{_CARD_STYLE}">
  <h3 style="{_CARD_H3_STYLE}">{name}{status_html}{vc_badge}</h3>
  <p style="{_META_STYLE}">
    Filed: {date_filed} &nbsp;|&nbsp; CIK: {cik} &nbsp;|&nbsp;
    Accession: {acc} &nbsp;|&nbsp;
    <a href="{edgar_url}" style="color:#4a90e2;">View on EDGAR</a>
  </p>
  <table style="{_TABLE_STYLE}">
    {rows_html}
  </table>
</div>"""


def _lockup_table(upcoming_lockups: list[dict]) -> str:
    """
    Render the upcoming lock-up expirations as an HTML table.

    Columns: Company Name, IPO Date, Lock-Up Expiry, Days Remaining.

    Args:
        upcoming_lockups: List of filing dicts with lock_up_expires_on set.

    Returns:
        HTML string for the lock-up section.
    """
    if not upcoming_lockups:
        no_msg_style = "color:#666;font-style:italic;margin:12px 0;"
        return f'<p style="{no_msg_style}">No lock-ups expiring in the next 30 days.</p>'

    today = date.today()
    rows_html_parts: list[str] = []
    for i, r in enumerate(upcoming_lockups):
        company = escape(r.get("company_name", "Unknown"))
        ipo_date = escape(r.get("prospectus_date") or "N/A")
        expiry = escape(r.get("lock_up_expires_on") or "TBD")

        # Calculate days remaining
        try:
            expiry_date = datetime.strptime(r["lock_up_expires_on"], "%Y-%m-%d").date()
            days_remaining = (expiry_date - today).days
            days_label = f"{days_remaining} day{'s' if days_remaining != 1 else ''}"
        except (KeyError, ValueError, TypeError):
            days_label = "N/A"

        td = _LOCKUP_TD_EVEN_STYLE if i % 2 == 1 else _LOCKUP_TD_STYLE
        rows_html_parts.append(
            f'<tr>'
            f'<td style="{td}">{company}</td>'
            f'<td style="{td}">{ipo_date}</td>'
            f'<td style="{td}">{expiry}</td>'
            f'<td style="{td}">{escape(days_label)}</td>'
            f'</tr>'
        )

    rows_html = "\n    ".join(rows_html_parts)
    return f"""<table style="{_LOCKUP_TABLE_STYLE}">
  <thead>
    <tr>
      <th style="{_LOCKUP_TH_STYLE}">Company Name</th>
      <th style="{_LOCKUP_TH_STYLE}">IPO Date</th>
      <th style="{_LOCKUP_TH_STYLE}">Lock-Up Expiry</th>
      <th style="{_LOCKUP_TH_STYLE}">Days Remaining</th>
    </tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>"""


# ---------------------------------------------------------------------------
# Public formatters
# ---------------------------------------------------------------------------

def format_html_email(
    filings: list[dict],
    week_start: str,
    week_end: str,
    upcoming_lockups: list[dict] | None = None,
) -> str:
    """
    Render the full weekly alert as an HTML email string.

    All styles are inlined on each element; no <style> block or external
    stylesheets are used so the output is safe for all major email clients.

    Args:
        filings:          List of filing dicts for the week.
        week_start:       YYYY-MM-DD start of the report period.
        week_end:         YYYY-MM-DD end of the report period.
        upcoming_lockups: Optional list of filings with lock-ups expiring
                          in the next 30 days (from get_upcoming_lockups).

    Returns:
        Complete HTML document as a string.
    """
    if not filings:
        body = (
            f'<p style="color:#666;">No S-1 filings were found for the week of '
            f'{escape(week_start)} to {escape(week_end)}.</p>'
        )
    else:
        cards = "\n".join(_card(f) for f in filings)
        count = len(filings)
        body = (
            f'<p><strong>{count} S-1 filing{"s" if count != 1 else ""}</strong> '
            f'found for the week of <strong>{escape(week_start)}</strong> '
            f'through <strong>{escape(week_end)}</strong>.</p>\n{cards}'
        )

    # Upcoming lock-up expirations section
    lockup_section = f"""
  <h2 style="{_SECTION_H2_STYLE}">Upcoming Lock-Up Expirations</h2>
  {_lockup_table(upcoming_lockups or [])}"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"></head>
<body style="{_BODY_STYLE}">
  <h2 style="{_H2_STYLE}">Weekly IPO S-1 Alert</h2>
  {body}
  {lockup_section}
  <div style="{_FOOTER_STYLE}">
    Data sourced from SEC EDGAR. Extracted by Claude AI &mdash; always verify with the
    original filing before acting on this information.
  </div>
</body>
</html>"""


def format_plain_email(
    filings: list[dict],
    week_start: str,
    week_end: str,
    upcoming_lockups: list[dict] | None = None,
) -> str:
    """
    Render the weekly alert as a plain-text email string.

    Includes all extracted fields and an upcoming lock-up expirations section.

    Args:
        filings:          List of filing dicts for the week.
        week_start:       YYYY-MM-DD start of the report period.
        week_end:         YYYY-MM-DD end of the report period.
        upcoming_lockups: Optional list of filings with lock-ups expiring
                          in the next 30 days.

    Returns:
        Plain-text email body as a string.
    """
    today = date.today()

    lines = [
        f"Weekly IPO S-1 Alert — {week_start} to {week_end}",
        f"{len(filings)} filing(s) found",
        "=" * 60,
    ]
    for f in filings:
        doc_priority = f.get("document_priority") or f.get("filing_type") or "S-1"
        status_label = _STATUS_LABELS.get(doc_priority, doc_priority)

        transfer_agent = (
            f.get("transfer_agent_normalized")
            or f.get("transfer_agent")
            or "N/A"
        )
        vc_value = (
            f.get("is_venture_backed_validated")
            or f.get("is_venture_backed")
            or "Unknown"
        )
        ipo_date = f.get("prospectus_date") or "Pending"

        lock_up_days = f.get("lock_up_days")
        lock_up_duration = (
            f"{lock_up_days} days" if lock_up_days is not None
            else (f.get("lock_up_expiration_date") or "N/A")
        )
        lock_up_expiry = f.get("lock_up_expires_on") or "TBD"

        lines += [
            "",
            f"Company:              {f.get('company_name')}",
            f"Status:               {status_label}",
            f"Filed:                {f.get('filing_date')}",
            f"Filing Type:          {doc_priority}",
            f"IPO Date:             {ipo_date}",
            f"Transfer Agent:       {transfer_agent}",
            f"Legal Counsel:        {f.get('legal_counsel')}",
            f"Dual-Listed:          {f.get('dually_listed')}",
            f"Lock-Up Duration:     {lock_up_duration}",
            f"Lock-Up Expiry Date:  {lock_up_expiry}",
            f"Lock-Up Terms:        {f.get('lock_up_terms')}",
            f"Top 5%+ Holders:      {f.get('top_5_percent_shareholders')}",
            f"Shareholder Notes:    {f.get('top_5_percent_shareholders_footnotes')}",
            f"VC Backed:            {vc_value}",
            f"EDGAR: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={f.get('cik')}&type=S-1",
            "-" * 60,
        ]

    # Upcoming lock-up expirations section
    lines += [
        "",
        "=" * 60,
        "UPCOMING LOCK-UP EXPIRATIONS (next 30 days)",
        "=" * 60,
    ]
    lockups = upcoming_lockups or []
    if not lockups:
        lines.append("No lock-ups expiring in the next 30 days.")
    else:
        lines.append(f"{'Company':<38}  {'IPO Date':<12}  {'Expiry':<12}  Days Remaining")
        lines.append("-" * 80)
        for r in lockups:
            company = (r.get("company_name") or "Unknown")[:38]
            ipo_dt = r.get("prospectus_date") or "N/A"
            expiry = r.get("lock_up_expires_on") or "TBD"
            try:
                expiry_date = datetime.strptime(r["lock_up_expires_on"], "%Y-%m-%d").date()
                days_remaining = str((expiry_date - today).days)
            except (KeyError, ValueError, TypeError):
                days_remaining = "N/A"
            lines.append(f"{company:<38}  {ipo_dt:<12}  {expiry:<12}  {days_remaining}")

    lines.append("\nData from SEC EDGAR; extracted by Claude AI. Verify before use.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_email(
    filings: list[dict],
    week_start: str,
    week_end: str,
    upcoming_lockups: list[dict] | None = None,
    test_mode: bool = False,
) -> bool:
    """
    Format and send the weekly alert email via Gmail SMTP.

    Sends both a plain-text and an HTML part (multipart/alternative).
    RECIPIENT_EMAIL in .env may be comma-separated; all addresses receive
    the email.

    Args:
        filings:          List of filing dicts for the week.
        week_start:       YYYY-MM-DD start of the report period.
        week_end:         YYYY-MM-DD end of the report period.
        upcoming_lockups: Optional list of dicts for upcoming lock-up
                          expirations (from get_upcoming_lockups).
        test_mode:        If True, prepends "[TEST]" to the subject line.

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    if not GMAIL_APP_PASSWORD:
        print("[Email] GMAIL_APP_PASSWORD not set — skipping send.")
        return False

    subject_prefix = "[TEST] " if test_mode else ""
    count = len(filings)
    subject = (
        f"{subject_prefix}Weekly IPO Alert: {count} S-1 filing{'s' if count != 1 else ''}"
        f" — week of {week_start}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(RECIPIENT_EMAILS)

    msg.attach(
        MIMEText(
            format_plain_email(filings, week_start, week_end, upcoming_lockups),
            "plain",
        )
    )
    msg.attach(
        MIMEText(
            format_html_email(filings, week_start, week_end, upcoming_lockups),
            "html",
        )
    )

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, RECIPIENT_EMAILS, msg.as_string())
        print(f"[Email] Sent to {', '.join(RECIPIENT_EMAILS)}: {subject}")
        return True
    except Exception as e:
        print(f"[Email] Failed to send: {e}")
        return False

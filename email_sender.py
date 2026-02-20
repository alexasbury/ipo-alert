"""
Format and send the weekly IPO S-1 alert email via Gmail SMTP.
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

GMAIL_USER = os.environ.get("GMAIL_USER", "alexanderasbury@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "alexanderasbury@gmail.com")


# ---------------------------------------------------------------------------
# HTML formatting
# ---------------------------------------------------------------------------

_STYLES = """
body { font-family: Arial, Helvetica, sans-serif; color: #222; max-width: 860px;
       margin: 0 auto; padding: 24px; background: #f4f6f9; }
h2   { color: #1a1a2e; border-bottom: 3px solid #4a90e2; padding-bottom: 8px; }
.card { background: #fff; border: 1px solid #dde3ec; border-radius: 10px;
        padding: 22px; margin-bottom: 24px; box-shadow: 0 2px 6px rgba(0,0,0,.06); }
.card h3 { margin: 0 0 4px; color: #1a1a2e; font-size: 18px; }
.meta { color: #666; font-size: 12px; margin-bottom: 14px; }
table { width: 100%; border-collapse: collapse; }
tr:nth-child(even) td { background: #f0f5ff; }
td { padding: 9px 12px; vertical-align: top; font-size: 13px;
     border-bottom: 1px solid #e8edf5; }
td:first-child { font-weight: 600; color: #444; width: 210px; white-space: nowrap; }
.badge { display: inline-block; padding: 3px 8px; border-radius: 4px;
         font-size: 11px; font-weight: 700; color: #fff; margin-left: 6px; }
.vc-yes   { background: #2e7d32; }
.vc-no    { background: #757575; }
.vc-unk   { background: #e65100; }
.footer   { color: #999; font-size: 11px; margin-top: 20px; border-top: 1px solid #dde3ec;
            padding-top: 12px; }
"""


def _vc_badge(is_vc: str) -> str:
    if is_vc == "Yes":
        return '<span class="badge vc-yes">VC Backed</span>'
    if is_vc == "No":
        return '<span class="badge vc-no">Not VC</span>'
    return '<span class="badge vc-unk">VC Unknown</span>'


def _card(filing: dict) -> str:
    name = escape(filing.get("company_name", "Unknown"))
    cik = escape(filing.get("cik", ""))
    date = escape(filing.get("filing_date", ""))
    acc = escape(filing.get("accession_number", ""))
    edgar_url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&CIK={cik}&type=S-1&dateb=&owner=include&count=10"
    )
    vc_badge = _vc_badge(filing.get("is_venture_backed", "Unknown"))

    def row(label: str, key: str) -> str:
        value = escape(str(filing.get(key) or "N/A"))
        return f"<tr><td>{label}</td><td>{value}</td></tr>"

    return f"""
<div class="card">
  <h3>{name}{vc_badge}</h3>
  <p class="meta">
    Filed: {date} &nbsp;|&nbsp; CIK: {cik} &nbsp;|&nbsp;
    Accession: {acc} &nbsp;|&nbsp;
    <a href="{edgar_url}" style="color:#4a90e2;">View on EDGAR</a>
  </p>
  <table>
    {row("Transfer Agent", "transfer_agent")}
    {row("Legal Counsel", "legal_counsel")}
    {row("Share Classes", "dually_listed")}
    {row("Lock-Up Date", "lock_up_date")}
    {row("Lock-Up Expiration", "lock_up_expiration_date")}
    {row("Lock-Up Terms", "lock_up_terms")}
    {row("Top 5%+ Shareholders", "top_5_percent_shareholders")}
    {row("Shareholder Footnotes", "top_5_percent_shareholders_footnotes")}
    {row("Venture Backed", "is_venture_backed")}
  </table>
</div>"""


def format_html_email(filings: list[dict], week_start: str, week_end: str) -> str:
    if not filings:
        body = f"<p>No S-1 filings were found for the week of {week_start} to {week_end}.</p>"
    else:
        cards = "\n".join(_card(f) for f in filings)
        count = len(filings)
        body = f"<p><strong>{count} S-1 filing{'s' if count != 1 else ''}</strong> found for the week of <strong>{week_start}</strong> through <strong>{week_end}</strong>.</p>\n{cards}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><style>{_STYLES}</style></head>
<body>
  <h2>Weekly IPO S-1 Alert</h2>
  {body}
  <div class="footer">
    Data sourced from SEC EDGAR. Extracted by Claude AI — always verify with the
    original filing before acting on this information.
  </div>
</body>
</html>"""


def format_plain_email(filings: list[dict], week_start: str, week_end: str) -> str:
    lines = [
        f"Weekly IPO S-1 Alert — {week_start} to {week_end}",
        f"{len(filings)} filing(s) found",
        "=" * 60,
    ]
    for f in filings:
        lines += [
            "",
            f"Company:       {f.get('company_name')}",
            f"Filed:         {f.get('filing_date')}",
            f"Transfer Agent: {f.get('transfer_agent')}",
            f"Legal Counsel: {f.get('legal_counsel')}",
            f"Share Classes: {f.get('dually_listed')}",
            f"Lock-Up Terms: {f.get('lock_up_terms')}",
            f"Top 5%+ Holders: {f.get('top_5_percent_shareholders')}",
            f"VC Backed:     {f.get('is_venture_backed')}",
            f"EDGAR: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={f.get('cik')}&type=S-1",
            "-" * 60,
        ]
    lines.append("\nData from SEC EDGAR; extracted by Claude AI. Verify before use.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_email(
    filings: list[dict],
    week_start: str,
    week_end: str,
    test_mode: bool = False,
) -> bool:
    """Send the formatted alert email. Returns True on success."""
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
    msg["To"] = RECIPIENT_EMAIL

    msg.attach(MIMEText(format_plain_email(filings, week_start, week_end), "plain"))
    msg.attach(MIMEText(format_html_email(filings, week_start, week_end), "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
        print(f"[Email] Sent to {RECIPIENT_EMAIL}: {subject}")
        return True
    except Exception as e:
        print(f"[Email] Failed to send: {e}")
        return False

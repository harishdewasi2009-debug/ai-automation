"""Sends ONLY drafts you have approved. Uses your own SMTP mailbox (Gmail, Outlook, etc.)."""
import json
import smtplib
import ssl
import time
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from config import OUTPUT_DIR, settings

LOG_FILE = OUTPUT_DIR / "sent_log.json"
OPTOUT_FILE = OUTPUT_DIR / "opt_out.txt"   # one email address per line - never emailed


def configured() -> bool:
    return all([settings.smtp_host, settings.smtp_user, settings.smtp_password, settings.smtp_from])


def _log() -> dict:
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _opt_outs() -> set:
    if not OPTOUT_FILE.exists():
        return set()
    return {l.strip().lower() for l in OPTOUT_FILE.read_text(encoding="utf-8").splitlines() if l.strip()}


def total_sent() -> int:
    return len(_log())


def _replies() -> dict:
    try:
        return json.loads((OUTPUT_DIR / "replies.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def split_draft(draft: str) -> tuple[str, str]:
    subject, body = "", draft
    if draft.lower().startswith("subject:"):
        first, _, rest = draft.partition("\n")
        subject, body = first[8:].strip(), rest.strip()
    return subject, body


def can_send(to: str, followup: bool = False) -> str:
    """Return '' if OK, otherwise the reason it must not be sent."""
    to = to.strip().lower()
    if not configured():
        return "SMTP not configured in .env"
    if to in _opt_outs():
        return "address is on the opt-out list"
    entry = _log().get(to)
    if not followup:
        return "already emailed before" if entry else ""
    if not entry:
        return "no first email was sent to this address"
    if to in _replies():
        return "they already replied"
    if entry.get("followups", 0) >= settings.max_followups:
        return f"already followed up {settings.max_followups} times"
    days = (date.today() - datetime.fromisoformat(entry["date"]).date()).days
    if days < settings.followup_days:
        return f"wait {settings.followup_days - days} more day(s) before following up"
    return ""


def send(to: str, draft: str, followup: bool = False) -> None:
    reason = can_send(to, followup)
    if reason:
        raise RuntimeError(reason)
    subject, body = split_draft(draft)
    footer = (f"\n\n--\n{settings.postal_info}\n"
              f"If you do not wish to receive further emails, reply \"unsubscribe\" and we will remove you.")
    msg = EmailMessage()
    msg["From"] = formataddr((settings.smtp_from_name, settings.smtp_from))
    msg["To"] = to
    msg["Subject"] = subject or "Business enquiry"
    msg["Message-ID"] = make_msgid()
    msg["Reply-To"] = settings.smtp_from
    msg.set_content(body + footer)
    ctx = ssl.create_default_context()
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, 465, context=ctx, timeout=30) as s:
            s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    log = _log()
    k = to.strip().lower()
    if followup:
        log[k]["followups"] = log[k].get("followups", 0) + 1
        log[k]["date"] = date.today().isoformat()
    else:
        log[k] = {"date": date.today().isoformat(), "subject": subject, "followups": 0}
    LOG_FILE.write_text(json.dumps(log, indent=1), encoding="utf-8")
    time.sleep(settings.send_delay_seconds)  # slow pace protects your mailbox reputation

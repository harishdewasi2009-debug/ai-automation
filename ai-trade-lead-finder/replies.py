"""Reads your inbox (IMAP), finds replies from people you emailed, and honours opt-out requests."""
import email
import imaplib
import json
import re
from datetime import datetime
from email.utils import parseaddr

from config import OUTPUT_DIR, settings
import mailer

REPLIES_FILE = OUTPUT_DIR / "replies.json"
OPTOUT_RE = re.compile(
    r"unsubscribe|remove me|remove us|stop (emailing|sending|contacting)|do not (contact|email)|don'?t (contact|email)", re.I)


def _imap_host() -> str:
    if settings.imap_host:
        return settings.imap_host
    return settings.smtp_host.replace("smtp.", "imap.", 1)


def load() -> dict:
    try:
        return json.loads(REPLIES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _body(msg) -> str:
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                break
    else:
        text = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")
    lines = []
    for ln in text.splitlines():           # drop quoted history
        if ln.startswith(">") or re.match(r"^On .* wrote:", ln):
            break
        lines.append(ln)
    return "\n".join(lines).strip()


def check() -> tuple[int, int]:
    """Return (new replies found, new opt-outs). Raises on login problems."""
    sent = mailer._log()
    if not sent:
        return 0, 0
    since = min(datetime.fromisoformat(v["date"]) for v in sent.values()).strftime("%d-%b-%Y")
    found, optouts = load(), 0
    new = 0
    M = imaplib.IMAP4_SSL(_imap_host())
    try:
        M.login(settings.smtp_user, settings.smtp_password)
        M.select("INBOX", readonly=True)
        _, data = M.search(None, f'(SINCE "{since}")')
        for num in data[0].split()[-500:]:
            _, d = M.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(d[0][1])
            sender = parseaddr(msg.get("From", ""))[1].lower()
            if sender not in sent or sender in found:
                continue
            body = _body(msg)
            wants_out = bool(OPTOUT_RE.search(body[:600]))
            found[sender] = {"date": msg.get("Date", ""), "subject": msg.get("Subject", ""),
                             "snippet": body[:400], "opt_out": wants_out}
            new += 1
            if wants_out:
                with open(mailer.OPTOUT_FILE, "a", encoding="utf-8") as f:
                    f.write(sender + "\n")
                optouts += 1
    finally:
        try:
            M.logout()
        except Exception:
            pass
    REPLIES_FILE.write_text(json.dumps(found, indent=1), encoding="utf-8")
    return new, optouts

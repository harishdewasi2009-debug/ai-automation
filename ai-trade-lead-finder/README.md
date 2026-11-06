# AI Trade Lead Finder (MVP v1)

Upload an Excel list -> find official websites -> extract public emails/phones (with source URL)
-> export to Excel -> draft emails for your approval. **Emails are sent only after you approve each draft.**

## Setup (Windows, PowerShell)
```
cd ai-trade-lead-finder
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env          # paste your Gemini, DeepSeek and Tavily keys
python make_sample_input.py   # then edit sample_input.xlsx with 10 companies you know
streamlit run app.py
```
If PowerShell blocks activation: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## How it works
1. Gemini identifies the company; Tavily finds candidate sites.
2. Gemini AND DeepSeek each pick the official site; if they disagree the row is flagged "Needs manual review".
3. The crawler reads the homepage + contact/about pages (respects robots.txt) and records the page each
   email/phone came from.
4. DeepSeek ranks and structures the contacts. Code then discards anything not actually found on the page,
   so nothing can be invented.
5. Results are saved to `output/cache.json` after every company - restarting never repeats finished ones.

## Notes
- Check the first 10 results by hand before running more.
- A found email is not proof the inbox works. Only email addresses a company publishes for business use,
  and follow anti-spam/privacy rules (include unsubscribe, honour opt-outs).
- Sites that need JavaScript to show contacts will come back empty; Playwright support is a later upgrade.

## Sending (v1.1)
- Fill the `SMTP_` lines in `.env` (Gmail needs an App Password).
- Only drafts you click **Approve** on can be sent. Use "Send this email now" or "Send all approved".
- Safety built in: an unsubscribe line + your company details are added to every email; nobody gets a second *first* email;
  addresses in `output/opt_out.txt` are never emailed; a short pause between sends. There is no daily cap.

## Replies and follow-ups
- "Check inbox for replies" reads your mailbox (IMAP, same login as SMTP). Anyone who writes "unsubscribe" / "remove me" is added to the opt-out list automatically.
- After `FOLLOWUP_AFTER_DAYS` (default 5) with no reply, "Draft follow-ups" writes a short follow-up. It still needs your Approve. Max `MAX_FOLLOWUPS` (default 2) per person.

## Password
Set `APP_PASSWORD` in `.env` (or Render environment). The app asks for it before showing anything.

## JavaScript websites
If the normal crawl finds no email, the page is re-read in a real browser. One-time setup: `playwright install chromium`.
On Render add that to the build command: `pip install -r requirements.txt && playwright install chromium`.

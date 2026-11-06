import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st

import agent
import excel_io
import hmac
import mailer
import replies
from config import CACHE_FILE, settings

st.set_page_config(page_title="AI Trade Lead Finder", layout="wide")
st.title("AI Trade Lead Finder")

# ---------- password gate ----------
if settings.app_password and not st.session_state.get("auth"):
    pw = st.text_input("Password", type="password")
    if pw:
        if hmac.compare_digest(pw, settings.app_password):
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()

# ---------- helpers ----------
def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache: dict):
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def key(c) -> str:
    return f"{c['name'].lower()}|{c['type'].lower()}"


if "rows" not in st.session_state:
    st.session_state.rows = []

# ---------- sidebar ----------
with st.sidebar:
    st.header("Settings")
    st.write("Gemini key:", "✅" if settings.gemini_key else "❌ missing")
    st.write("DeepSeek key:", "✅" if settings.deepseek_key else "❌ missing")
    st.write("Search (Tavily) key:", "✅" if settings.tavily_key else "❌ missing")
    st.caption("Keys are read from your local .env file.")
    if not settings.app_password:
        st.warning("No APP_PASSWORD set - anyone with the link can use this app. Set one before hosting online.")
    workers = st.slider("Companies researched in parallel", 1, 8, settings.max_workers)
    product = st.text_input("Product for email drafts", "EN590 10 PPM petroleum products")
    signature = st.text_area("Email signature", "Best regards,\nTrade Business Development Team", height=80)
    if st.button("Clear saved results"):
        CACHE_FILE.unlink(missing_ok=True)
        st.session_state.rows = []
        st.rerun()

# ---------- 1. upload ----------
st.subheader("1. Upload companies")
up = st.file_uploader("Excel file with columns: Company name, Type, Country", type=["xlsx"])
companies = []
if up:
    try:
        companies, warns = excel_io.read_input(up)
        st.success(f"{len(companies)} companies loaded.")
        for w in warns[:5]:
            st.caption(w)
        st.dataframe(pd.DataFrame(companies), use_container_width=True, height=200)
    except Exception as e:
        st.error(str(e))

# ---------- 2. research ----------
st.subheader("2. Research")
missing = [n for n, k in [("Gemini", settings.gemini_key), ("DeepSeek", settings.deepseek_key)] if not k]
if not settings.tavily_key:
    st.warning("TAVILY_API_KEY is missing - website search cannot run.")
if missing:
    st.info(f"No key for {', '.join(missing)}: the other model will do both jobs (no cross-checking).")

limit = st.number_input("Only research the first N companies (use 10 for your first test)", 1, 1000, 10)
if st.button("Start research", type="primary", disabled=not (companies and settings.tavily_key)):
    cache = load_cache()
    todo = [c for c in companies[: int(limit)] if key(c) not in cache]
    done_rows = {key(c): cache[key(c)] for c in companies[: int(limit)] if key(c) in cache}
    if done_rows:
        st.caption(f"{len(done_rows)} companies reused from saved results (not researched again).")
    bar = st.progress(0.0, text="Starting...")
    total = len(todo)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(agent.research_company, c["name"], c["type"], c["country"]): c for c in todo}
        for i, fut in enumerate(as_completed(futures), start=1):
            c = futures[fut]
            try:
                row = fut.result()
            except Exception as e:
                row = agent._empty(c["name"], c["type"], c["country"])
                row["Verification status"] = "Failed"
                row["Notes"] = str(e)
            cache[key(c)] = row
            done_rows[key(c)] = row
            save_cache(cache)
            bar.progress(i / total, text=f"{i}/{total}: {c['name']}")
    bar.empty()
    st.session_state.rows = [done_rows[key(c)] for c in companies[: int(limit)] if key(c) in done_rows]

# ---------- results ----------
rows = st.session_state.rows
if rows:
    df = pd.DataFrame(rows)
    st.subheader("3. Results")
    a, b, c_ = st.columns(3)
    a.metric("Researched", len(df))
    b.metric("With email", int((df["Business email"] != "").sum()))
    c_.metric("Need review / failed", int(df["Verification status"].isin(["Needs manual review", "Failed", "No contact found"]).sum()))
    st.dataframe(df.drop(columns=["Email draft", "_followup"], errors="ignore"), use_container_width=True)

    # ---------- 4. drafts + approval ----------
    st.subheader("4. Email drafts and approval")
    st.caption("Nothing is sent until you click Approve on a draft. Only Approved drafts can be sent.")
    if st.button("Generate drafts for companies with an email"):
        prog = st.progress(0.0)
        targets = [r for r in rows if r["Business email"] and not r["Email draft"]]
        for i, r in enumerate(targets, start=1):
            try:
                d = agent.draft_email(r, product, signature)
                r["Email draft"] = f"Subject: {d['subject']}\n\n{d['body']}"
                r["Notes"] = (r["Notes"] + "; " if r["Notes"] else "") + f"Draft review: {d['review']}"
                r["Email sending status"] = "Pending approval"
            except Exception as e:
                r["Notes"] = (r["Notes"] + "; " if r["Notes"] else "") + f"Draft failed: {e}"
            prog.progress(i / max(len(targets), 1))
        cache = load_cache()
        for r in rows:
            cache[f"{r['Company name'].lower()}|{r['Buyer / Supplier'].lower()}"] = r
        save_cache(cache)
        st.rerun()

    drafts = [r for r in rows if r["Email draft"]]
    for r in drafts:
        k = f"{r['Company name']}|{r['Buyer / Supplier']}"
        with st.expander(f"{r['Company name']} - {r['Business email']} - {r['Email sending status']}"):
            r["Email draft"] = st.text_area("Draft (editable)", r["Email draft"], height=220, key="t" + k)
            c1, c2 = st.columns(2)
            if c1.button("Approve", key="a" + k):
                r["Email sending status"] = "Approved"
                st.rerun()
            if c2.button("Reject", key="r" + k):
                r["Email sending status"] = "Rejected"
                st.rerun()
            if r["Email sending status"] == "Approved":
                why = mailer.can_send(r["Business email"], bool(r.get("_followup")))
                if why:
                    st.caption(f"Cannot send: {why}")
                elif st.button("Send this email now", key="s" + k):
                    try:
                        mailer.send(r["Business email"], r["Email draft"], bool(r.get("_followup")))
                        r["Email sending status"] = "Sent"
                        r["_followup"] = False
                    except Exception as e:
                        r["Email sending status"] = "Send failed"
                        r["Notes"] = (r["Notes"] + "; " if r["Notes"] else "") + f"Send error: {e}"
                    cache = load_cache()
                    cache[f"{r['Company name'].lower()}|{r['Buyer / Supplier'].lower()}"] = r
                    save_cache(cache)
                    st.rerun()

    approved = [r for r in rows if r["Email sending status"] == "Approved" and not mailer.can_send(r["Business email"], bool(r.get("_followup")))]
    st.write(f"Approved and ready to send: **{len(approved)}**  |  total sent: {mailer.total_sent()}")
    if not mailer.configured():
        st.warning("Fill in the SMTP_ settings in .env to enable sending.")
    elif approved and st.button(f"Send all {len(approved)} approved emails"):
        bar = st.progress(0.0)
        for i, r in enumerate(approved, start=1):
            try:
                mailer.send(r["Business email"], r["Email draft"], bool(r.get("_followup")))
                r["Email sending status"] = "Sent"
                r["_followup"] = False
            except Exception as e:
                r["Email sending status"] = "Send failed"
                r["Notes"] = (r["Notes"] + "; " if r["Notes"] else "") + f"Send error: {e}"
            bar.progress(i / len(approved))
        cache = load_cache()
        for r in rows:
            cache[f"{r['Company name'].lower()}|{r['Buyer / Supplier'].lower()}"] = r
        save_cache(cache)
        st.rerun()

    # ---------- replies + follow-ups ----------
    st.subheader("5. Replies and follow-ups")
    if not mailer.configured():
        st.caption("Set the SMTP_ settings in .env to read replies.")
    else:
        if st.button("Check inbox for replies"):
            try:
                n, o = replies.check()
                st.success(f"{n} new replies found. {o} opt-out request(s) added to the do-not-email list.")
            except Exception as e:
                st.error(f"Could not read inbox: {e}")
        rep = replies.load()
        for em, v in rep.items():
            who = next((r["Company name"] for r in rows if r["Business email"].lower() == em), em)
            with st.expander(f"{'🚫 ' if v['opt_out'] else '💬 '}{who} - {v['subject']}"):
                st.write(v["snippet"] or "(empty)")
        log = mailer._log()
        waiting = [r for r in rows if r["Email sending status"] == "Sent"
                   and r["Business email"].lower() in log and r["Business email"].lower() not in rep
                   and not mailer.can_send(r["Business email"], True)]
        st.write(f"Replied: **{len(rep)}**  |  Ready for a follow-up: **{len(waiting)}**")
        if waiting and st.button(f"Draft follow-ups for {len(waiting)} companies"):
            for r in waiting:
                n = log[r["Business email"].lower()].get("followups", 0) + 1
                try:
                    d = agent.draft_followup(r, product, signature, n)
                    r["Email draft"] = f"Subject: {d['subject']}\n\n{d['body']}"
                    r["Email sending status"] = "Pending approval"
                    r["_followup"] = True
                except Exception as e:
                    r["Notes"] = (r["Notes"] + "; " if r["Notes"] else "") + f"Follow-up draft failed: {e}"
            cache = load_cache()
            for r in rows:
                cache[f"{r['Company name'].lower()}|{r['Buyer / Supplier'].lower()}"] = r
            save_cache(cache)
            st.rerun()
        st.caption("Follow-up drafts appear in section 4 and still need your Approve before sending.")

    # ---------- export ----------
    st.subheader("6. Export")
    st.download_button(
        "Download Excel", excel_io.export_excel(rows), "trade_leads.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

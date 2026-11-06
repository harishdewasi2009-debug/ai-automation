"""Research pipeline for one company:
Gemini identifies -> search -> Gemini + DeepSeek both pick the website -> crawl -> DeepSeek structures contacts.
Emails/phones are only kept if the crawler actually saw them on a page (no invented data).
"""
import re
from datetime import date
from urllib.parse import urlparse

import crawler
import llm
from config import settings
from search import website_candidates

COLUMNS = [
    "Company name", "Buyer / Supplier", "Country", "Official website", "Business email",
    "Contact number", "Contact person", "Company category", "Website source", "Email source",
    "Phone source", "Verification status", "Research date", "Email draft", "Email sending status",
    "All emails found", "All phones found", "Notes",
]


def _norm_digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _pick_prompt(name, ctype, country, industry, candidates):
    lines = "\n".join(f"{i}. {c['title']} | {c['url']} | {c['snippet']}" for i, c in enumerate(candidates))
    return f"""Find the OFFICIAL website of this company.
Company: {name}
Type: {ctype}
Country: {country or 'unknown'}
Industry: {industry or 'unknown'}

Candidates:
{lines}

Rules: choose only an index from the list. Choose the company's own website, not a directory, news site or
a different company with a similar name. If none clearly matches, use null.
Return JSON: {{"index": <int or null>, "confidence": "high|medium|low", "reason": "<short>"}}"""


def _empty(name, ctype, country):
    row = {c: "" for c in COLUMNS}
    row.update({
        "Company name": name, "Buyer / Supplier": ctype, "Country": country,
        "Research date": date.today().isoformat(), "Email sending status": "Not drafted",
    })
    return row


def research_company(name: str, ctype: str, country: str) -> dict:
    row = _empty(name, ctype, country)
    notes = []

    # 1. Identify (Gemini)
    try:
        ident = llm.ask("gemini", f"""Company name: {name}
Stated type: {ctype}
Stated country: {country or 'not given'}
Based on the name only, return JSON: {{"country": "...", "industry": "...",
"role": "buyer|supplier|refinery|trader|intermediary|unknown", "search_hint": "short extra words for a web search"}}.
If you do not recognise the company, say "unknown" - do not guess.""")
    except Exception as e:
        ident = {}
        notes.append(f"Identify step failed: {e}")
    country = country or (ident.get("country") if ident.get("country") != "unknown" else "") or ""
    row["Country"] = country
    industry = ident.get("industry", "")
    row["Company category"] = ident.get("role", "") if ident.get("role") != "unknown" else ""

    # 2. Search
    queries = [f"{name} {country} official website".strip(), f"{name} {industry} {ident.get('search_hint', '')} contact".strip()]
    candidates = website_candidates(queries)
    if not candidates:
        row["Verification status"] = "Needs manual review"
        row["Notes"] = "; ".join(notes + ["No website candidates found"])
        return row

    # 3. Two models pick the website independently
    prompt = _pick_prompt(name, ctype, country, industry, candidates)
    picks = {}
    for provider in ("gemini", "deepseek"):
        try:
            picks[provider] = llm.ask(provider, prompt)
        except Exception as e:
            notes.append(f"{provider} website pick failed: {e}")
    idx_values = {p.get("index") for p in picks.values() if isinstance(p, dict)}
    # if only one key is configured both calls hit the same model; that is fine
    disagree = len(idx_values) > 1
    first = next(iter(picks.values()), {})
    idx = first.get("index")
    if idx is None or not isinstance(idx, int) or not 0 <= idx < len(candidates):
        row["Verification status"] = "Needs manual review"
        row["Notes"] = "; ".join(notes + ["No confident official website"])
        return row

    site_url = candidates[idx]["url"]
    parts = urlparse(site_url)
    website = f"{parts.scheme}://{parts.netloc}"
    row["Official website"] = website
    row["Website source"] = site_url
    confidence = first.get("confidence", "low")
    if disagree:
        notes.append("Gemini and DeepSeek chose different websites")

    # 4. Crawl
    crawled = crawler.crawl_site(website)
    if not crawled["pages"]:
        row["Verification status"] = "Needs manual review"
        row["Notes"] = "; ".join(notes + ["Website could not be read (blocked, offline or robots.txt)"])
        return row

    # 5. Structure with DeepSeek, then enforce "only what was really found"
    emails, phones = crawled["emails"], crawled["phones"]
    chosen_emails, chosen_phones, person = list(emails), list(phones), ""
    if emails or phones:
        try:
            s = llm.ask("deepseek", f"""Company: {name} ({ctype}). Website: {website}
Candidate emails found on the website: {list(emails)}
Candidate phones found on the website: {list(phones)}
Page text:
{crawled['text'][:6000]}

Return JSON: {{"emails": [ordered best-first business emails, chosen ONLY from the candidate list],
"phones": [ordered best-first, ONLY from the candidate list],
"contact_person": "name and title if explicitly published in the text, else empty string",
"category": "one short phrase describing what the company does"}}
Never invent or modify values. Exclude personal-looking addresses of unrelated people.""")
            chosen_emails = [e for e in s.get("emails", []) if e.lower() in emails] or chosen_emails
            valid_digits = {_norm_digits(p): p for p in phones}
            chosen_phones = [valid_digits[_norm_digits(p)] for p in s.get("phones", []) if _norm_digits(p) in valid_digits] or chosen_phones
            person = s.get("contact_person", "") or ""
            if s.get("category"):
                row["Company category"] = s["category"]
        except Exception as e:
            notes.append(f"Contact structuring failed (raw values kept): {e}")

    if chosen_emails:
        row["Business email"] = chosen_emails[0]
        row["Email source"] = emails[chosen_emails[0]]
    if chosen_phones:
        row["Contact number"] = chosen_phones[0]
        row["Phone source"] = phones[chosen_phones[0]]
    row["Contact person"] = person
    row["All emails found"] = "; ".join(chosen_emails)
    row["All phones found"] = "; ".join(chosen_phones)

    # 6. Verification status
    own_domain = _domain(website)
    email_on_domain = False
    if chosen_emails:
        ed = chosen_emails[0].split("@")[1].lower()
        email_on_domain = ed == own_domain or ed.endswith("." + own_domain) or own_domain.endswith("." + ed)
    if not chosen_emails and not chosen_phones:
        status = "No contact found"
    elif disagree or confidence == "low":
        status = "Needs manual review"
    elif confidence == "high" and (email_on_domain or not chosen_emails):
        status = "Website matched - contact published on site"
    else:
        status = "Needs manual review"
        if chosen_emails and not email_on_domain:
            notes.append("Email domain differs from website domain")
    row["Verification status"] = status
    row["Notes"] = "; ".join(notes)
    return row


def draft_email(row: dict, product: str, signature: str) -> dict:
    """Gemini writes the draft, DeepSeek reviews it. Returns {'subject','body','review'}."""
    role = "supplier" if "suppl" in row["Buyer / Supplier"].lower() else "buyer"
    d = llm.ask("gemini", f"""Write a short, polite, professional first-contact business email (max 120 words).
Recipient company: {row['Company name']} (a {role}), country: {row['Country'] or 'n/a'}.
Product: {product}.
{'Ask whether they can supply it and request their procedures, specifications and terms.' if role == 'supplier' else 'Ask whether they are currently buying it and invite them to share their requirements.'}
Do not make claims about prices, volumes or past dealings. Do not invent facts about the recipient.
Sign off with: {signature}
Return JSON: {{"subject": "...", "body": "..."}}""")
    try:
        rv = llm.ask("deepseek", f"""Review this outreach email for tone, accuracy and spam-like wording.
Subject: {d.get('subject')}
Body: {d.get('body')}
Return JSON: {{"ok": true/false, "issues": ["..."]}}""")
        review = "OK" if rv.get("ok") else "; ".join(rv.get("issues", [])) or "Check wording"
    except Exception as e:
        review = f"Review skipped: {e}"
    return {"subject": d.get("subject", ""), "body": d.get("body", ""), "review": review}


def draft_followup(row: dict, product: str, signature: str, n: int) -> dict:
    role = "supplier" if "suppl" in row["Buyer / Supplier"].lower() else "buyer"
    d = llm.ask("gemini", f"""Write a very short, polite follow-up email (max 70 words) to {row['Company name']} (a {role}).
We emailed them earlier about {product} and have not had a reply. This is follow-up number {n}.
Do not pressure them, do not invent facts, do not mention prices. Make it easy for them to say no.
Sign off with: {signature}
Return JSON: {{"subject": "...", "body": "..."}}""")
    return {"subject": d.get("subject", ""), "body": d.get("body", "")}

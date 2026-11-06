"""Polite crawler: reads a handful of public pages and pulls out emails and phone numbers."""
import re
from datetime import date
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from config import settings

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_PLUS_RE = re.compile(r"\+\d[\d\s().\-]{7,17}\d")
PHONE_LABEL_RE = re.compile(r"(?:tel|phone|mob|mobile|call|fax)\b[^\d+]{0,15}(\+?\d[\d\s().\-]{7,17}\d)", re.I)
BAD_EMAIL_PARTS = ("example.", "sentry", "wixpress", "yourdomain", "domain.com", "email.com")
BAD_EMAIL_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
LINK_KEYWORDS = ("contact", "kontakt", "about", "impressum", "team", "management", "company", "trading", "products")

_robots_cache: dict[str, RobotFileParser | None] = {}


def _client():
    return httpx.Client(
        headers={"User-Agent": settings.user_agent},
        timeout=settings.request_timeout,
        follow_redirects=True,
    )


def _allowed(client, url: str) -> bool:
    parts = urlparse(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots_cache:
        rp = RobotFileParser()
        try:
            r = client.get(base + "/robots.txt")
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
                _robots_cache[base] = rp
            else:
                _robots_cache[base] = None  # no robots.txt -> allowed
        except Exception:
            _robots_cache[base] = None
    rp = _robots_cache[base]
    return True if rp is None else rp.can_fetch(settings.user_agent, url)


def _clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if not 8 <= len(digits) <= 15:
        return None
    return re.sub(r"\s+", " ", raw).strip(" .-")


def _extract(soup, final_url: str, result: dict) -> str:
    """Pull emails/phones out of a parsed page into result; return the page text."""
    for a in soup.find_all("a", href=True):          # mailto: / tel: links are the most reliable signals
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            for e in EMAIL_RE.findall(href[7:].split("?")[0]):
                result["emails"].setdefault(e.lower(), final_url)
        elif href.lower().startswith("tel:"):
            p = _clean_phone(href[4:].replace("%20", " "))
            if p:
                result["phones"].setdefault(p, final_url)
    for s_ in soup(["script", "style", "noscript"]):
        s_.decompose()
    text = soup.get_text(" ", strip=True)
    for e in EMAIL_RE.findall(text):
        result["emails"].setdefault(e.lower(), final_url)
    for m in PHONE_LABEL_RE.findall(text) + PHONE_PLUS_RE.findall(text):
        p = _clean_phone(m)
        if p:
            result["phones"].setdefault(p, final_url)
    return text


def _js_fallback(result: dict) -> None:
    """Re-read the pages in a real browser when the plain fetch found no email (JavaScript sites)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=settings.user_agent)
            for url in result["pages"][: settings.max_pages_per_site]:
                try:
                    page.goto(url, timeout=25000, wait_until="networkidle")
                    soup = BeautifulSoup(page.content(), "html.parser")
                except Exception:
                    continue
                text = _extract(soup, url, result)
                result["text"] += f"\n[PAGE {url} (browser)]\n{text[:2500]}"
            browser.close()
    except Exception:
        pass  # browser not installed etc. - keep whatever the plain crawl found


def crawl_site(website: str) -> dict:
    """Return {'emails': {email: url}, 'phones': {phone: url}, 'text': str, 'pages': [urls]}."""
    result = {"emails": {}, "phones": {}, "text": "", "pages": []}
    with _client() as client:
        queue = [website]
        visited = set()
        while queue and len(visited) < settings.max_pages_per_site:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                if not _allowed(client, url):
                    continue
                r = client.get(url)
                if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                    continue
            except Exception:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            final_url = str(r.url)
            result["pages"].append(final_url)

            text = _extract(soup, final_url, result)

            if any(k in final_url.lower() for k in ("contact", "kontakt", "about", "impressum")) or len(visited) == 1:
                result["text"] += f"\n[PAGE {final_url}]\n{text[:2500]}"

            # queue relevant internal pages (from the homepage only)
            if len(visited) == 1:
                host = urlparse(final_url).netloc
                scored = []
                for a in soup.find_all("a", href=True):
                    full = urljoin(final_url, a["href"]).split("#")[0]
                    if urlparse(full).netloc != host or full in visited:
                        continue
                    label = (a.get_text(" ", strip=True) + " " + full).lower()
                    for i, k in enumerate(LINK_KEYWORDS):
                        if k in label:
                            scored.append((i, full))
                            break
                for _, link in sorted(scored):
                    if link not in queue:
                        queue.append(link)

    if not result["emails"] and settings.use_js_fallback and result["pages"]:
        _js_fallback(result)

    # filter junk emails
    result["emails"] = {
        e: u for e, u in result["emails"].items()
        if not e.endswith(BAD_EMAIL_EXT) and not any(b in e for b in BAD_EMAIL_PARTS)
    }
    result["collected_on"] = date.today().isoformat()
    return result

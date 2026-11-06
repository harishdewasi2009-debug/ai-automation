"""Website discovery through the Tavily search API."""
from urllib.parse import urlparse

import httpx

from config import settings

# Directories / social sites: useful for context but never "the official website"
BLOCKED_DOMAINS = {
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "wikipedia.org", "bloomberg.com", "dnb.com", "zoominfo.com", "crunchbase.com",
    "opencorporates.com", "alibaba.com", "made-in-china.com", "indiamart.com",
    "tradeindia.com", "globalsources.com", "yellowpages.com", "yelp.com", "reuters.com",
    "rocketreach.co", "apollo.io", "kompass.com", "europages.com", "tiktok.com",
}


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def search_web(query: str, max_results: int = 8) -> list[dict]:
    if not settings.tavily_key:
        raise RuntimeError("TAVILY_API_KEY is missing")
    r = httpx.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {settings.tavily_key}"},
        json={"query": query, "max_results": max_results, "search_depth": "basic"},
        timeout=30,
    )
    r.raise_for_status()
    return [
        {"title": x.get("title", ""), "url": x.get("url", ""), "snippet": (x.get("content") or "")[:300]}
        for x in r.json().get("results", [])
    ]


def website_candidates(queries: list[str]) -> list[dict]:
    """Run queries, drop directories/socials, keep one result per domain."""
    seen, out = set(), []
    for q in queries:
        try:
            results = search_web(q)
        except Exception:
            continue
        for item in results:
            d = _domain(item["url"])
            if not d or d in seen or any(d == b or d.endswith("." + b) for b in BLOCKED_DOMAINS):
                continue
            seen.add(d)
            out.append(item)
    return out[:10]

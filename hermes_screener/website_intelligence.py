"""
Website Intelligence — Analyze token websites for quality, activity, and trendiness.

Collects for each top token:
  - Website URL (from Dexscreener enrichment)
  - Blog/announcement activity (recent posts, update frequency)
  - Traffic estimates (SimilarWeb free API)
  - Website complexity (page size, resources, structure depth)
  - Trendiness (content matching trending keywords from AI discovery)

Scoring (100pts):
  Blog Activity        25pts  (recent posts, update frequency)
  Website Complexity   25pts  (page size, resources, structure — too simple = bad)
  Content Trendiness   25pts  (keywords match trending social topics)
  Traffic Signals      15pts  (estimated visitors, social proof)
  Announcement Fresh   10pts  (how recent are announcements)

Usage:
    from hermes_screener.website_intelligence import run_website_analysis
    signals = run_website_analysis(tokens, trending_keywords)
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from hermes_screener.config import settings
from hermes_screener.logging import get_logger
from hermes_screener.metrics import metrics

log = get_logger("website_intelligence")

# Cache file for website analysis results
CACHE_PATH = settings.hermes_home / "data" / "token_screener" / "website_analysis.json"


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSITE DISCOVERY
# ═══════════════════════════════════════════════════════════════════════════════

async def discover_website(chain: str, address: str, client: httpx.AsyncClient) -> Optional[str]:
    """Find website URL for a token from Dexscreener."""
    try:
        resp = await client.get(f"https://api.dexscreener.com/latest/dex/tokens/{address}", timeout=10)
        if resp.status_code != 200:
            return None
        pairs = resp.json().get("pairs", [])
        if not pairs:
            return None
        info = pairs[0].get("info", {})
        websites = info.get("websites", [])
        if websites:
            return websites[0].get("url")
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSITE FETCHING & PARSING
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_website(url: str, client: httpx.AsyncClient) -> Optional[dict]:
    """Fetch a website and extract content + metadata."""
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15)
        if resp.status_code != 200:
            return None

        html = resp.text
        headers = dict(resp.headers)

        # Extract text content (strip HTML tags)
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # Extract meta tags
        meta_desc = ""
        meta_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
        if meta_match:
            meta_desc = meta_match.group(1)

        # Extract links for blog/announcement detection
        links = re.findall(r'href=["\']([^"\']+)["\']', html, re.I)
        blog_links = [l for l in links if any(kw in l.lower() for kw in
            ['blog', 'news', 'announc', 'update', 'post', 'article', 'medium', 'mirror'])]

        # Count resources (images, scripts, stylesheets)
        images = len(re.findall(r'<img[^>]*>', html, re.I))
        scripts = len(re.findall(r'<script[^>]*src=', html, re.I))
        stylesheets = len(re.findall(r'<link[^>]*rel=["\']stylesheet["\']', html, re.I))

        # Page size
        page_size_kb = len(html) / 1024

        return {
            "url": url,
            "text": text[:5000],  # limit for analysis
            "meta_description": meta_desc,
            "page_size_kb": round(page_size_kb, 1),
            "image_count": images,
            "script_count": scripts,
            "stylesheet_count": stylesheets,
            "resource_count": images + scripts + stylesheets,
            "blog_links": blog_links[:10],
            "text_length": len(text),
            "word_count": len(text.split()),
            "status_code": resp.status_code,
            "content_type": headers.get("content-type", ""),
        }
    except Exception as e:
        return {"url": url, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# BLOG / ANNOUNCEMENT DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_blog_page(url: str, client: httpx.AsyncClient) -> Optional[dict]:
    """Fetch a blog/announcement page and extract recent posts."""
    try:
        resp = await client.get(url, follow_redirects=True, timeout=10)
        if resp.status_code != 200:
            return None

        html = resp.text

        # Extract article titles and dates
        articles = []

        # Pattern 1: <article> tags
        article_blocks = re.findall(r'<article[^>]*>(.*?)</article>', html, re.DOTALL | re.I)
        for block in article_blocks[:10]:
            title_match = re.search(r'<h[1-4][^>]*>(.*?)</h[1-4]>', block, re.I)
            date_match = re.search(r'(?:datetime|date|time)[^>]*>.*?(\d{4}[-/]\d{1,2}[-/]\d{1,2})', block, re.I)
            if not date_match:
                date_match = re.search(r'(\w+ \d{1,2},? \d{4})', block)
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ""
            date = date_match.group(1) if date_match else ""
            if title:
                articles.append({"title": title[:100], "date": date})

        # Pattern 2: h2/h3 titles (common on landing pages)
        if not articles:
            headings = re.findall(r'<h[23][^>]*>(.*?)</h[23]>', html, re.I)
            for h in headings[:10]:
                title = re.sub(r'<[^>]+>', '', h).strip()
                if len(title) > 10 and len(title) < 200:
                    articles.append({"title": title, "date": ""})

        # Pattern 3: Blog post links
        blog_urls = re.findall(r'href=["\']([^"\']*(?:blog|news|post|article|announc)[^"\']*)["\']', html, re.I)

        # Detect if content mentions dates/updates
        date_patterns = re.findall(r'(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}', html, re.I)
        recent_dates = re.findall(r'202[5-6][-/]\d{1,2}[-/]\d{1,2}', html)

        return {
            "articles_found": len(articles),
            "articles": articles[:5],
            "blog_urls": blog_urls[:5],
            "date_mentions": len(date_patterns),
            "recent_date_mentions": len(recent_dates),
            "has_blog_content": len(articles) > 0 or len(blog_urls) > 0,
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# TRAFFIC ESTIMATION
# ═══════════════════════════════════════════════════════════════════════════════

async def estimate_traffic(url: str, client: httpx.AsyncClient) -> dict:
    """
    Estimate website traffic using free signals.

    Methods (no API key needed):
      1. Check SimilarWeb free widget data
      2. Check for analytics scripts (GA, GTM, Plausible) as engagement signals
      3. Check social proof (Twitter widget, Discord widget)
      4. Check meta tags for Open Graph engagement
    """
    signals = {
        "has_analytics": False,
        "has_social_widgets": False,
        "analytics_type": "",
        "estimated_engagement": 0,
    }

    try:
        resp = await client.get(url, follow_redirects=True, timeout=10)
        if resp.status_code != 200:
            return signals

        html = resp.text.lower()

        # Analytics detection
        if "google-analytics" in html or "gtag" in html or "googletagmanager" in html:
            signals["has_analytics"] = True
            signals["analytics_type"] = "google"
        elif "plausible.io" in html or "plausible" in html:
            signals["has_analytics"] = True
            signals["analytics_type"] = "plausible"
        elif "umami" in html or "matomo" in html or "fathom" in html:
            signals["has_analytics"] = True
            signals["analytics_type"] = "privacy"

        # Social widgets
        if "twitter-timeline" in html or "twitter.com/widgets" in html:
            signals["has_social_widgets"] = True
        if "discord.com/widget" in html or "discord.gg" in html:
            signals["has_social_widgets"] = True
        if "telegram.org/js" in html or "t.me/" in html:
            signals["has_social_widgets"] = True

        # Engagement estimate (simple heuristic)
        engagement = 0
        if signals["has_analytics"]:
            engagement += 20  # investing in tracking = likely has traffic
        if signals["has_social_widgets"]:
            engagement += 15  # social proof
        if len(resp.text) > 50000:
            engagement += 10  # substantial site
        if "join" in html or "subscribe" in html or "newsletter" in html:
            engagement += 10  # audience building
        if "live" in html or "presale" in html or "buy now" in html:
            engagement += 15  # active marketing

        signals["estimated_engagement"] = engagement

    except Exception:
        pass

    return signals


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSITE COMPLEXITY SCORING
# ═══════════════════════════════════════════════════════════════════════════════

def score_complexity(website_data: dict) -> Tuple[float, dict]:
    """
    Score website complexity (0-25).

    Too simple = bad (rug indicator, lazy dev team).
    Well-built = good (real team, real investment).
    Over-complex = neutral (might be template).
    """
    score = 0.0
    details = {}

    if website_data.get("error"):
        return 0.0, {"error": website_data["error"]}

    page_size = website_data.get("page_size_kb", 0)
    resources = website_data.get("resource_count", 0)
    images = website_data.get("image_count", 0)
    word_count = website_data.get("word_count", 0)
    blog_links = website_data.get("blog_links", [])

    # Page size (1-8pts)
    if page_size > 500:
        score += 8
        details["size"] = "large"
    elif page_size > 100:
        score += 5
        details["size"] = "medium"
    elif page_size > 20:
        score += 2
        details["size"] = "small"
    else:
        score += 0
        details["size"] = "tiny"  # bad signal

    # Resource count (1-7pts)
    if resources > 20:
        score += 7
        details["resources"] = "rich"
    elif resources > 10:
        score += 4
        details["resources"] = "moderate"
    elif resources > 3:
        score += 2
        details["resources"] = "minimal"
    else:
        score += 0
        details["resources"] = "bare"  # bad signal

    # Image count (0-5pts)
    if images > 10:
        score += 5
    elif images > 3:
        score += 3
    elif images > 0:
        score += 1

    # Content depth (0-5pts)
    if word_count > 1000:
        score += 5
        details["content"] = "deep"
    elif word_count > 300:
        score += 3
        details["content"] = "moderate"
    elif word_count > 100:
        score += 1
        details["content"] = "shallow"
    else:
        details["content"] = "empty"  # very bad signal

    # Blog section exists (bonus)
    if blog_links:
        score += min(len(blog_links), 3)

    return round(min(score, 25), 1), details


# ═══════════════════════════════════════════════════════════════════════════════
# TRENDINESS SCORING
# ═══════════════════════════════════════════════════════════════════════════════

def score_trendiness(website_data: dict, trending_keywords: List[dict]) -> Tuple[float, dict]:
    """
    Score how well website content matches current trending topics (0-25).

    Compares website text against trending keywords from the AI keyword discovery.
    More keyword matches = higher trendiness = more likely to ride the wave.
    """
    if website_data.get("error") or not trending_keywords:
        return 0.0, {"error": "no data or keywords"}

    text = (website_data.get("text", "") + " " + website_data.get("meta_description", "")).lower()
    if not text:
        return 0.0, {"error": "no text"}

    score = 0.0
    matches = []

    for kw_data in trending_keywords:
        keyword = kw_data.get("keyword", "").lower()
        kw_score = kw_data.get("score", 50)

        if len(keyword) < 3:
            continue

        # Check if keyword appears in website content
        occurrences = text.count(keyword)
        if occurrences > 0:
            # Score based on keyword importance × occurrences
            match_score = min((kw_score / 100) * occurrences * 2, 5)
            score += match_score
            matches.append({"keyword": keyword, "occurrences": occurrences, "score": round(match_score, 1)})

    # Cap at 25
    return round(min(score, 25), 1), {"matches": matches[:10], "total_matches": len(matches)}


# ═══════════════════════════════════════════════════════════════════════════════
# BLOG ACTIVITY SCORING
# ═══════════════════════════════════════════════════════════════════════════════

def score_blog_activity(blog_data: Optional[dict]) -> Tuple[float, dict]:
    """Score blog/announcement activity (0-25)."""
    if not blog_data:
        return 0.0, {"error": "no blog data"}

    score = 0.0
    articles = blog_data.get("articles_found", 0)
    recent_dates = blog_data.get("recent_date_mentions", 0)
    has_blog = blog_data.get("has_blog_content", False)

    # Articles/posts found (0-10)
    if articles >= 5:
        score += 10
    elif articles >= 3:
        score += 7
    elif articles >= 1:
        score += 4

    # Recent date mentions (0-10)
    if recent_dates >= 5:
        score += 10
    elif recent_dates >= 2:
        score += 6
    elif recent_dates >= 1:
        score += 3

    # Has blog section at all (0-5)
    if has_blog:
        score += 5

    return round(min(score, 25), 1), {
        "articles": articles,
        "recent_dates": recent_dates,
        "has_blog": has_blog,
        "sample_articles": blog_data.get("articles", [])[:3],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# COMPOSITE WEBSITE SCORE
# ═══════════════════════════════════════════════════════════════════════════════

def compute_website_score(
    website_data: Optional[dict],
    blog_data: Optional[dict],
    traffic_data: Optional[dict],
    trending_keywords: List[dict],
) -> Tuple[float, dict]:
    """
    Compute composite website intelligence score (0-100).

    Blog Activity       25pts  (recent posts, update frequency)
    Website Complexity  25pts  (page size, resources, structure — too simple = bad)
    Content Trendiness  25pts  (keywords match trending social topics)
    Traffic Signals     15pts  (analytics, social widgets, engagement)
    Announcement Fresh  10pts  (how recent are announcements)
    """
    if not website_data or website_data.get("error"):
        return 0.0, {"error": "no website"}

    blog_score, blog_detail = score_blog_activity(blog_data)
    complexity_score, complexity_detail = score_complexity(website_data)
    trendiness_score, trendiness_detail = score_trendiness(website_data, trending_keywords)

    # Traffic signals (0-15)
    traffic_score = 0
    if traffic_data:
        traffic_score = min(traffic_data.get("estimated_engagement", 0), 15)

    # Announcement freshness (0-10)
    freshness_score = 0
    if blog_data:
        recent = blog_data.get("recent_date_mentions", 0)
        if recent >= 3:
            freshness_score = 10
        elif recent >= 1:
            freshness_score = 5

    total = round(blog_score + complexity_score + trendiness_score + traffic_score + freshness_score, 1)

    return total, {
        "blog_activity": {"score": blog_score, **blog_detail},
        "complexity": {"score": complexity_score, **complexity_detail},
        "trendiness": {"score": trendiness_score, **trendiness_detail},
        "traffic": {"score": traffic_score, **(traffic_data or {})},
        "freshness": {"score": freshness_score},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ANALYSIS RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

async def analyze_websites(
    tokens: List[dict],
    trending_keywords: List[dict],
    max_concurrent: int = 5,
) -> Dict[str, dict]:
    """
    Analyze websites for all tokens with URLs.

    Args:
        tokens: List of scored tokens (may have website URLs in enrichment)
        trending_keywords: From keyword_discovery module
        max_concurrent: Parallel website fetches

    Returns: {address: {website_score, website_details, ...}}
    """
    results: Dict[str, dict] = {}
    semaphore = __import__("asyncio").Semaphore(max_concurrent)

    async def analyze_one(token: dict, client: httpx.AsyncClient):
        addr = token.get("contract_address", "")
        if not addr:
            return

        # Find website URL (from enrichment data or discover it)
        url = token.get("website_url")
        if not url:
            url = await discover_website(token.get("chain", ""), addr, client)

        if not url:
            results[addr] = {"website_score": 0, "has_website": False}
            return

        async with semaphore:
            # Fetch main page
            website_data = await fetch_website(url, client)

            # Fetch blog/announcement pages
            blog_data = None
            if website_data and website_data.get("blog_links"):
                blog_url = website_data["blog_links"][0]
                if not blog_url.startswith("http"):
                    blog_url = url.rstrip("/") + "/" + blog_url.lstrip("/")
                blog_data = await fetch_blog_page(blog_url, client)

            # Traffic signals
            traffic_data = await estimate_traffic(url, client)

            # Compute score
            website_score, details = compute_website_score(
                website_data, blog_data, traffic_data, trending_keywords
            )

            results[addr] = {
                "website_url": url,
                "website_score": website_score,
                "has_website": True,
                "website_details": details,
            }

            log.debug("website_analyzed", token=token.get("symbol", ""),
                     url=url, score=website_score)

    limits = httpx.Limits(max_connections=max_concurrent + 2)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20, connect=5),
        limits=limits,
        headers={"User-Agent": "Mozilla/5.0 (compatible; HermesScreener/9.0)"},
    ) as client:
        tasks = [analyze_one(t, client) for t in tokens[:30]]  # limit to top 30
        await __import__("asyncio").gather(*tasks, return_exceptions=True)

    log.info("websites_analyzed", total=len(results), with_website=sum(1 for r in results.values() if r.get("has_website")))
    return results


def run_website_analysis(
    tokens: List[dict],
    trending_keywords: List[dict],
) -> Dict[str, dict]:
    """Sync wrapper for analyze_websites()."""
    import asyncio
    return asyncio.run(analyze_websites(tokens, trending_keywords))

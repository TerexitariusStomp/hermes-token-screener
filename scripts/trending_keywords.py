#!/usr/bin/env python3
"""
Trending Keyword Extractor — Dexscreener Edition

Fetches token descriptions from Dexscreener's boosted tokens API
and extracts trending keywords using frequency analysis.

Output: ~/.hermes/data/token_screener/trending_keywords.json
Used by AI trading brain for narrative-aware decisions.
Refreshed by cron every 10 minutes.
"""

import json
import time
import re
import urllib.request
import urllib.error
from collections import Counter
from pathlib import Path

DATA_DIR = Path.home() / ".hermes" / "data"
OUTPUT_PATH = DATA_DIR / "token_screener" / "trending_keywords.json"

# Comprehensive stopwords (per skill spec — covers pronouns, prepositions,
# auxiliary verbs, common adverbs/fillers, plus discovered leak candidates)
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "is", "was", "are", "been", "be", "have", "has", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might", "must", "can", "this",
    "that", "these", "those", "i", "you", "he", "she", "it", "we", "they", "me", "him",
    "her", "us", "them", "my", "your", "his", "its", "our", "their", "mine", "yours",
    "hers", "ours", "theirs", "what", "which", "who", "whom", "where", "when", "why",
    "how", "all", "each", "every", "both", "few", "more", "most", "much", "many", "some",
    "such", "no", "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "also", "now", "get", "one", "two", "three", "first", "last", "next", "like", "good",
    "best", "big", "still", "even", "back", "well", "way", "make", "take", "come", "go",
    "see", "know", "want", "give", "use", "find", "tell", "ask", "work", "seem", "feel",
    "try", "leave", "call", "keep", "let", "begin", "show", "hear", "play", "run", "move",
    "live", "believe", "hold", "bring", "happen", "must", "provide", "sit", "stand", "lose",
    "pay", "meet", "include", "continue", "set", "learn", "change", "lead", "understand",
    "watch", "follow", "stop", "create", "speak", "read", "allow", "add", "spend", "grow",
    "open", "walk", "win", "offer", "remember", "love", "consider", "appear", "buy", "wait",
    "serve", "die", "send", "expect", "build", "stay", "fall", "cut", "reach", "kill",
    "remain", "again", "if", "as", "everyone", "anything", "anyone", "someone", "somebody",
    "nobody", "something", "nothing", "token", "coin",
}

# Crypto-specific terms that are stopword-like but domain-relevant
CRYPTO_WHITELIST = {"btc", "eth", "sol", "defi", "nft", "dao", "web3", "ai", "ml", "l2",
                    "layer", "lfg", "ngmi", "gm", "wagmi", "hodl", "ape", "apein", "rekt"}


def fetch_json(url: str, timeout: int = 15):
    """Fetch JSON from URL with User-Agent header."""
    req = urllib.request.Request(url, headers={"User-Agent": "HermesAgent/1.0 (+https://github.com/NousResearch/hermes)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_boosted_tokens():
    """Fetch top boosted tokens from Dexscreener."""
    url = "https://api.dexscreener.com/token-boosts/top/v1"
    data = fetch_json(url)
    if isinstance(data, list):
        return data
    return []


def collect_descriptions(boosts):
    """Extract descriptions from boost objects and triggers."""
    descriptions = []
    seen = set()

    for token in boosts[:50]:  # Top 50 boosts
        # Primary description field
        desc = token.get("description", "") or token.get("promoTitle", "")
        if desc and len(desc) > 5:
            key = desc.lower().strip()[:120]
            if key not in seen:
                seen.add(key)
                descriptions.append(desc)

        # Trigger-embedded description
        trigger = token.get("trigger", {})
        if trigger:
            tdesc = trigger.get("description", "")
            if tdesc and len(tdesc) > 5:
                key = tdesc.lower().strip()[:120]
                if key not in seen:
                    seen.add(key)
                    descriptions.append(tdesc)

        time.sleep(0.05)  # Be nice to rate limits

    return descriptions


def extract_keywords(texts):
    """Frequency-analysis keyword extraction with bigrams."""
    word_freq = Counter()
    bigram_freq = Counter()

    for text in texts:
        if not text:
            continue
        clean = re.sub(r"[^\w\s]", " ", text.lower())
        words = [w for w in clean.split() if len(w) >= 3 and w not in STOPWORDS]
        word_freq.update(words)

        for i in range(len(words) - 1):
            bigram_freq[f"{words[i]} {words[i+1]}"] += 1

    keywords = []
    for word, count in word_freq.most_common(50):
        if count >= 2:
            keywords.append({"keyword": word, "count": count, "type": "word"})
    for bg, count in bigram_freq.most_common(20):
        if count >= 2:
            keywords.append({"keyword": bg, "count": count, "type": "bigram"})

    keywords.sort(key=lambda k: -k["count"])
    return keywords[:60]


def defensively_zero_stopwords(keywords):
    """Detect and zero any leaked stopwords."""
    leaked = [k for k in keywords if k["keyword"].lower() in STOPWORDS and k["count"] > 0]
    if leaked:
        for k in leaked:
            k["count"] = 0
        print(f"  ⚠️  Stop-word leak zeroed: {[k['keyword'] for k in leaked]}")
    keywords.sort(key=lambda k: -k["count"])
    return [k for k in keywords if k["count"] > 0]


def rotate_archives(keep: int = 10):
    """Clean old archives from the archives/ subdirectory."""
    archive_dir = OUTPUT_PATH.parent / "archives"
    archives = sorted(archive_dir.glob("trending_keywords.json.*.archive"),
                      key=lambda p: p.stat().st_mtime,
                      reverse=True)
    for old in archives[keep:]:
        old.unlink()


def main():
    print("=" * 60)
    print("Trending Keyword Extractor — Dexscreener Boosted Tokens")
    print("=" * 60)

    boosts = fetch_boosted_tokens()
    if not boosts:
        print("ERROR: No boost data received from Dexscreener.")
        return

    print(f"  Fetched {len(boosts)} boosted tokens")
    descriptions = collect_descriptions(boosts)
    print(f"  Collected {len(descriptions)} unique descriptions")

    if not descriptions:
        print("ERROR: No descriptions extracted.")
        return

    keywords = extract_keywords(descriptions)
    keywords = defensively_zero_stopwords(keywords)

    output = {
        "method": "dexscreener_boosted_lists",
        "generated_at": time.time(),
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "window_hours": 1.0,
        "texts_analyzed": len(descriptions),
        "token_names": 0,
        "keywords": keywords,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if OUTPUT_PATH.exists():
        ts = time.strftime("%Y%m%d-%H%M%S")
        archive_dir = OUTPUT_PATH.parent / "archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        dest = archive_dir / f"trending_keywords.json.{ts}.archive"
        OUTPUT_PATH.rename(dest)
        print(f"  Rotated previous output → archives/{dest.name}")

    OUTPUT_PATH.write_text(json.dumps(output, indent=2))

    print(f"\nTop {min(15, len(keywords))} keywords:")
    for kw in keywords[:15]:
        bar = "#" * min(kw["count"], 30)
        print(f"  {kw['keyword']:>20}  {kw['count']:>4}  {bar}")

    print(f"\nSaved → {OUTPUT_PATH}")
    rotate_archives(keep=10)
    print("=" * 60)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Trending Keyword Extractor

Extracts trending keywords/topics from:
  - PumpPortal token names (last 1h)
  - GMGN trench/trending token names
  - Telegram contract call messages

Outputs: ~/.hermes/data/token_screener/trending_keywords.json
Refreshed by cron every 10 minutes.
"""

import json
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path

DATA_DIR = Path.home() / ".hermes" / "data"
DB_PATH = DATA_DIR / "central_contracts.db"
OUTPUT_PATH = DATA_DIR / "token_screener" / "trending_keywords.json"

# Common words to exclude
STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "is",
    "was",
    "are",
    "been",
    "be",
    "have",
    "has",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "can",
    "this",
    "that",
    "these",
    "those",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "me",
    "him",
    "her",
    "us",
    "them",
    "my",
    "your",
    "his",
    "its",
    "our",
    "their",
    "mine",
    "yours",
    "hers",
    "ours",
    "theirs",
    "what",
    "which",
    "who",
    "whom",
    "where",
    "when",
    "why",
    "how",
    "all",
    "each",
    "every",
    "both",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "just",
    "also",
    "now",
    "new",
    "get",
    "one",
    "two",
    "three",
    "first",
    "last",
    "next",
    "like",
    "good",
    "best",
    "big",
    "much",
    "still",
    "even",
    "back",
    "well",
    "way",
    "make",
    "take",
    "come",
    "go",
    "see",
    "know",
    "want",
    "give",
    "use",
    "find",
    "tell",
    "ask",
    "work",
    "seem",
    "feel",
    "try",
    "leave",
    "call",
    "keep",
    "let",
    "begin",
    "show",
    "hear",
    "play",
    "run",
    "move",
    "live",
    "believe",
    "hold",
    "bring",
    "happen",
    "must",
    "provide",
    "sit",
    "stand",
    "lose",
    "pay",
    "meet",
    "include",
    "continue",
    "set",
    "learn",
    "change",
    "lead",
    "understand",
    "watch",
    "follow",
    "stop",
    "create",
    "speak",
    "read",
    "allow",
    "add",
    "spend",
    "grow",
    "open",
    "walk",
    "win",
    "offer",
    "remember",
    "love",
    "consider",
    "appear",
    "buy",
    "wait",
    "serve",
    "die",
    "send",
    "expect",
    "build",
    "stay",
    "fall",
    "cut",
    "reach",
    "kill",
    "remain",
    "pump",
    "token",
    "coin",
    "sol",
    "eth",
    "usd",
    "www",
    "http",
    "https",
    "com",
    "io",
    "xyz",
    "fun",
    "discord",
    "telegram",
    "twitter",
    "x",
    "dexscreener",
    "gmgn",
    "raydium",
    "pumpfun",
}


def extract_token_names(texts: list[str]) -> list[str]:
    """Extract actual token names/symbols from message texts."""
    names = []
    for text in texts:
        if not text:
            continue
        # Format: "NAME | (SYMBOL) | mcap_sol=X | init_buy=Y | sol=Z"
        # Or:     "pumpfun_dev | tokens: NAME (ADDR...), NAME (ADDR...)"

        if "|" in text:
            parts = text.split("|")
            # First part is usually the name
            name = parts[0].strip()
            if name and not name.startswith("pumpfun_dev"):
                names.append(name)
            # Second part might be (SYMBOL)
            if len(parts) > 1:
                sym_match = re.search(r"\(([^)]+)\)", parts[1])
                if sym_match:
                    names.append(sym_match.group(1))

        if "tokens:" in text:
            # Extract token names from "tokens: NAME (...), NAME (...)"
            for m in re.finditer(r"([A-Za-z0-9\s]+?)\s*\(", text.split("tokens:")[-1]):
                name = m.group(1).strip()
                if name and len(name) >= 2:
                    names.append(name)

    return names


def extract_keywords(texts: list[str], min_freq: int = 2) -> list[dict]:
    """Extract keywords from a list of texts using frequency analysis."""
    word_freq = Counter()
    bigram_freq = Counter()

    for text in texts:
        if not text:
            continue
        # Clean and tokenize
        clean = re.sub(r"[^\w\s]", " ", text.lower())
        words = [w for w in clean.split() if len(w) >= 3 and w not in STOPWORDS]
        word_freq.update(words)

        # Bigrams
        for i in range(len(words) - 1):
            bg = f"{words[i]} {words[i+1]}"
            bigram_freq[bg] += 1

    # Combine and filter
    keywords = []
    for word, count in word_freq.most_common(50):
        if count >= min_freq:
            keywords.append({"keyword": word, "count": count, "type": "word"})

    for bg, count in bigram_freq.most_common(20):
        if count >= min_freq:
            keywords.append({"keyword": bg, "count": count, "type": "bigram"})

    # Sort by count descending
    keywords.sort(key=lambda k: -k["count"])
    return keywords[:30]


def fetch_recent_texts(hours: float = 1.0) -> list[str]:
    """Fetch token names and messages from the last N hours."""
    texts = []
    cutoff = time.time() - (hours * 3600)

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row

        # Token names from pumpportal and gmgn
        rows = conn.execute(
            """
            SELECT last_message_text FROM telegram_contracts_unique
            WHERE last_seen_at > ?
            AND (last_source LIKE '%pumpportal%' OR last_source LIKE '%gmgn%')
        """,
            (cutoff,),
        ).fetchall()
        for r in rows:
            texts.append(r["last_message_text"] or "")

        # Also get telegram messages
        rows2 = conn.execute(
            """
            SELECT message_text FROM telegram_contract_calls
            WHERE observed_at > ?
            LIMIT 500
        """,
            (cutoff,),
        ).fetchall()
        for r in rows2:
            texts.append(r["message_text"] or "")

        conn.close()
    except Exception as e:
        print(f"DB error: {e}")

    return texts


def main():
    print("Extracting trending keywords...")

    texts = fetch_recent_texts(hours=1.0)
    print(f"  {len(texts)} texts from last 1h")

    # Extract actual token names (cleaner signal)
    token_names = extract_token_names(texts)
    name_freq = Counter(
        n.lower() for n in token_names if len(n) >= 2 and n.lower() not in STOPWORDS
    )
    token_keywords = [
        {"keyword": name, "count": count, "type": "token"}
        for name, count in name_freq.most_common(20)
        if count >= 2
    ]

    # Also extract general keywords from names only (not metadata)
    general_kw = extract_keywords(token_names, min_freq=2)

    # Merge, dedup, sort
    seen = set()
    keywords = []
    for kw in token_keywords + general_kw:
        if kw["keyword"] not in seen:
            seen.add(kw["keyword"])
            keywords.append(kw)

    keywords.sort(key=lambda k: -k["count"])
    keywords = keywords[:25]

    # Add metadata
    output = {
        "generated_at": time.time(),
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "window_hours": 1.0,
        "texts_analyzed": len(texts),
        "keywords": keywords,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))

    # Print top keywords
    print(f"\nTop trending keywords:")
    for kw in keywords[:15]:
        bar = "#" * min(kw["count"], 30)
        print(f"  {kw['keyword']:>20}  {kw['count']:>4}  {bar}")

    print(f"\nSaved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Trending Keyword Extractor (Dexscreener description analysis)

Extracts trending keywords from Dexscreener token descriptions with
intelligent filtering. Uses Bonsai-8B if available, otherwise a
smart frequency analysis focused on the description content.

Outputs: ~/.hermes/data/token_screener/trending_keywords.json
Archives: ~/.hermes/data/token_screener/trending_keywords.json.YYYYMMDD-HHMMSS.archive (kept 7d)
"""

import json
import re
import subprocess
import sys
import time
import shutil
from collections import Counter
from pathlib import Path
from datetime import datetime, timedelta

import requests


# Testing: force frequency mode

DATA_DIR = Path.home() / ".hermes" / "data"
TOP100_PATH = DATA_DIR / "token_screener" / "top100.json"
OUTPUT_PATH = DATA_DIR / "token_screener" / "trending_keywords.json"
ARCHIVE_DIR = DATA_DIR / "token_screener" / "archives"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

BONSAI_URL = "http://localhost:8083/v1/chat/completions"
BONSAI_MODEL = "Bonsai-8B.gguf"

STOPWORDS = {
    # --- Pronouns ---
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "mine", "yours", "hers", "ours", "theirs",
    "this", "that", "these", "those", "who", "which", "what", "where", "when", "why", "how",
    "whoever", "whatever", "whichever", "whomever",
    # --- Prepositions ---
    "of", "in", "on", "at", "to", "for", "with", "by", "from", "as", "into", "through",
    "during", "before", "after", "over", "under", "between", "among", "against", "around",
    "above", "below", "beyond", "near", "onto", "upon", "toward", "within", "without",
    # --- Conjunctions ---
    "and", "or", "but", "nor", "for", "yet", "so", "because", "although", "since", "unless",
    # --- Articles & Determiners ---
    "a", "an", "the", "all", "each", "every", "both", "few", "more", "most", "other", "some",
    "such", "no", "not", "only", "own", "same", "so", "than", "too", "very", "just", "also",
    "now", "any", "most", "many", "much", "little", "few", "several",
    # --- Auxiliary/Modal Verbs ---
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "must", "can", "shall", "ought", "need", "dare",
    # --- Common Adverbs/Fillers ---
    "all", "some", "such", "not", "no", "nor", "only", "own", "same", "so", "than", "too",
    "very", "just", "also", "now", "get", "one", "two", "three", "first", "last", "next",
    "like", "well", "way", "make", "take", "come", "go", "see", "know", "want", "give",
    "use", "find", "tell", "ask", "work", "seem", "feel", "try", "leave", "keep", "let",
    "show", "hear", "play", "run", "move", "live", "hold", "bring", "must", "there", "here",
    "about", "into", "over", "after", "before", "between", "under", "again", "then", "once",
    "been", "being", "having", "doing", "while", "its", "made", "making", "uses", "used", "using",
    "world", "first", "based", "built", "powered", "designed", "created", "team", "governance",
    "ecosystem", "utility", "features", "innovative", "unique", "revolutionary", "next",
    "generation", "leading", "top", "best", "biggest", "largest", "growing", "fast", "secure",
    "great", "real", "time", "become", "give", "good", "things", "never", "without", "right",
    "something", "nothing", "people", "still", "through",
    # --- Additional common leaks ---
    "everyone", "everything", "anyone", "anybody", "someone", "somebody", "noone", "nobody",
    "each", "both", "few", "many", "several", "such", "too", "very", "quite", "rather",
    "almost", "already", "always", "often", "sometimes", "usually", "never", "ever", "just",
    "maybe", "perhaps", "probably", "certainly", "definitely", "clearly", "obviously",
    # --- DeFi generic (not narratives) ---
    "txns", "txn", "stagnant", "volume", "rug", "burned", "renounced", "liquidity", "swap",
    "pool", "pair", "burn", "contract", "deployed", "address", "supply", "circulating",
    "marketcap", "mcap", "verified", "tracked", "traded", "trading", "exchange", "uniswap",
    "raydium",
    # --- Crypto platform/tool names (generic) ---
    "token", "coin", "project", "community", "official", "blockchain", "protocol", "platform",
    "network", "chain", "website", "link", "join", "follow", "page", "discord", "telegram",
    "twitter", "dexscreener", "pumpfun", "solana", "ethereum", "pump", "fun", "sol", "eth",
    "usd", "www", "http", "https", "com", "io", "xyz", "amp", "nbsp", "don", "new", "la",
    "el", "en",
    # Common filler words (non-crypto-relevant)
    "out", "back", "off", "away", "simple", "call", "wait", "still",
    "ever", "never", "right", "here", "there", "well", "way", "make", "take",
    "come", "go", "see", "know", "want", "give", "use", "find", "tell", "ask",
    "work", "seem", "feel", "try", "leave", "keep", "let", "show", "hear",
    "play", "run", "move", "live", "hold", "bring", "become", "get", "one",
    # Generic nouns/verbs that dilute crypto narrative signals
    "internet", "social", "media", "face", "culture", "cycle", "leads", "movement",
    "phenomenon", "overtaking", "scroll", "escape", "space", "time", "dream",
    "real", "first", "final", "coming", "meet", "face", "mind", "body",
    # Extended stopwords
    "place", "waiting", "came", "upon", "also",
    "through", "since", "something", "anything",
    "end", "going", "combining", "inspired", "symbol", "oldest", "private",

    # Extended stopwords
    "place",
    "waiting",
    "came",
    "upon",
    "through",
    "since",
    "also",
}


def curl_json(url: str, timeout: int = 10) -> list | dict | None:
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout), "-L",
             "-H", "User-Agent: Mozilla/5.0", url],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        if r.stdout:
            return json.loads(r.stdout)
    except Exception:
        pass
    return None


def collect_data() -> tuple[list[str], list[str], list[str]]:
    """Collect descriptions and token names from Dexscreener + top100."""
    descriptions = []
    token_names = []
    scoring_signals = []

    # 1. Dexscreener boosted tokens (richest source of descriptions)
    seen_descs = set()
    for endpoint in ["top/v1", "latest/v1"]:
        data = curl_json(f"https://api.dexscreener.com/token-boosts/{endpoint}", timeout=15)
        if data and isinstance(data, list):
            for item in data:
                desc = item.get("description", "").strip()
                # Deduplicate + filter spam
                if desc and len(desc) > 10 and len(desc) < 500 and desc not in seen_descs:
                    # Skip obvious spam patterns (repeated filler phrases)
                    spam_patterns = [
                        r"larp.*til.*make.*it",
                        r"papi.*papi.*papi",
                        r"cant escape",
                        r"wherever you scroll",
                    ]
                    is_spam = any(re.search(p, desc.lower()) for p in spam_patterns)
                    if not is_spam:
                        seen_descs.add(desc)
                        descriptions.append(desc)

    # 2. Top100 data
    if TOP100_PATH.exists():
        try:
            top100 = json.loads(TOP100_PATH.read_text())
            chain_map = {
                "ethereum": "ethereum", "eth": "ethereum",
                "solana": "solana", "sol": "solana",
                "base": "base",
            }
            tokens = top100.get("tokens", [])

            # Token names (low weight - just for context)
            for t in tokens:
                sym = t.get("symbol", "")
                name = t.get("name", "")
                if sym:
                    token_names.append(sym)
                if name and name != sym:
                    token_names.append(name)

            # Scoring signals (kept separate, low weight)
            for t in tokens:
                for p in (t.get("positives") or []):
                    scoring_signals.append(p)
                for n in (t.get("negatives") or []):
                    scoring_signals.append(n)

            # Fetch descriptions for top 15 scored tokens from Dexscreener
            scored = sorted(tokens, key=lambda t: -(t.get("score", 0) or 0))
            for t in scored[:15]:
                chain = chain_map.get(t.get("chain", "").lower(), "solana")
                addr = t.get("contract_address", "")
                if not addr:
                    continue
                data = curl_json(
                    f"https://api.dexscreener.com/tokens/v1/{chain}/{addr}",
                    timeout=8,
                )
                if data and isinstance(data, list):
                    for pair in data:
                        desc = pair.get("info", {}).get("description", "")
                        if desc and len(desc) > 10:
                            descriptions.append(desc)
                        break
                time.sleep(0.2)
        except Exception:
            pass

    print(f"  Descriptions: {len(descriptions)}, Token names: {len(token_names)}, Signals: {len(scoring_signals)}")
    return descriptions, token_names, scoring_signals


def try_ai_extraction(descriptions: list[str], token_names: list[str]) -> list[dict] | None:
    """Try Bonsai-8B for keyword extraction. Returns None if unavailable."""
    try:
        health = requests.get("http://localhost:8083/health", timeout=3)
        if health.status_code != 200:
            return None
    except Exception:
        return None

    desc_block = "\n".join(descriptions[:5])  # 5 descriptions max for speed
    names_block = ", ".join(token_names[:30])

    system = (
        "Extract trending crypto themes and narratives from token descriptions. "
        "Return ONLY a JSON array of strings: [\"keyword1\", \"keyword2\", ...]. "
        "10-15 items. Focus on memes, sectors, narratives, cultural references. "
        "No generic filler words."
    )
    prompt = f"Tokens: {names_block}\n\nDescriptions:\n{desc_block}\n\nJSON array:"

    try:
        resp = requests.post(
            BONSAI_URL,
            json={
                "model": BONSAI_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 150,
                "temperature": 0.3,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            json_match = re.search(r'\[.*?\]', content, re.DOTALL)
            if json_match:
                themes = json.loads(json_match.group())
                if not isinstance(themes, list):
                    return None

                # Count actual occurrences across ALL descriptions
                result = []
                for theme in themes[:15]:
                    word = str(theme).strip().lower()
                    if not word or len(word) < 3 or word in STOPWORDS:
                        continue

                    # Count occurrences in full description set (not just 5 sampled)
                    count = 0
                    for desc in descriptions:
                        if word in desc.lower():
                            count += 1

                    if count >= 2:  # Only include if found in 2+ descriptions
                        result.append({"keyword": word, "count": count, "type": "theme"})

                result.sort(key=lambda k: -k["count"])
                return result[:15] if result else None
    except Exception as e:
        print(f"  AI failed: {e}")

    return None


def rotate_archives() -> None:
    """Archive the current trending_keywords.json before writing a new one."""
    if OUTPUT_PATH.exists():
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        archive_path = ARCHIVE_DIR / f"trending_keywords.json.{ts}.archive"
        shutil.copy2(OUTPUT_PATH, archive_path)
        print(f"  Archived previous run as: {archive_path.name}")

        # Prune archives older than 7 days
        cutoff = datetime.utcnow() - timedelta(days=7)
        pruned = 0
        for f in ARCHIVE_DIR.glob("trending_keywords.json.*.archive"):
            try:
                # Parse timestamp from filename: trending_keywords.json.YYYYMMDD-HHMMSS.archive
                parts = f.stem.split('.')
                if len(parts) >= 3:
                    file_ts_str = parts[2]  # YYYYMMDD-HHMMSS
                    file_dt = datetime.strptime(file_ts_str, "%Y%m%d-%H%M%S")
                    if file_dt < cutoff:
                        f.unlink(missing_ok=True)
                        pruned += 1
            except Exception:
                pass  # skip files we can't parse
        if pruned:
            print(f"  Pruned {pruned} archive(s) older than 7 days")


def smart_extract(descriptions: list[str], token_names: list[str], signals: list[str]) -> list[dict]:
    """Smart frequency analysis focused on description content."""
    # Weight: descriptions (x3) > token names (x1) > signals (x0.5)
    word_freq = Counter()
    bigram_freq = Counter()

    def process_text(text: str, weight: int = 1):
        clean = re.sub(r"[^\w\s]", " ", text.lower())
        words = [w for w in clean.split() if len(w) >= 3 and w not in STOPWORDS and not w.isdigit()]
        word_freq.update({w: weight for w in words})
        for i in range(len(words) - 1):
            bg = f"{words[i]} {words[i+1]}"
            bigram_freq[bg] += weight

    # Descriptions get 3x weight — this is the organic content
    for desc in descriptions:
        process_text(desc, weight=3)

    # Token names 1x — useful for context
    for name in token_names:
        process_text(name, weight=1)

    # Signals excluded — they're system-generated (txns, stagnant, volume, etc.)

    # ---- Verification: assert stop-words did NOT leak through ----
    # Critical stop-words that MUST be filtered to 0 count
    CRITICAL_STOPWORDS = [
        "the", "of", "and", "in", "on", "at", "to", "for", "with", "by", "from", "is",
        "are", "was", "were", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "must", "can", "this", "that",
        "these", "those", "as", "if", "again", "everyone", "anything", "something",
        "nothing", "anyone", "someone", "noone", "everybody", "nobody", "somebody",
        # Expanded filler list (matches STOPWORDS subset)
        "out", "back", "off", "away", "simple", "call", "wait", "still", "again",
        "ever", "never", "right", "here", "there", "well", "way", "make", "take",
        "come", "go", "see", "know", "want", "give", "use", "find", "tell", "ask",
        "work", "seem", "feel", "try", "leave", "keep", "let", "show", "hear",
        "play", "run", "move", "live", "hold", "bring", "become", "get", "one",
        "place", "waiting", "came", "upon", "through", "since",
        "end", "going", "combining", "inspired", "symbol", "oldest", "private",
    ]
    leaked = [w for w in CRITICAL_STOPWORDS if word_freq.get(w, 0) > 0]
    if leaked:
        print(f"  WARNING: Stop-word leak detected: {leaked}")
        for w in leaked:
            word_freq[w] = 0  # Zero it out defensively

    keywords = []
    for word, count in word_freq.most_common(40):
        if count >= 3:
            keywords.append({"keyword": word, "count": count, "type": "word"})

    for bg, count in bigram_freq.most_common(15):
        if count >= 3:
            keywords.append({"keyword": bg, "count": count, "type": "bigram"})

    keywords.sort(key=lambda k: -k["count"])

    # Deduplicate singular/plural variants
    seen = set()
    deduped = []
    for kw in keywords:
        base = kw["keyword"].rstrip("s")
        if base in seen:
            continue
        seen.add(base)
        deduped.append(kw)

    return deduped[:20]


def main():
    print("Trending Keyword Extractor")
    print("=" * 50)

    # Rotate/archive previous output before collecting new data
    rotate_archives()

    descriptions, token_names, signals = collect_data()
    if not descriptions:
        print("ERROR: No descriptions collected")
        sys.exit(1)

    # Try AI first
    print("  Trying Bonsai-8B...")
    keywords = try_ai_extraction(descriptions, token_names)
    method = "ai"

    # Fallback to smart frequency
    if not keywords:
        print("  Using smart frequency extraction...")
        keywords = smart_extract(descriptions, token_names, signals)
        method = "frequency"

    output = {
        "generated_at": time.time(),
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "window_hours": 1.0,
        "texts_analyzed": len(descriptions),
        "token_names": len(token_names),
        "method": method,
        "keywords": keywords[:25],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))

    print(f"\nTrending keywords ({method}):")
    for kw in keywords[:15]:
        bar = "#" * min(kw["count"], 30)
        print(f"  {kw['keyword']:>20}  {kw['count']:>4}  {bar}")

    print(f"\nSaved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

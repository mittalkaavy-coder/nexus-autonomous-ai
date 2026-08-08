"""Quick manual verification script for Phase 6 live discovery."""
import logging
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from app.discovery import discover_topics, LIVE_FEEDS

print("\n=== LIVE DISCOVERY RUN ===\n")
topics = discover_topics()
print(f"\nTotal live candidates: {len(topics)}")

for i, t in enumerate(topics, 1):
    title = t["title"][:90]
    url = t["source_url"][:80]
    pub = t["published_at"]
    print(f"\n[{i}] {title}")
    print(f"    source_url   : {url}")
    print(f"    published_at : {pub}")

print("\n\n=== BROKEN FEED TEST ===\n")
# Temporarily inject a broken URL into the feed list and confirm it doesn't crash
from app import discovery as disc_module

original_feeds = disc_module.LIVE_FEEDS
broken_feeds = [
    {"name": "Broken Feed", "url": "https://this-domain-does-not-exist-nexus-test.invalid/rss"},
    {"name": "Timeout Feed", "url": "http://10.255.255.1/timeout-test"},   # non-routable, will timeout
]

disc_module.LIVE_FEEDS = broken_feeds
print("Running discovery with only broken feeds...")
result = discover_topics()
print(f"Result: {result!r}  (expected: [])")
assert result == [], f"Expected [], got {result}"
print("[PASS] All-sources-down returns [] without raising.\n")

disc_module.LIVE_FEEDS = original_feeds

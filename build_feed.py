#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["feedparser", "requests"]
# ///
"""Build a curated podcast RSS feed from hand-picked episodes.

Reads good-ones.json and source-rss-feeds.json from the same directory,
fetches the source feeds, extracts matching episodes, and writes a
combined RSS feed (feed.xml) with episodes in chronological order.

Usage:
    uv run build_feed.py
"""

import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path

import feedparser
import requests

SCRIPT_DIR = Path(__file__).parent
OUTPUT_FILE = SCRIPT_DIR / "feed.xml"
REQUEST_TIMEOUT = 30
USER_AGENT = "this-is-a-good-one/1.0 (podcast feed aggregator)"


def normalize(text: str) -> str:
    """Normalize text for comparison."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    for ch in "\u2018\u2019\u0060\u00b4":
        text = text.replace(ch, "'")
    for ch in "\u201c\u201d":
        text = text.replace(ch, '"')
    for ch in "\u2013\u2014":
        text = text.replace(ch, "-")
    return text


def titles_match(feed_title: str, good_one_title: str) -> bool:
    """Check if a feed item title matches a good-ones title."""
    ft = normalize(feed_title)
    gt = normalize(good_one_title)
    return ft == gt or gt in ft or ft in gt


def episode_number_from_entry(entry) -> str | None:
    """Extract episode number from a feedparser entry."""
    ep = entry.get("itunes_episode")
    if ep:
        return str(ep).strip()
    title = entry.get("title", "")
    m = re.match(r"(?:ep\.?\s*)?#?(\d+[a-z]?)\s*[:\-\u2013\u2014]", title, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def find_matches(feed, good_ones_for_show):
    """Match feed entries to the good-ones list for a show.

    Returns (matched, remaining) where matched is a list of
    (entry, good_one) tuples and remaining is unmatched good-ones.
    """
    matched = []
    remaining = list(good_ones_for_show)

    for entry in feed.entries:
        if not remaining:
            break
        entry_title = entry.get("title", "")
        entry_ep = episode_number_from_entry(entry)

        for i, go in enumerate(remaining):
            if titles_match(entry_title, go["title"]):
                matched.append((entry, go))
                remaining.pop(i)
                break
            if go.get("number") and entry_ep and str(go["number"]) == entry_ep:
                matched.append((entry, go))
                remaining.pop(i)
                break

    return matched, remaining


def parse_pub_date(entry) -> datetime:
    """Parse publication date from a feedparser entry."""
    pp = entry.get("published_parsed") or entry.get("updated_parsed")
    if pp:
        return datetime(*pp[:6], tzinfo=timezone.utc)
    for field in ("published", "updated"):
        val = entry.get(field, "")
        if val:
            try:
                return parsedate_to_datetime(val)
            except Exception:
                pass
    return datetime(2000, 1, 1, tzinfo=timezone.utc)


def escape_xml(text: str) -> str:
    """Escape text for use in XML."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def cdata(text: str) -> str:
    """Wrap text in a CDATA section, handling nested ]]>."""
    text = str(text).replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{text}]]>"


def entry_to_item_xml(entry, show_name: str) -> str:
    """Convert a feedparser entry to an RSS <item> XML string."""
    lines = ["  <item>"]

    title = entry.get("title", "")
    lines.append(f"    <title>{escape_xml(title)}</title>")

    link = entry.get("link", "")
    if link:
        lines.append(f"    <link>{escape_xml(link)}</link>")

    summary = entry.get("summary", "")
    if summary:
        lines.append(f"    <description>{cdata(summary)}</description>")

    pub = entry.get("published", "")
    if pub:
        lines.append(f"    <pubDate>{escape_xml(pub)}</pubDate>")

    guid = entry.get("id", "") or link
    if guid:
        perm = "true" if guid.startswith("http") else "false"
        lines.append(f'    <guid isPermaLink="{perm}">{escape_xml(guid)}</guid>')

    for enc in entry.get("enclosures", []):
        url = escape_xml(enc.get("url", enc.get("href", "")))
        length = enc.get("length", "0")
        etype = enc.get("type", "audio/mpeg")
        lines.append(f'    <enclosure url="{url}" length="{length}" type="{etype}" />')

    duration = entry.get("itunes_duration", "")
    if duration:
        lines.append(f"    <itunes:duration>{escape_xml(duration)}</itunes:duration>")

    ep_num = entry.get("itunes_episode", "")
    if ep_num:
        lines.append(f"    <itunes:episode>{escape_xml(ep_num)}</itunes:episode>")

    author = entry.get("author", "") or entry.get("itunes_author", "")
    if author:
        lines.append(f"    <itunes:author>{escape_xml(author)}</itunes:author>")

    explicit = entry.get("itunes_explicit", "")
    if explicit:
        lines.append(f"    <itunes:explicit>{escape_xml(explicit)}</itunes:explicit>")

    content_list = entry.get("content", [])
    if content_list:
        val = content_list[0].get("value", "")
        if val:
            lines.append(f"    <content:encoded>{cdata(val)}</content:encoded>")

    lines.append(f"    <category>{escape_xml(show_name)}</category>")

    image = entry.get("image", {})
    if isinstance(image, dict) and image.get("href"):
        lines.append(f'    <itunes:image href="{escape_xml(image["href"])}" />')

    lines.append("  </item>")
    return "\n".join(lines)


def build_feed(items: list[tuple]) -> str:
    """Build RSS XML from matched items sorted chronologically."""
    now = format_datetime(datetime.now(timezone.utc))

    header = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:itunes="http://www.itunes.apple.com/dtds/podcast-1.0.dtd"
  xmlns:content="http://purl.org/rss/1.0/modules/content/"
  xmlns:atom="http://www.w3.org/2005/Atom"
>
<channel>
  <title>This Is a Good One</title>
  <description>A curated collection of podcast episodes. Hand-picked from across shows.</description>
  <language>en-us</language>
  <lastBuildDate>{now}</lastBuildDate>
  <generator>build_feed.py</generator>"""

    body_parts = []
    for entry, good_one, show_name in items:
        body_parts.append(entry_to_item_xml(entry, show_name))

    footer = """\
</channel>
</rss>"""

    return header + "\n" + "\n".join(body_parts) + "\n" + footer


def main():
    good_ones = json.loads((SCRIPT_DIR / "good-ones.json").read_text())
    feeds_config = json.loads((SCRIPT_DIR / "source-rss-feeds.json").read_text())

    by_show: dict[str, list] = {}
    for ep in good_ones:
        by_show.setdefault(ep["show"], []).append(ep)

    feed_urls = {f["show"]: f["feed-url"] for f in feeds_config}

    all_matched: list[tuple] = []
    total_wanted = len(good_ones)

    for show_name, show_eps in by_show.items():
        url = feed_urls.get(show_name)
        if not url:
            print(f"  SKIP: No feed URL for '{show_name}'", file=sys.stderr)
            continue

        print(f"  {show_name} ({url})")
        try:
            resp = requests.get(
                url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"    FETCH FAILED: {e}", file=sys.stderr)
            continue

        feed = feedparser.parse(resp.content)
        print(f"    {len(feed.entries)} entries in feed, looking for {len(show_eps)}")

        matched, remaining = find_matches(feed, show_eps)
        for entry, go in matched:
            all_matched.append((entry, go, show_name))
            print(f"    \u2713 #{go.get('number', '?')}: {go['title']}")

        for r in remaining:
            print(f"    \u2717 #{r.get('number', '?')}: {r['title']}  (not in feed)")

    print(f"\n  Matched {len(all_matched)}/{total_wanted} episodes")

    all_matched.sort(key=lambda x: parse_pub_date(x[0]))

    rss = build_feed(all_matched)
    OUTPUT_FILE.write_text(rss, encoding="utf-8")
    print(f"  Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

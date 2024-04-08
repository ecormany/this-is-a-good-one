import json
import feedparser
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString

# Load RSS feeds URLs
with open('../source-rss-feeds.json', 'r') as feeds_file:
    rss_feeds_urls = json.load(feeds_file)

# Load the items to be matched
with open('../good-ones.json', 'r') as items_file:
    good_items = json.load(items_file)

# Dictionary to hold parsed RSS feeds to avoid multiple fetches
parsed_feeds = {}

# Fetch and parse each unique RSS feed once
for feed in rss_feeds_urls:
    parsed_feeds[feed["show"]] = feedparser.parse(feed["feed-url"])

# Function to find a matching item in the parsed feed
def find_matching_item(parsed_feed, item):
    for feed_item in parsed_feed.entries:
        if feed_item.title == item["title"]:
            return feed_item
    return None

# Accumulate matching items from feeds
matching_items = []
for item in good_items:
    if "after show" in item["title"].lower() or "members only" in item["title"].lower():
        continue
    source = item["url"]
    if source in parsed_feeds:
        matching_item = find_matching_item(parsed_feeds[source], item)
        if matching_item:
            matching_items.append(matching_item)

# Sort the matching items by their publication date
matching_items.sort(key=lambda x: datetime(*x.published_parsed[:6]))

# Create the final RSS feed
rss = Element('rss', version='2.0', attrib={'xmlns:itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd'})
channel = SubElement(rss, 'channel')

for item in matching_items:
    item_element = SubElement(channel, 'item')
    title = SubElement(item_element, 'title')
    title.text = item.title
    pubDate = SubElement(item_element, 'pubDate')
    pubDate.text = item.published
    description = SubElement(item_element, 'description')
    description.text = item.description if 'description' in item else 'No description available'
    link = SubElement(item_element, 'link')
    link.text = item.link

# Convert the ElementTree to a string and format it with minidom for readability
rss_str = tostring(rss, 'utf-8')
pretty_rss_str = parseString(rss_str).toprettyxml(indent="  ")

# Output the pretty formatted RSS feed to a file
output_path = './build/final_rss_feed.xml'
with open(output_path, 'w') as output_file:
    output_file.write(pretty_rss_str)

output_path

import re
import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

# Pattern to find item card structures in SSR HTML.
# This needs to be robust enough to handle the Vinted SSR structure.
# Based on discovery, item links are <a href="/items/<id>-...">
# And photos are <img> elements within the same card.
# The card itself seems to have a specific structure.

# Simple regex to find item cards. A more robust solution might need a proper HTML parser,
# but for a one-request SSR parse, this regex might be sufficient if the structure is consistent.
# For now, let's look for item URLs as anchor points.

ITEM_CARD_PATTERN = re.compile(
    r'<div[^>]*data-testid="item-card"[^>]*>.*?<a[^>]*href="(?P<url>/items/(?P<id>\d+)-[^"]*)"[^>]*>.*?<img[^>]*src="(?P<photo_url>[^"]*)"[^>]*>.*?</div>',
    re.DOTALL | re.IGNORECASE
)

# This pattern is too restrictive and might fail. Let's start with a simpler extraction approach.
# Since we need to prove it, let's use a combination of regex and structure.

from html.parser import HTMLParser

class VintedCatalogHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self.current_item = None
        self.in_item_card = False
        self.in_title = False
        self.in_price = False
        self.current_tag = None
        # Diagnostics
        self.diagnostics = {
            "card_start_count": 0,
            "card_end_count": 0,
            "cards_with_item_link": 0,
            "cards_with_photo": 0,
            "cards_with_title": 0,
            "cards_with_price": 0,
            "cards_emitted": 0,
        }

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        attr_dict = dict(attrs)

        # Support both new and test structures
        if tag == 'div' and ('new-item-box' in attr_dict.get('class', '') or attr_dict.get('data-testid') == 'item-card'):
            self.in_item_card = True
            self.diagnostics["card_start_count"] += 1
            self.current_item = {'photo_url': '', 'title': 'Unknown', 'price': 0.0, 'currency': 'PLN'}

        if self.in_item_card:
            if tag == 'a' and 'href' in attr_dict and '/items/' in attr_dict['href']:
                url = attr_dict['href']
                self.current_item['path'] = url
                self.current_item['url'] = f"https://www.vinted.pl{url}"
                match = re.search(r'/items/(\d+)-', url)
                self.current_item['id'] = match.group(1) if match else "0"
                self.diagnostics["cards_with_item_link"] += 1

            if tag == 'img' and 'src' in attr_dict:
                self.current_item['photo_url'] = attr_dict['src']
                self.diagnostics["cards_with_photo"] += 1

            # Support both new and test selectors
            class_attr = attr_dict.get('class', '')
            testid_attr = attr_dict.get('data-testid', '')

            if tag == 'div' and ('item-title' in class_attr or testid_attr == 'item-title'):
                self.in_title = True
                self.diagnostics["cards_with_title"] += 1

            if tag == 'div' and ('item-price' in class_attr or testid_attr == 'item-price'):
                self.in_price = True
                self.diagnostics["cards_with_price"] += 1
    def handle_data(self, data):
        if self.in_item_card:
            if self.in_title:
                self.current_item['title'] = data.strip()

            if self.in_price:
                price_cleaned = re.sub(r'[^0-9.]', '', data.replace(',', '.'))
                try:
                    self.current_item['price'] = float(price_cleaned)
                except ValueError:
                    pass

    def handle_endtag(self, tag):
        if tag == 'div' and self.in_item_card:
            if self.in_title:
                self.in_title = False
            elif self.in_price:
                self.in_price = False
            else:
                self.items.append(self.current_item)
                self.diagnostics["cards_emitted"] += 1
                self.in_item_card = False
                self.current_item = None
                self.diagnostics["card_end_count"] += 1

def parse_catalog_ssr_html(html: str) -> List[Dict[str, Any]]:
    parser = VintedCatalogHTMLParser()
    parser.feed(html)
    return parser.items

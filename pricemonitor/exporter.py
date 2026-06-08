#!/usr/bin/env python3
"""Prometheus exporter for price monitor data. Serves /metrics for Grafana."""

import json
import os
import re
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

import requests
import yaml

CONFIG_FILE = os.path.expanduser("~/.hermes/.amzn-config.yaml")
HISTORY_FILE = os.path.expanduser("~/.hermes/logs/amzn_check_history.jsonl")
PORT = int(os.environ.get("PRICE_EXPORTER_PORT", 9800))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

_products = []
_latest_prices = {}


def load_config():
    with open(CONFIG_FILE) as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("products", [])


def extract_price(html):
    for m in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(m.group(1))
            offers = data.get("offers", {})
            if isinstance(offers, dict):
                p = offers.get("price")
                if p:
                    return float(p)
            elif isinstance(offers, list):
                for o in offers:
                    p = o.get("price")
                    if p:
                        return float(p)
        except Exception:
            pass
    m = re.search(
        r'<span[^>]*class="[^"]*a-offscreen[^"]*"[^>]*>\$?([0-9,]+\.?[0-9]*)</span>',
        html, re.IGNORECASE,
    )
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def scrape():
    global _latest_prices
    session = requests.Session()
    session.headers.update(HEADERS)
    now = datetime.now().timestamp()
    for p in _products:
        try:
            r = session.get(p["url"], timeout=30)
            r.raise_for_status()
            price = extract_price(r.text)
            if price is not None:
                _latest_prices[p["name"]] = (price, now)
        except Exception:
            pass


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        scrape()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        lines = [
            "# HELP amazon_product_price Current product price in USD",
            "# TYPE amazon_product_price gauge",
        ]
        for name, (price, ts) in sorted(_latest_prices.items()):
            safe = name.replace(" ", "_").replace("-", "_").lower()
            lines.append(f'amazon_product_price{{product="{safe}",name="{name}"}} {price} {int(ts * 1000)}')
        self.wfile.write("\n".join(lines).encode())

    def log_message(self, fmt, *args):
        pass


def main():
    global _products
    _products = load_config()
    if not _products:
        print("No products configured.")
        sys.exit(1)

    server = HTTPServer(("0.0.0.0", PORT), MetricsHandler)
    print(f"Prometheus exporter running on http://0.0.0.0:{PORT}/metrics")
    print(f"Monitoring {len(_products)} products")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()

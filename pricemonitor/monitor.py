#!/usr/bin/env python3
"""
Amazon Price Monitor Script
Fetches and tracks price changes for multiple Amazon products.
"""

import json
import os
import re
import sys
import time
from datetime import datetime

import requests
import yaml

CONFIG_FILE = os.path.expanduser("~/.hermes/.amzn-config.yaml")
DEFAULT_CHECK_INTERVAL = 15  # minutes
MAX_LOG_SIZE = 1 * 1024 * 1024  # 1 MB

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def load_config():
    try:
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f)
        if not isinstance(config, dict):
            raise ValueError("Config must be a dictionary")
        products = config.get("products", [])
        if not isinstance(products, list) or not products:
            raise ValueError("Config must contain a non-empty 'products' list")
        for p in products:
            if not p.get("asin") or not p.get("url"):
                raise ValueError(f"Each product must have 'asin' and 'url': {p}")
        return config
    except Exception as e:
        print(f"Error loading config: {e}")
        print("Using default config")
        return {
            "products": [
                {
                    "url": "https://www.amazon.com/gp/product/B08ZL6XD9H",
                    "asin": "B08ZL6XD9H",
                    "name": "ZOTAC RTX 3090",
                }
            ]
        }


def extract_price_from_html(html):
    if not html:
        return None

    # Strategy 1: JSON-LD structured data (most reliable)
    try:
        for match in re.finditer(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            html,
            re.DOTALL | re.IGNORECASE,
        ):
            data = json.loads(match.group(1))
            offers = data.get("offers", {})
            if isinstance(offers, dict):
                price = offers.get("price")
                if price:
                    return float(price)
            elif isinstance(offers, list):
                for offer in offers:
                    price = offer.get("price")
                    if price:
                        return float(price)
    except Exception:
        pass

    # Strategy 2: a-offscreen span (full price text e.g. "$2,095.00")
    try:
        m = re.search(
            r'<span[^>]*class="[^"]*a-offscreen[^"]*"[^>]*>\$?([0-9,]+\.?[0-9]*)</span>',
            html,
            re.IGNORECASE,
        )
        if m:
            return float(m.group(1).replace(",", ""))
    except Exception:
        pass

    # Strategy 3: a-price-whole + a-price-fraction spans
    try:
        m = re.search(
            r'<span[^>]*class="[^"]*a-price-whole[^"]*"[^>]*>([0-9,]+)\s*<span[^>]*class="[^"]*a-price-fraction[^"]*"[^>]*>([0-9]+)',
            html,
            re.IGNORECASE,
        )
        if m:
            whole = m.group(1).replace(",", "")
            fraction = m.group(2).zfill(2)[:2]
            return float(f"{whole}.{fraction}")
    except Exception:
        pass

    return None


def fetch_price(session, product_url, product_name, product_asin):
    try:
        response = session.get(product_url, timeout=30)
        response.raise_for_status()
        price = extract_price_from_html(response.text)
        result = {
            "product_name": product_name,
            "asin": product_asin,
            "price": price,
            "timestamp": datetime.now().isoformat(),
            "url": product_url,
            "html_length": len(response.text),
        }
        if price is None:
            result["debug_preview"] = response.text[:500]
        return result
    except Exception as e:
        return {
            "product_name": product_name,
            "asin": product_asin,
            "price": None,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
            "url": product_url,
        }


def rotate_log(log_path, max_size):
    try:
        if os.path.exists(log_path) and os.path.getsize(log_path) > max_size:
            base, ext = os.path.splitext(log_path)
            i = 1
            while os.path.exists(f"{base}.{i}{ext}"):
                i += 1
            os.rename(log_path, f"{base}.{i}{ext}")
    except Exception as e:
        print(f"  Warning: log rotation failed: {e}")


def main():
    config = load_config()
    products = config.get("products", [])
    check_interval = config.get("check_interval_minutes", DEFAULT_CHECK_INTERVAL)

    log_dir = os.path.expanduser(config.get("log_dir", "~/.hermes/logs"))
    log_file_name = config.get("log_file", "amzn_price_history.json")
    log_file = os.path.join(log_dir, log_file_name)
    history_file = os.path.join(log_dir, "amzn_check_history.jsonl")

    os.makedirs(log_dir, exist_ok=True)
    rotate_log(log_file, MAX_LOG_SIZE)
    rotate_log(history_file, MAX_LOG_SIZE)

    tracking = {}
    for prod in products:
        asin = prod.get("asin")
        tracking[asin] = {
            "name": prod.get("name", asin),
            "url": prod.get("url"),
            "interval": prod.get("check_interval_minutes", check_interval),
        }

    print("=" * 70)
    print("Amazon Price Monitor")
    print(f"Config: {CONFIG_FILE}")
    print(f"Check interval: {check_interval} minutes")
    print("=" * 70)
    print()
    for asin, info in tracking.items():
        print(f"  - {info['name']} ({asin}): {info['url']}")
    print()

    last_prices = {}
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        while True:
            for asin, info in tracking.items():
                print(f"Fetching: {info['name']} ({asin})...")
                result = fetch_price(session, info["url"], info["name"], asin)
                ts = result.get("timestamp")
                price = result.get("price")

                if "error" in result:
                    print(f"[{ts}] {info['name']}: ERROR - {result['error']}")
                    continue

                if price is None:
                    print(f"[{ts}] {info['name']}: Could not extract price")
                    debug = result.get("debug_preview", "")
                    if debug:
                        print(f"  HTML preview: {debug[:300]}")
                    continue

                old_price = last_prices.get(asin)
                if old_price is None:
                    print(f"[{ts}] {info['name']}: ${price:.2f} (initial)")
                elif price != old_price:
                    change = price - old_price
                    print(
                        f"[{ts}] {info['name']}: ${price:.2f} "
                        f"(was ${old_price:.2f}, change: ${change:+.2f})"
                    )
                    try:
                        with open(log_file, "a") as f:
                            f.write(
                                f"[{ts}] {info['name']}: "
                                f"${old_price:.2f} -> ${price:.2f}\n"
                            )
                    except OSError as e:
                        print(f"  Warning: failed to write log: {e}")
                else:
                    print(f"[{ts}] {info['name']}: ${price:.2f} (unchanged)")

                try:
                    with open(history_file, "a") as f:
                        f.write(json.dumps({
                            "ts": ts,
                            "product": info["name"],
                            "asin": asin,
                            "price": price,
                        }) + "\n")
                except OSError as e:
                    print(f"  Warning: failed to write history: {e}")

                last_prices[asin] = price
                time.sleep(2)

            print("-" * 40)
            time.sleep(check_interval * 60)

    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

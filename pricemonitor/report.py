#!/usr/bin/env python3
"""Generate an HTML price tracking dashboard from config and price history."""

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, date
from html import escape

import requests
import yaml

CONFIG_FILE = os.path.expanduser("~/.hermes/.amzn-config.yaml")
CHANGE_LOG = os.path.expanduser("~/.hermes/logs/amzn_price_history.json")
HISTORY_FILE = os.path.expanduser("~/.hermes/logs/amzn_check_history.jsonl")
OUTPUT_FILE = os.path.expanduser("~/.hermes/logs/price-dashboard.html")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def load_config():
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f) or {"products": []}


def fetch_current_prices(products):
    session = requests.Session()
    session.headers.update(HEADERS)
    results = []
    for p in products:
        url = p["url"]
        name = p.get("name", p.get("asin", "Unknown"))
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            price = None
            # JSON-LD
            for m in re.finditer(
                r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                r.text, re.DOTALL | re.IGNORECASE,
            ):
                data = json.loads(m.group(1))
                offers = data.get("offers", {})
                if isinstance(offers, dict):
                    price = offers.get("price")
                elif isinstance(offers, list):
                    price = next((o.get("price") for o in offers if o.get("price")), None)
                if price:
                    price = float(price)
                    break
            # a-offscreen
            if price is None:
                m = re.search(
                    r'<span[^>]*class="[^"]*a-offscreen[^"]*"[^>]*>\$?([0-9,]+\.?[0-9]*)</span>',
                    r.text, re.IGNORECASE,
                )
                if m:
                    price = float(m.group(1).replace(",", ""))
            results.append({"name": name, "url": url, "price": price, "ok": price is not None})
        except Exception as e:
            results.append({"name": name, "url": url, "price": None, "ok": False, "error": str(e)})
    return results


def read_check_history():
    entries = []
    if not os.path.exists(HISTORY_FILE):
        return entries
    with open(HISTORY_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def read_change_log():
    entries = []
    if not os.path.exists(CHANGE_LOG):
        return entries
    with open(CHANGE_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = re.match(r'\[(.+?)\]\s+(.+?):\s+\$([\d.]+)\s*->\s*\$([\d.]+)', line)
            if m:
                entries.append({
                    "ts": m.group(1),
                    "product": m.group(2),
                    "old": float(m.group(3)),
                    "new": float(m.group(4)),
                })
    return entries


def build_daily_history(entries):
    daily = defaultdict(lambda: defaultdict(list))
    for e in entries:
        d = e["ts"][:10]
        daily[e["product"]][d].append(e["price"])
    summary = {}
    for prod, days in daily.items():
        summary[prod] = []
        for d, prices in sorted(days.items()):
            summary[prod].append({
                "date": d,
                "min": min(prices),
                "max": max(prices),
                "last": prices[-1],
                "checks": len(prices),
            })
    return summary


def generate_html(current_prices, daily_history, change_entries):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    product_cards = ""
    for p in current_prices:
        status = "ok" if p.get("ok") else ("error" if p.get("error") else "unknown")
        err = escape(p.get("error", "")) if not p.get("ok") else ""
        asin_tag = ""
        u = p.get("url", "")
        if "/dp/" in u:
            asin_tag = u.split("/dp/")[-1].split("?")[0]
        elif "/product/" in u:
            asin_tag = u.rstrip("/").split("/")[-1]
        product_cards += f"""
        <div class="card {status}">
            <div class="card-header">
                <a href="{escape(u)}" target="_blank">{escape(p['name'])}</a>
                <span class="tag">{escape(asin_tag)}</span>
            </div>
            <div class="price">{'$%.2f' % p['price'] if p['price'] else '<span class="na">N/A</span>'}</div>
            {f'<div class="error-msg">{err}</div>' if err else ''}
        </div>"""

    all_product_names = [p["name"] for p in current_prices if p["price"] is not None]
    colors = ['#58a6ff', '#3fb950', '#d29922', '#f85149', '#bc8cff', '#f0883e']

    # Build daily chart datasets
    chart_datasets_json = []
    chart_labels = set()
    product_daily_data = {}
    for prod, days in daily_history.items():
        if prod not in all_product_names:
            continue
        labels = [d["date"] for d in days]
        prices = [d["last"] for d in days]
        chart_labels.update(labels)
        product_daily_data[prod] = {"labels": labels, "prices": prices}

    sorted_labels = sorted(chart_labels)
    for i, prod in enumerate(all_product_names):
        if prod in product_daily_data:
            data = product_daily_data[prod]
            padded = []
            for lbl in sorted_labels:
                if lbl in data["labels"]:
                    idx = data["labels"].index(lbl)
                    padded.append(data["prices"][idx])
                elif padded:
                    padded.append(padded[-1])
                else:
                    padded.append(None)
            chart_datasets_json.append({
                "label": prod,
                "data": padded,
                "borderColor": colors[i % len(colors)],
                "backgroundColor": colors[i % len(colors)] + "33",
                "fill": False,
                "tension": 0.2,
                "spanGaps": True,
            })

    chart_labels_json = json.dumps(sorted_labels)
    chart_datasets_json_str = json.dumps(chart_datasets_json)

    # Daily summary table
    daily_rows = ""
    if daily_history:
        all_dates = sorted({d for days in daily_history.values() for d in [day["date"] for day in days]}, reverse=True)
        for d in all_dates[:30]:
            daily_rows += f"<tr><td>{escape(d)}</td>"
            for prod in all_product_names:
                days_list = daily_history.get(prod, [])
                match = next((day for day in days_list if day["date"] == d), None)
                if match:
                    daily_rows += f"""
                    <td>
                        <span class="price-cell">${match['last']:.2f}</span>
                        <span class="range-cell">H ${match['max']:.2f} L ${match['min']:.2f}</span>
                        <span class="checks-cell">{match['checks']} checks</span>
                    </td>"""
                else:
                    daily_rows += "<td class='na'>-</td>"
            daily_rows += "</tr>"
    else:
        daily_rows = f"<tr><td colspan='{1 + len(all_product_names)}' class='na' style='text-align:center;padding:24px;'>No history yet — data will appear as the monitor runs</td></tr>"

    # Change log table
    change_rows = ""
    if change_entries:
        for h in reversed(change_entries[-50:]):
            change_rows += f"""
            <tr>
                <td>{escape(h['ts'])}</td>
                <td>{escape(h['product'])}</td>
                <td class="old">${h['old']:.2f}</td>
                <td class="new">${h['new']:.2f}</td>
                <td class="diff {'up' if h['new'] > h['old'] else 'down'}">{'+' if h['new'] > h['old'] else ''}{h['new'] - h['old']:.2f}</td>
            </tr>"""

    product_count = len(all_product_names)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Price Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: #0d1117; color: #c9d1d9; padding: 24px; min-height: 100vh;
}}
.header {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #30363d;
}}
.header h1 {{ font-size: 20px; font-weight: 600; color: #f0f6fc; }}
.header .ts {{ color: #8b949e; font-size: 13px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; margin-bottom: 32px; }}
.card {{
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 20px; position: relative; transition: border-color .2s;
}}
.card:hover {{ border-color: #58a6ff; }}
.card.error {{ border-left: 3px solid #f85149; }}
.card.ok {{ border-left: 3px solid #3fb950; }}
.card-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; gap: 8px; }}
.card-header a {{ color: #58a6ff; text-decoration: none; font-size: 14px; font-weight: 500; line-height: 1.3; }}
.card-header a:hover {{ text-decoration: underline; }}
.tag {{ font-size: 11px; color: #8b949e; background: #21262d; padding: 2px 6px; border-radius: 4px; white-space: nowrap; }}
.price {{ font-size: 28px; font-weight: 700; color: #f0f6fc; }}
.price .na {{ color: #8b949e; font-weight: 400; }}
.error-msg {{ color: #f85149; font-size: 12px; margin-top: 8px; }}
.section {{ margin-bottom: 24px; }}
.section h2 {{ font-size: 16px; font-weight: 600; color: #f0f6fc; margin-bottom: 12px; }}
.section-desc {{ color: #8b949e; font-size: 13px; margin-bottom: 12px; }}
.chart-container {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; }}
.chart-container-small {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin-bottom: 24px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ text-align: left; padding: 8px 12px; border-bottom: 2px solid #30363d; color: #8b949e; font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: .05em; white-space: nowrap; }}
td {{ padding: 8px 12px; border-bottom: 1px solid #21262d; vertical-align: middle; }}
tr:hover td {{ background: #1c2128; }}
.old {{ color: #f0883e; }}
.new {{ color: #3fb950; }}
.diff {{ font-weight: 600; }}
.diff.up {{ color: #f85149; }}
.diff.down {{ color: #3fb950; }}
.na {{ color: #8b949e; text-align: center; }}
.price-cell {{ display: block; font-weight: 600; color: #f0f6fc; font-size: 14px; }}
.range-cell {{ display: block; font-size: 11px; color: #8b949e; }}
.checks-cell {{ display: block; font-size: 10px; color: #484f58; }}
</style>
</head>
<body>
<div class="header">
    <h1>Price Dashboard</h1>
    <span class="ts">Updated {escape(now)}</span>
</div>

<div class="section">
    <h2>Current Prices</h2>
    <div class="cards">{product_cards}</div>
</div>

<div class="section">
    <h2>Daily Price Trend</h2>
    <div class="section-desc">Closing price per day</div>
    <div class="chart-container">
        <canvas id="trendChart" height="300"></canvas>
    </div>
</div>

<div class="section">
    <h2>Daily Summary</h2>
    <div class="section-desc">Last price · High · Low per day</div>
    <div class="chart-container-small" style="overflow-x:auto">
        <table>
            <thead><tr><th>Date</th>{"".join(f'<th>{escape(p)}</th>' for p in all_product_names)}</tr></thead>
            <tbody>{daily_rows}</tbody>
        </table>
    </div>
</div>

<div class="section">
    <h2>Price Changes</h2>
    <table>
        <thead><tr><th>Time</th><th>Product</th><th>Old</th><th>New</th><th>Change</th></tr></thead>
        <tbody>{"<tr><td colspan='5' class='na' style='text-align:center;padding:24px;'>No changes recorded yet</td></tr>" if not change_rows else change_rows}</tbody>
    </table>
</div>

<script>
const ctx = document.getElementById('trendChart').getContext('2d');
new Chart(ctx, {{
    type: 'line',
    data: {{
        labels: {chart_labels_json},
        datasets: {chart_datasets_json_str}
    }},
    options: {{
        responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
            legend: {{ labels: {{ color: '#c9d1d9' }} }},
            tooltip: {{
                callbacks: {{
                    label: ctx => ctx.dataset.label + ': $' + ctx.parsed.y.toFixed(2)
                }}
            }}
        }},
        scales: {{
            y: {{
                ticks: {{ callback: v => '$' + v.toFixed(0), color: '#8b949e' }},
                grid: {{ color: '#21262d' }}
            }},
            x: {{
                ticks: {{ color: '#8b949e' }},
                grid: {{ display: false }}
            }}
        }}
    }}
}});
</script>
</body>
</html>"""

    return html


def main():
    config = load_config()
    products = config.get("products", [])
    if not products:
        print("No products configured.")
        sys.exit(1)

    print("Fetching current prices...")
    current = fetch_current_prices(products)

    print("Reading check history...")
    history_entries = read_check_history()
    daily_history = build_daily_history(history_entries)

    print("Reading change log...")
    changes = read_change_log()

    html = generate_html(current, daily_history, changes)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        f.write(html)

    print(f"Dashboard written to {OUTPUT_FILE}")
    print(f"  Products: {len(current)}")
    print(f"  Check history entries: {len(history_entries)}")
    print(f"  Price changes: {len(changes)}")


if __name__ == "__main__":
    main()

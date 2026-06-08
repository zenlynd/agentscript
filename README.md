# agentscript

Scripts for AI agents.

## pricemonitor

Track Amazon product prices and view them in a dashboard.

### monitor.py

Continuously fetches prices for products listed in `~/.hermes/.amzn-config.yaml`.

```bash
python3 ~/.hermes/scripts/pricemonitor/monitor.py
```

Logs every check to `~/.hermes/logs/amzn_check_history.jsonl` and records price changes to `~/.hermes/logs/amzn_price_history.json`.

### report.py

Generates an HTML dashboard from the check history.

```bash
python3 ~/.hermes/scripts/pricemonitor/report.py
```

Output: `~/.hermes/logs/price-dashboard.html` — dark-themed page with current prices, daily trend chart, and change history.

### exporter.py

Prometheus metrics exporter for Grafana ingestion.

```bash
python3 ~/.hermes/scripts/pricemonitor/exporter.py
```

Serves `GET /metrics` on port 9800 (`PRICE_EXPORTER_PORT` to change). Exposes `amazon_product_price` gauge metrics with `product` and `name` labels.

#### Prometheus config (`prometheus.yml`)

```yaml
scrape_configs:
  - job_name: "amazon-prices"
    scrape_interval: 15m
    static_configs:
      - targets: ["localhost:9800"]
```

#### Grafana

Import `pricemonitor/grafana-dashboard.json` for a pre-built dashboard with current price stats and a trend chart. Requires Prometheus data source.

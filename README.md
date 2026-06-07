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

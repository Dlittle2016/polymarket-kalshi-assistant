# Polymarket → Kalshi Assistant v1

Read-only Streamlit prototype for trader activity, candidate market matching, price comparison, and stake limits.

## Run
Python 3.10+:
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Scope and safeguards
- No Kalshi account connection or live order placement.
- Market title similarity is a screening aid, not proof of equivalent settlement.
- Fees are manually estimated; slippage and actual fee schedules may differ.
- Always verify market rules and executable prices. A trade can lose its entire stake.

Public endpoints used:
- `https://data-api.polymarket.com/trades`
- `https://api.elections.kalshi.com/trade-api/v2/markets`

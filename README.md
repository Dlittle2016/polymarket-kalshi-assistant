# Polymarket → Kalshi Assistant v2

Replace the repository's `app.py` and `requirements.txt` with these files. This version retrieves multiple pages of open Kalshi markets (up to the selected page depth), filters and ranks keyword matches, and includes wallet trade lookup and a manual risk calculator.

Run with `pip install -r requirements.txt` then `streamlit run app.py`.

Read-only prototype: no account authentication or order placement. Similar titles do not prove identical settlement conditions. Verify full rules, deadlines, settlement sources, live executable prices, fees, and slippage. All trades can lose the full stake.

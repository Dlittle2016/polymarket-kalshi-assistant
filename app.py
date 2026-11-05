import re
import requests
import streamlit as st
from datetime import datetime, timezone

st.set_page_config(page_title="Polymarket → Kalshi Assistant", page_icon="📊", layout="wide")

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
POLY_BASE = "https://data-api.polymarket.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketResearchAssistant/6.0)"}

TOPICS = {
    "Federal Reserve": ["federal reserve", "fomc", "fed funds", "federal funds rate", "interest rate", "rate decision", "rate cut", "rate hike", "rate increase", "rate reduction", "monetary policy", "fed chair", "fed meeting"],
    "Inflation": ["inflation", "cpi", "core cpi", "pce", "ppi", "price index"],
    "Employment": ["unemployment", "nonfarm payrolls", "jobs report", "jobless claims", "employment", "labor market", "payrolls", "job creation"],
    "Economic Growth": ["gdp", "economic growth", "recession", "contraction", "expansion"],
    "Consumer Economy": ["retail sales", "consumer spending", "consumer confidence", "consumer sentiment", "personal income", "personal spending"],
    "Housing": ["housing starts", "home sales", "home prices", "housing market", "building permits", "mortgage rates"],
    "Treasury & Bonds": ["treasury yields", "10-year yield", "2-year yield", "bond yield", "treasury bonds", "treasury rate"],
    "Business & Manufacturing": ["manufacturing", "industrial production", "pmi", "ism", "business activity", "factory orders", "durable goods"],
}


def get_json(url, params=None, timeout=20):
    response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.json()


def norm(value):
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def phrase_in(text, phrase):
    text = " " + re.sub(r"[^a-z0-9]+", " ", norm(text)) + " "
    phrase = " " + re.sub(r"[^a-z0-9]+", " ", norm(phrase)) + " "
    return phrase in text


def topics_for(text):
    found = []
    for topic, phrases in TOPICS.items():
        if any(phrase_in(text, p) for p in phrases):
            found.append(topic)
    return found


@st.cache_data(ttl=45, show_spinner=False)
def fetch_kalshi_events(max_pages=10):
    all_events, cursor = [], None
    for _ in range(max_pages):
        params = {"status": "open", "limit": 200, "with_nested_markets": "true"}
        if cursor:
            params["cursor"] = cursor
        payload = get_json(f"{KALSHI_BASE}/events", params=params)
        events = payload.get("events", []) or []
        all_events.extend(events)
        cursor = payload.get("cursor")
        if not cursor:
            break
    return all_events


@st.cache_data(ttl=120, show_spinner=False)
def fetch_leaderboard(period, category, sort_by, limit):
    params = {"time_period": period.lower(), "category": category.lower(), "sort_by": sort_by.upper(), "limit": int(limit)}
    payload = get_json(f"{POLY_BASE}/v2/leaderboard", params=params)
    rows = payload.get("data", [])
    if isinstance(rows, dict):
        rows = rows.get("leaderboard", rows.get("data", []))
    return rows if isinstance(rows, list) else [], payload.get("pagination", {})


@st.cache_data(ttl=90, show_spinner=False)
def fetch_wallet_stats(wallet):
    payload = get_json(f"{POLY_BASE}/v2/user-stats", params={"user": wallet})
    return payload.get("data")


@st.cache_data(ttl=60, show_spinner=False)
def fetch_wallet_positions(wallet, status, limit=100):
    payload = get_json(f"{POLY_BASE}/v2/positions", params={"user": wallet, "status": status, "limit": limit, "sort_by": "REALIZED_PNL" if status == "CLOSED" else "CURRENT_VALUE", "sort_direction": "DESC"})
    return payload.get("data", [])


def money(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def wallet_of(row):
    return row.get("user_id") or row.get("proxy_wallet") or row.get("proxyWallet") or row.get("address") or ""


def display_leader(row):
    return row.get("user_name") or row.get("username") or row.get("name") or (wallet_of(row)[:10] + "…")


st.title("📊 Polymarket → Kalshi Trading Assistant")
st.caption("Version 6 · Public market research · Read-only · Manual approval only · No automatic trading")

with st.sidebar:
    st.subheader("Research settings")
    bankroll = st.number_input("Simulated bankroll ($)", min_value=1.0, max_value=100000.0, value=55.0, step=5.0)
    st.caption("This is a planning value only. The app does not connect to your Kalshi account or place orders.")

market_tab, trader_tab, wallet_tab, calculator_tab = st.tabs(["Economic Markets", "Trader Leaderboard", "Wallet Inspector", "Payoff Calculator"])

with market_tab:
    st.subheader("Open Kalshi economic markets")
    c1, c2 = st.columns([1, 2])
    with c1:
        selected_topic = st.selectbox("Economic category", ["All economic topics"] + list(TOPICS.keys()))
    with c2:
        keyword = st.text_input("Optional keyword", placeholder="e.g. Fed, CPI, Powell, GDP")
    if st.button("Search Kalshi markets", type="primary", key="search_markets"):
        st.session_state["run_market_search"] = True
    if st.session_state.get("run_market_search"):
        try:
            with st.spinner("Loading Kalshi events and nested markets..."):
                events = fetch_kalshi_events()
            matches = []
            for event in events:
                event_title = event.get("title", "")
                event_subtitle = event.get("subtitle", "")
                event_category = event.get("category", "")
                markets = event.get("markets", []) or []
                for market in markets:
                    title = market.get("title", "")
                    searchable = " ".join([event_title, event_subtitle, event_category, title, market.get("subtitle", "")])
                    found_topics = topics_for(searchable)
                    if selected_topic != "All economic topics" and selected_topic not in found_topics:
                        continue
                    if selected_topic == "All economic topics" and not found_topics:
                        continue
                    if keyword and not phrase_in(searchable, keyword):
                        # Allow common abbreviations and short search terms as token matches.
                        tokens = set(re.findall(r"[a-z0-9]+", norm(searchable)))
                        if norm(keyword) not in tokens:
                            continue
                    matches.append((event, market, found_topics))
            st.success(f"Retrieved {len(events):,} events · Found {len(matches):,} matching markets")
            if not matches:
                st.info("No matching markets found. Try a broader category or a shorter keyword.")
            for event, market, found_topics in matches[:60]:
                with st.container(border=True):
                    st.markdown(f"**{market.get('title') or event.get('title') or 'Untitled market'}**")
                    st.caption(f"{event.get('title', '')} · {' / '.join(found_topics)}")
                    cols = st.columns(3)
                    cols[0].metric("YES ask", market.get("yes_ask_dollars") or (f"{market.get('yes_ask')}¢" if market.get("yes_ask") is not None else "—"))
                    cols[1].metric("NO ask", market.get("no_ask_dollars") or (f"{market.get('no_ask')}¢" if market.get("no_ask") is not None else "—"))
                    cols[2].metric("Ticker", market.get("ticker", "—"))
                    if market.get("close_time"):
                        st.caption(f"Closes: {market.get('close_time')}")
                    if market.get("rules_primary"):
                        with st.expander("Settlement rules"):
                            st.write(market.get("rules_primary"))
        except Exception as exc:
            st.error(f"Kalshi market search failed: {exc}")
            st.caption("If this continues, copy the full error text so we can diagnose the API response.")

with trader_tab:
    st.subheader("Find traders by reported Polymarket performance")
    st.warning("Leaderboard P&L is a ranking signal, not proof of a repeatable edge. Daily/weekly/monthly results can include mark-to-market changes; all-time P&L is realized-only. Volume is reported in shares, not dollars.")
    a, b, c, d = st.columns(4)
    with a:
        period = st.selectbox("Performance window", ["ALL", "MONTH", "WEEK", "DAY"], index=0)
    with b:
        category = st.selectbox("Category", ["OVERALL", "ECONOMICS", "FINANCE", "CRYPTO", "POLITICS", "SPORTS", "TECH", "WEATHER", "CULTURE", "MENTIONS"])
    with c:
        rank_by = st.selectbox("Rank by", ["PNL", "VOLUME"])
    with d:
        row_limit = st.selectbox("Rows", [10, 25, 50], index=1)
    if st.button("Load Polymarket leaderboard", type="primary", key="load_leaderboard"):
        st.session_state["run_leaderboard"] = True
    if st.session_state.get("run_leaderboard"):
        try:
            with st.spinner("Loading the public Polymarket leaderboard..."):
                leaders, pagination = fetch_leaderboard(period, category, rank_by, row_limit)
            st.caption(f"Showing {len(leaders)} leaderboard entries · Retrieved {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
            if not leaders:
                st.info("The leaderboard returned no rows. Try another time window or category.")
            for row in leaders:
                wallet = wallet_of(row)
                with st.container(border=True):
                    left, right = st.columns([3, 2])
                    with left:
                        rank = row.get("rank", "—")
                        st.markdown(f"**#{rank} · {display_leader(row)}**")
                        st.caption(wallet if wallet else "Wallet address not supplied by API")
                        if row.get("verified") or row.get("verified_badge"):
                            st.caption("✓ Polymarket verified profile")
                    with right:
                        st.metric("P&L", money(row.get("pnl")))
                        st.metric("Volume (shares)", f"{float(row.get('volume', row.get('vol', 0)) or 0):,.0f}")
                    if wallet:
                        if st.button("Inspect this wallet", key=f"inspect_{wallet}"):
                            st.session_state["selected_wallet"] = wallet
                            st.session_state["selected_wallet_name"] = display_leader(row)
                            st.session_state["active_tab_hint"] = "wallet"
                            st.info("Wallet selected. Open the Wallet Inspector tab to review its positions and profile data.")
            if pagination.get("has_more"):
                st.caption("More leaderboard entries are available through cursor pagination; this version displays the first page only.")
        except Exception as exc:
            st.error(f"Polymarket leaderboard request failed: {exc}")
            st.caption("The current Polymarket API uses the v2 leaderboard. Copy the full error text if this fails.")

with wallet_tab:
    st.subheader("Inspect a Polymarket wallet")
    default_wallet = st.session_state.get("selected_wallet", "")
    wallet = st.text_input("Wallet address", value=default_wallet, placeholder="0x…")
    if st.button("Analyze wallet", type="primary", key="analyze_wallet"):
        st.session_state["wallet_to_analyze"] = wallet.strip()
    target = st.session_state.get("wallet_to_analyze", "")
    if target:
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", target):
            st.error("Enter a valid 42-character Polygon wallet address beginning with 0x.")
        else:
            try:
                with st.spinner("Loading wallet profile and positions..."):
                    stats = fetch_wallet_stats(target)
                    open_positions = fetch_wallet_positions(target, "OPEN", 100)
                    closed_positions = fetch_wallet_positions(target, "CLOSED", 100)
                if not stats:
                    st.info("Polymarket did not return a profile record for this wallet. It may still have on-chain activity.")
                else:
                    pnl_data = stats.get("all_time_pnl") or {}
                    realized = pnl_data.get("realized_pnl")
                    if realized is None:
                        market_pnl = pnl_data.get("realized_market_pnl") or 0
                        combo_pnl = pnl_data.get("realized_combo_pnl") or 0
                        realized = market_pnl + combo_pnl
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("All-time realized P&L", money(realized))
                    m2.metric("Markets traded", f"{stats.get('trades', 0):,}")
                    m3.metric("Biggest win", money(stats.get("biggest_win")))
                    m4.metric("Current open positions", f"{len(open_positions):,}")
                    st.caption("These are API-reported profile statistics. Markets traded is not the same as number of fills; the API does not provide a reliable win-rate field here.")
                st.markdown("#### Current open positions")
                if not open_positions:
                    st.info("No open positions were returned.")
                for pos in open_positions[:50]:
                    with st.container(border=True):
                        st.markdown(f"**{pos.get('title') or pos.get('name') or 'Untitled market'}**")
                        st.write(f"Outcome: {pos.get('outcome', '—')} · Average entry: {pos.get('avg_price', '—')} · Current price: {pos.get('current_price', '—')}")
                        st.write(f"Current value: {money(pos.get('current_value'))} · Unrealized P&L: {money(pos.get('unrealized_pnl'))}")
                        st.caption(f"Last activity: {pos.get('last_event_at', '—')} · Condition: {pos.get('condition_id', '—')}")
                with st.expander("Recently closed positions / realized results"):
                    if not closed_positions:
                        st.info("No closed positions were returned.")
                    for pos in closed_positions[:50]:
                        st.write(f"**{pos.get('title') or pos.get('name') or 'Untitled'}** · {pos.get('outcome', '—')} · Realized P&L: {money(pos.get('realized_pnl'))}")
            except Exception as exc:
                st.error(f"Wallet analysis failed: {exc}")
                st.caption("Copy the complete error text. A 429/503 response can mean the public API is temporarily busy.")

with calculator_tab:
    st.subheader("Binary contract payoff calculator")
    st.caption("Planning calculator only. Enter the price you could actually buy at, not the midpoint or last-traded price.")
    x, y, z = st.columns(3)
    with x:
        stake = st.number_input("Maximum stake ($)", min_value=1.0, value=float(min(bankroll, 55.0)), step=1.0)
    with y:
        ask_cents = st.number_input("Executable ask (cents)", min_value=1.0, max_value=99.0, value=50.0, step=1.0)
    with z:
        fee_per_contract = st.number_input("Estimated fee per contract ($)", min_value=0.0, value=0.01, step=0.01, format="%.3f")
    estimated_probability = st.slider("Your estimated probability of winning", min_value=1, max_value=99, value=55)
    price = ask_cents / 100.0
    cost_each = price + fee_per_contract
    contracts = int(stake // cost_each) if cost_each > 0 else 0
    total_cost = contracts * cost_each
    profit_if_win = contracts * (1.0 - price) - contracts * fee_per_contract
    loss_if_lose = total_cost
    ev = contracts * (estimated_probability / 100.0 * (1.0 - price) - (1.0 - estimated_probability / 100.0) * price - fee_per_contract)
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Contracts", f"{contracts:,}")
    q2.metric("Total cost", money(total_cost))
    q3.metric("Profit if win", money(profit_if_win))
    q4.metric("Estimated EV", money(ev))
    st.write(f"Maximum loss if the contract loses: **{money(loss_if_lose)}**. Remaining bankroll: **{money(max(0, bankroll - total_cost))}**.")
    st.caption("This estimate excludes any unentered fees, spread changes, partial fills, slippage, and settlement risk. EV is only as good as your probability estimate.")

st.divider()
st.subheader("Before approving any trade")
checks = [
    "The Polymarket and Kalshi contracts resolve on the same real-world event.",
    "The outcome, threshold, measurement period, deadline, and timezone match exactly.",
    "The settlement sources and exception rules are compatible.",
    "The Polymarket position is current and the trader has not exited or reversed it.",
    "The Kalshi price is an executable ask with enough order-book depth.",
    "Fees, spread, slippage, and the possibility of losing the full stake are included.",
    "The stake is within the bankroll limit and affordable to lose completely.",
]
for item in checks:
    st.checkbox(item, key="check_" + str(checks.index(item)))

st.caption("Data sources: Polymarket public Data API and Kalshi public Trade API. Data can be delayed, incomplete, or changed by the providers. This app is informational and does not provide guaranteed signals or execute trades.")

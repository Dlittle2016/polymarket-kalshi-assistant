import re
import requests
import streamlit as st
from datetime import datetime, timezone

st.set_page_config(
    page_title="Polymarket → Kalshi Assistant",
    page_icon="📊",
    layout="wide"
)

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
POLY_BASE = "https://data-api.polymarket.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MarketResearchAssistant/7.0)"
}

TOPICS = {
    "Federal Reserve": [
        "federal reserve", "fomc", "fed funds", "federal funds rate",
        "interest rate", "rate decision", "rate cut", "rate hike",
        "rate increase", "rate reduction", "monetary policy",
        "fed chair", "fed meeting"
    ],
    "Inflation": [
        "inflation", "cpi", "core cpi", "pce", "ppi", "price index"
    ],
    "Employment": [
        "unemployment", "nonfarm payrolls", "jobs report",
        "jobless claims", "employment", "labor market",
        "payrolls", "job creation"
    ],
    "Economic Growth": [
        "gdp", "economic growth", "recession", "contraction",
        "expansion"
    ],
    "Consumer Economy": [
        "retail sales", "consumer spending", "consumer confidence",
        "consumer sentiment", "personal income", "personal spending"
    ],
    "Housing": [
        "housing starts", "home sales", "home prices",
        "housing market", "building permits", "mortgage rates"
    ],
    "Treasury & Bonds": [
        "treasury yields", "10-year yield", "2-year yield",
        "bond yield", "treasury bonds", "treasury rate"
    ],
    "Business & Manufacturing": [
        "manufacturing", "industrial production", "pmi", "ism",
        "business activity", "factory orders", "durable goods"
    ],
}


def get_json(url, params=None, timeout=20):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=timeout
    )
    response.raise_for_status()
    return response.json()


def norm(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "").lower()
    ).strip()


def phrase_in(text, phrase):
    text = " " + re.sub(
        r"[^a-z0-9]+",
        " ",
        norm(text)
    ) + " "

    phrase = " " + re.sub(
        r"[^a-z0-9]+",
        " ",
        norm(phrase)
    ) + " "

    return phrase in text


def topics_for(text):
    found = []

    for topic, phrases in TOPICS.items():
        if any(phrase_in(text, p) for p in phrases):
            found.append(topic)

    return found


@st.cache_data(ttl=45, show_spinner=False)
def fetch_kalshi_events(max_pages=10):
    all_events = []
    cursor = None

    for _ in range(max_pages):
        params = {
            "status": "open",
            "limit": 200,
            "with_nested_markets": "true"
        }

        if cursor:
            params["cursor"] = cursor

        payload = get_json(
            f"{KALSHI_BASE}/events",
            params=params
        )

        events = payload.get("events", []) or []
        all_events.extend(events)

        cursor = payload.get("cursor")

        if not cursor:
            break

    return all_events


@st.cache_data(ttl=120, show_spinner=False)
def fetch_leaderboard(period, category, sort_by, limit):
    params = {
        "time_period": period.lower(),
        "category": category.lower(),
        "sort_by": sort_by.upper(),
        "limit": int(limit)
    }

    payload = get_json(
        f"{POLY_BASE}/v2/leaderboard",
        params=params
    )

    rows = payload.get("data", [])

    if isinstance(rows, dict):
        rows = rows.get(
            "leaderboard",
            rows.get("data", [])
        )

    return (
        rows if isinstance(rows, list) else [],
        payload.get("pagination", {})
    )


@st.cache_data(ttl=90, show_spinner=False)
def fetch_wallet_stats(wallet):
    payload = get_json(
        f"{POLY_BASE}/v2/user-stats",
        params={"user": wallet}
    )

    return payload.get("data")


@st.cache_data(ttl=60, show_spinner=False)
def fetch_wallet_positions(wallet, status, limit=100):
    params = {
        "user": wallet,
        "status": status,
        "limit": limit,
        "sort_by": (
            "REALIZED_PNL"
            if status == "CLOSED"
            else "CURRENT_VALUE"
        ),
        "sort_direction": "DESC",
        "filter_type": "TOKENS",
        "filter_amount": 0
    }

    if status == "OPEN":
        params["include_archived"] = "true"

    payload = get_json(
        f"{POLY_BASE}/v2/positions",
        params=params
    )

    return (
        payload.get("data", []),
        payload.get("pagination", {})
    )


@st.cache_data(ttl=60, show_spinner=False)
def fetch_wallet_activity(wallet, limit=100):
    payload = get_json(
        f"{POLY_BASE}/v2/activity",
        params={
            "user": wallet,
            "limit": limit,
            "sort_by": "TIMESTAMP",
            "sort_direction": "DESC"
        }
    )

    return (
        payload.get("data", []),
        payload.get("pagination", {})
    )


@st.cache_data(ttl=120, show_spinner=False)
def fetch_wallet_pnl(wallet):
    payload = get_json(
        f"{POLY_BASE}/v2/user-pnl",
        params={
            "user": wallet,
            "interval": "max",
            "fidelity": "1d"
        }
    )

    return payload.get("data")


@st.cache_data(ttl=120, show_spinner=False)
def fetch_wallet_volume(wallet):
    payload = get_json(
        f"{POLY_BASE}/v2/user-volume",
        params={"user": wallet}
    )

    return payload.get("data")


def money(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def wallet_of(row):
    return (
        row.get("user_id")
        or row.get("proxy_wallet")
        or row.get("proxyWallet")
        or row.get("address")
        or ""
    )


def display_leader(row):
    return (
        row.get("user_name")
        or row.get("username")
        or row.get("name")
        or (wallet_of(row)[:10] + "…")
    )


st.title("📊 Polymarket → Kalshi Trading Assistant")

st.caption(
    "Version 7 · Trader intelligence · Public market research · "
    "Read-only · Manual approval only · No automatic trading"
)


# SIDEBAR

with st.sidebar:
    st.subheader("Research settings")

    bankroll = st.number_input(
        "Simulated bankroll ($)",
        min_value=1.0,
        max_value=100000.0,
        value=55.0,
        step=5.0
    )

    st.caption(
        "This is a planning value only. The app does not connect "
        "to your Kalshi account or place orders."
    )


# TABS

market_tab, trader_tab, wallet_tab, calculator_tab = st.tabs([
    "Economic Markets",
    "Trader Leaderboard",
    "Wallet Inspector",
    "Payoff Calculator"
])


# --------------------------------------------------
# ECONOMIC MARKETS
# --------------------------------------------------

with market_tab:

    st.subheader("Open Kalshi economic markets")

    c1, c2 = st.columns([1, 2])

    with c1:
        selected_topic = st.selectbox(
            "Economic category",
            ["All economic topics"] + list(TOPICS.keys())
        )

    with c2:
        keyword = st.text_input(
            "Optional keyword",
            placeholder="e.g. Fed, CPI, Powell, GDP"
        )

    if st.button(
        "Search Kalshi markets",
        type="primary",
        key="search_markets"
    ):
        st.session_state["run_market_search"] = True

    if st.session_state.get("run_market_search"):

        try:
            with st.spinner(
                "Loading Kalshi events and nested markets..."
            ):
                events = fetch_kalshi_events()

            matches = []

            for event in events:

                event_title = event.get("title", "")
                event_subtitle = event.get("subtitle", "")
                event_category = event.get("category", "")

                markets = event.get("markets", []) or []

                for market in markets:

                    title = market.get("title", "")

                    searchable = " ".join([
                        event_title,
                        event_subtitle,
                        event_category,
                        title,
                        market.get("subtitle", "")
                    ])

                    found_topics = topics_for(searchable)

                    if (
                        selected_topic != "All economic topics"
                        and selected_topic not in found_topics
                    ):
                        continue

                    if (
                        selected_topic == "All economic topics"
                        and not found_topics
                    ):
                        continue

                    if keyword and not phrase_in(searchable, keyword):

                        tokens = set(
                            re.findall(
                                r"[a-z0-9]+",
                                norm(searchable)
                            )
                        )

                        if norm(keyword) not in tokens:
                            continue

                    matches.append(
                        (event, market, found_topics)
                    )

            st.success(
                f"Retrieved {len(events):,} events · "
                f"Found {len(matches):,} matching markets"
            )

            if not matches:
                st.info(
                    "No matching markets found. Try a broader "
                    "category or a shorter keyword."
                )

            for event, market, found_topics in matches[:60]:

                with st.container(border=True):

                    st.markdown(
                        f"**{market.get('title') or event.get('title') or 'Untitled market'}**"
                    )

                    st.caption(
                        f"{event.get('title', '')} · "
                        f"{' / '.join(found_topics)}"
                    )

                    cols = st.columns(3)

                    cols[0].metric(
                        "YES ask",
                        market.get("yes_ask_dollars")
                        or (
                            f"{market.get('yes_ask')}¢"
                            if market.get("yes_ask") is not None
                            else "—"
                        )
                    )

                    cols[1].metric(
                        "NO ask",
                        market.get("no_ask_dollars")
                        or (
                            f"{market.get('no_ask')}¢"
                            if market.get("no_ask") is not None
                            else "—"
                        )
                    )

                    cols[2].metric(
                        "Ticker",
                        market.get("ticker", "—")
                    )

                    if market.get("close_time"):
                        st.caption(
                            f"Closes: {market.get('close_time')}"
                        )

                    if market.get("rules_primary"):

                        with st.expander("Settlement rules"):
                            st.write(
                                market.get("rules_primary")
                            )

        except Exception as exc:

            st.error(
                f"Kalshi market search failed: {exc}"
            )

            st.caption(
                "If this continues, copy the full error text "
                "so we can diagnose the API response."
            )


# --------------------------------------------------
# POLYMARKET TRADER LEADERBOARD
# --------------------------------------------------

with trader_tab:

    st.subheader(
        "Find traders by reported Polymarket performance"
    )

    st.warning(
        "Leaderboard P&L is a ranking signal, not proof of a "
        "repeatable edge. Daily/weekly/monthly results can include "
        "mark-to-market changes; all-time P&L is realized-only. "
        "Volume is reported in shares, not dollars."
    )

    a, b, c, d = st.columns(4)

    with a:
        period = st.selectbox(
            "Performance window",
            ["ALL", "MONTH", "WEEK", "DAY"],
            index=0
        )

    with b:
        category = st.selectbox(
            "Category",
            [
                "OVERALL",
                "ECONOMICS",
                "FINANCE",
                "CRYPTO",
                "POLITICS",
                "SPORTS",
                "TECH",
                "WEATHER",
                "CULTURE",
                "MENTIONS"
            ]
        )

    with c:
        rank_by = st.selectbox(
            "Rank by",
            ["PNL", "VOLUME"]
        )

    with d:
        row_limit = st.selectbox(
            "Rows",
            [10, 25, 50],
            index=1
        )

    if st.button(
        "Load Polymarket leaderboard",
        type="primary",
        key="load_leaderboard"
    ):
        st.session_state["run_leaderboard"] = True

    if st.session_state.get("run_leaderboard"):

        try:
            with st.spinner(
                "Loading the public Polymarket leaderboard..."
            ):
                leaders, pagination = fetch_leaderboard(
                    period,
                    category,
                    rank_by,
                    row_limit
                )

            st.caption(
                f"Showing {len(leaders)} leaderboard entries · "
                f"Retrieved {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            )

            if not leaders:
                st.info(
                    "The leaderboard returned no rows. "
                    "Try another time window or category."
                )

            for row in leaders:

                wallet = wallet_of(row)

                with st.container(border=True):

                    left, right = st.columns([3, 2])

                    with left:

                        rank = row.get("rank", "—")

                        st.markdown(
                            f"**#{rank} · {display_leader(row)}**"
                        )

                        st.caption(
                            wallet
                            if wallet
                            else "Wallet address not supplied by API"
                        )

                        if (
                            row.get("verified")
                            or row.get("verified_badge")
                        ):
                            st.caption(
                                "✓ Polymarket verified profile"
                            )

                    with right:

                        st.metric(
                            "P&L",
                            money(row.get("pnl"))
                        )

                        st.metric(
                            "Volume (shares)",
                            f"{float(row.get('volume', row.get('vol', 0)) or 0):,.0f}"
                        )

                    if wallet:

                        if st.button(
                            "Inspect this wallet",
                            key=f"inspect_{wallet}"
                        ):

                            st.session_state["selected_wallet"] = wallet

                            st.session_state["selected_wallet_name"] = (
                                display_leader(row)
                            )

                            st.session_state["active_tab_hint"] = "wallet"

                            st.info(
                                "Wallet selected. Open the Wallet Inspector "
                                "tab to review its positions and profile data."
                            )

            if pagination.get("has_more"):

                st.caption(
                    "More leaderboard entries are available through "
                    "cursor pagination; this version displays the first page only."
                )

        except Exception as exc:

            st.error(
                f"Polymarket leaderboard request failed: {exc}"
            )

            st.caption(
                "The current Polymarket API uses the v2 leaderboard. "
                "Copy the full error text if this fails."
            )


# --------------------------------------------------
# WALLET INSPECTOR
# --------------------------------------------------

with wallet_tab:

    st.subheader(
        "Trader intelligence: inspect positions, activity, and P&L"
    )

    st.caption(
        "Start with a leaderboard wallet or paste any public "
        "Polymarket proxy wallet address."
    )

    default_wallet = st.session_state.get(
        "selected_wallet",
        "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
    )

    default_name = st.session_state.get(
        "selected_wallet_name",
        "Theo4 (leaderboard #1)"
    )

    st.write(
        f"Selected research target: **{default_name}**"
    )

    wallet = st.text_input(
        "Wallet address",
        value=default_wallet,
        placeholder="0x…"
    )

    if st.button(
        "Analyze wallet",
        type="primary",
        key="analyze_wallet"
    ):
        st.session_state["wallet_to_analyze"] = wallet.strip()

    target = st.session_state.get(
        "wallet_to_analyze",
        default_wallet
    )

    if target:

        if not re.fullmatch(
            r"0x[a-fA-F0-9]{40}",
            target
        ):

            st.error(
                "Enter a valid 42-character Polygon wallet address "
                "beginning with 0x."
            )

        else:

            try:

                with st.spinner(
                    "Loading profile, positions, recent activity, and P&L history..."
                ):

                    stats = fetch_wallet_stats(target)

                    open_positions, open_pagination = (
                        fetch_wallet_positions(
                            target,
                            "OPEN",
                            100
                        )
                    )

                    closed_positions, closed_pagination = (
                        fetch_wallet_positions(
                            target,
                            "CLOSED",
                            100
                        )
                    )

                    activity, activity_pagination = (
                        fetch_wallet_activity(
                            target,
                            100
                        )
                    )

                    pnl_history = fetch_wallet_pnl(target)

                    volume_data = fetch_wallet_volume(target)

                if not stats:

                    st.info(
                        "Polymarket did not return a profile record "
                        "for this wallet. Other wallet data may still be available."
                    )

                else:

                    pnl_data = stats.get("all_time_pnl") or {}

                    realized = pnl_data.get("realized_pnl")

                    if realized is None:

                        realized = (
                            (pnl_data.get("realized_market_pnl") or 0)
                            +
                            (pnl_data.get("realized_combo_pnl") or 0)
                        )

                    m1, m2, m3, m4 = st.columns(4)

                    m1.metric(
                        "All-time realized P&L",
                        money(realized)
                    )

                    m2.metric(
                        "Markets traded",
                        f"{stats.get('trades', 0):,}"
                    )

                    m3.metric(
                        "Biggest resolved win",
                        money(stats.get("biggest_win"))
                    )

                    m4.metric(
                        "Current open positions",
                        f"{len(open_positions):,}"
                    )

                    if stats.get("join_date"):

                        joined = datetime.fromtimestamp(
                            stats["join_date"],
                            timezone.utc
                        ).strftime("%Y-%m-%d")

                        st.caption(
                            f"Profile join date: {joined} · "
                            f"Profile views: {stats.get('views', '—')}"
                        )

                if volume_data:

                    v1, v2, v3 = st.columns(3)

                    v1.metric(
                        "Lifetime volume (USD)",
                        money(volume_data.get("volume_usdc"))
                    )

                    v2.metric(
                        "Lifetime volume (shares)",
                        f"{float(volume_data.get('volume') or 0):,.0f}"
                    )

                    v3.metric(
                        "Lifetime fill count",
                        f"{int(volume_data.get('trade_count') or 0):,}"
                    )

                # OPEN POSITIONS

                st.markdown("#### Current open positions")

                if not open_positions:

                    st.info(
                        "No open positions were returned by the Polymarket API."
                    )

                    st.caption(
                        "The request includes archived open positions and "
                        "sets the minimum token filter to zero. If this remains "
                        "empty, the wallet may genuinely have no current holdings."
                    )

                for pos in open_positions[:50]:

                    with st.container(border=True):

                        st.markdown(
                            f"**{pos.get('title') or pos.get('name') or 'Untitled market'}**"
                        )

                        p1, p2, p3, p4 = st.columns(4)

                        p1.metric(
                            "Outcome",
                            str(pos.get("outcome") or "—")
                        )

                        p2.metric(
                            "Average entry",
                            f"{float(pos.get('avg_price') or 0):.3f}"
                        )

                        p3.metric(
                            "Current price",
                            f"{float(pos.get('current_price') or 0):.3f}"
                        )

                        p4.metric(
                            "Current shares",
                            f"{float(pos.get('current_size') or 0):,.2f}"
                        )

                        st.write(
                            f"Current value: **{money(pos.get('current_value'))}** · "
                            f"Unrealized P&L: **{money(pos.get('unrealized_pnl'))}** · "
                            f"Realized P&L: **{money(pos.get('realized_pnl'))}**"
                        )

                        st.caption(
                            f"Last position activity: {pos.get('last_event_at', '—')} · "
                            f"Market closes: {pos.get('end_date', '—')} · "
                            f"Condition: {pos.get('condition_id', '—')}"
                        )

                if open_pagination.get("has_more"):

                    st.caption(
                        "More open positions exist beyond the first 100 returned."
                    )

                # RECENT ACTIVITY

                st.markdown("#### Recent wallet activity")

                st.caption(
                    "This feed can include trades and other wallet actions. "
                    "Check the activity type before interpreting a row as a buy or sell."
                )

                if not activity:

                    st.info(
                        "No recent activity was returned."
                    )

                for item in activity[:50]:

                    ts = item.get("timestamp")

                    when = (
                        datetime.fromtimestamp(
                            ts,
                            timezone.utc
                        ).strftime("%Y-%m-%d %H:%M UTC")
                        if isinstance(ts, (int, float))
                        else str(ts or "Time unavailable")
                    )

                    title = (
                        item.get("title")
                        or item.get("name")
                        or item.get("eventSlug")
                        or "Untitled market"
                    )

                    side = (
                        item.get("side")
                        or item.get("type")
                        or "Activity"
                    )

                    outcome = item.get("outcome") or ""

                    price_val = item.get("price")
                    size_val = item.get("size")

                    value_val = (
                        item.get("usdcSize")
                        or item.get("usdc_size")
                    )

                    details = []

                    if outcome:
                        details.append(str(outcome))

                    if price_val is not None:
                        details.append(
                            f"Price {float(price_val):.3f}"
                        )

                    if size_val is not None:
                        details.append(
                            f"Shares {float(size_val):,.2f}"
                        )

                    if value_val is not None:
                        details.append(
                            f"Value {money(value_val)}"
                        )

                    st.write(
                        f"**{when} · {side} · {title}**"
                    )

                    st.caption(
                        " · ".join(details)
                        if details
                        else "No trade price/size fields supplied for this activity row."
                    )

                if activity_pagination.get("has_more"):

                    st.caption(
                        "More activity is available through cursor pagination; "
                        "this view shows the first 100 records."
                    )

                # P&L HISTORY

                st.markdown("#### P&L history")

                points = (
                    (pnl_history or {}).get("points", [])
                    if isinstance(pnl_history, dict)
                    else []
                )

                if points:

                    import pandas as pd

                    pnl_rows = []

                    for point in points:

                        stamp = point.get("timestamp")

                        if stamp is None:
                            continue

                        row = {
                            "Date": datetime.fromtimestamp(
                                stamp,
                                timezone.utc
                            ),
                            "Realized P&L": point.get("realized_pnl"),
                            "Unrealized P&L": point.get("unrealized_pnl"),
                            "Volume USD": point.get("volume_usdc")
                        }

                        pnl_rows.append(row)

                    if pnl_rows:

                        frame = (
                            pd.DataFrame(pnl_rows)
                            .set_index("Date")
                            .sort_index()
                        )

                        chart_cols = [
                            col
                            for col in [
                                "Realized P&L",
                                "Unrealized P&L"
                            ]
                            if frame[col].notna().any()
                        ]

                        if chart_cols:
                            st.line_chart(frame[chart_cols])

                        st.dataframe(
                            frame.tail(30),
                            use_container_width=True
                        )

                else:

                    st.info(
                        "No P&L time series was returned for this wallet."
                    )

                # CLOSED POSITIONS

                with st.expander(
                    "Recently closed positions / realized results"
                ):

                    if not closed_positions:

                        st.info(
                            "No closed positions were returned."
                        )

                    for pos in closed_positions[:50]:

                        st.write(
                            f"**{pos.get('title') or pos.get('name') or 'Untitled'}** · "
                            f"{pos.get('outcome', '—')} · "
                            f"Realized P&L: {money(pos.get('realized_pnl'))} · "
                            f"Entry: {pos.get('avg_price', '—')} · "
                            f"Last activity: {pos.get('last_event_at', '—')}"
                        )

                    if closed_pagination.get("has_more"):

                        st.caption(
                            "Additional closed positions are available beyond this first page."
                        )

                st.warning(
                    "Interpretation caution: the leaderboard's headline P&L, "
                    "wallet profile P&L, position-level P&L, and P&L history "
                    "may use different windows or accounting components. "
                    "A current position is not proof the trader still has "
                    "the same conviction; activity timestamps can lag. "
                    "Never mirror a position without checking the live market "
                    "and exact settlement rules."
                )

            except Exception as exc:

                st.error(
                    f"Wallet analysis failed: {exc}"
                )

                st.caption(
                    "Copy the complete error text. Public endpoints may "
                    "return 429/503 when busy; retry after a short wait."
                )


# --------------------------------------------------
# PAYOFF CALCULATOR
# --------------------------------------------------

with calculator_tab:

    st.subheader("Binary contract payoff calculator")

    st.caption(
        "Planning calculator only. Enter the price you could actually buy at, "
        "not the midpoint or last-traded price."
    )

    x, y, z = st.columns(3)

    with x:

        stake = st.number_input(
            "Maximum stake ($)",
            min_value=1.0,
            value=float(min(bankroll, 55.0)),
            step=1.0
        )

    with y:

        ask_cents = st.number_input(
            "Executable ask (cents)",
            min_value=1.0,
            max_value=99.0,
            value=50.0,
            step=1.0
        )

    with z:

        fee_per_contract = st.number_input(
            "Estimated fee per contract ($)",
            min_value=0.0,
            value=0.01,
            step=0.01,
            format="%.3f"
        )

    estimated_probability = st.slider(
        "Your estimated probability of winning",
        min_value=1,
        max_value=99,
        value=55
    )

    price = ask_cents / 100.0

    cost_each = price + fee_per_contract

    contracts = (
        int(stake // cost_each)
        if cost_each > 0
        else 0
    )

    total_cost = contracts * cost_each

    profit_if_win = (
        contracts * (1.0 - price)
        - contracts * fee_per_contract
    )

    loss_if_lose = total_cost

    ev = contracts * (
        estimated_probability / 100.0 * (1.0 - price)
        -
        (1.0 - estimated_probability / 100.0) * price
        -
        fee_per_contract
    )

    q1, q2, q3, q4 = st.columns(4)

    q1.metric(
        "Contracts",
        f"{contracts:,}"
    )

    q2.metric(
        "Total cost",
        money(total_cost)
    )

    q3.metric(
        "Profit if win",
        money(profit_if_win)
    )

    q4.metric(
        "Estimated EV",
        money(ev)
    )

    st.write(
        f"Maximum loss if the contract loses: **{money(loss_if_lose)}**. "
        f"Remaining bankroll: **{money(max(0, bankroll - total_cost))}**."
    )

    st.caption(
        "This estimate excludes any unentered fees, spread changes, "
        "partial fills, slippage, and settlement risk. "
        "EV is only as good as your probability estimate."
    )


# --------------------------------------------------
# MANUAL TRADE APPROVAL CHECKLIST
# --------------------------------------------------

st.divider()

st.subheader("Before approving any trade")

checks = [
    "The Polymarket and Kalshi contracts resolve on the same real-world event.",
    "The outcome, threshold, measurement period, deadline, and timezone match exactly.",
    "The settlement sources and exception rules are compatible.",
    "The Polymarket position is current and the trader has not exited or reversed it.",
    "The Kalshi price is an executable ask with enough order-book depth.",
    "Fees, spread, slippage, and the possibility of losing the full stake are included.",
    "The stake is within the bankroll limit and affordable to lose completely."
]

for item in checks:

    st.checkbox(
        item,
        key="check_" + str(checks.index(item))
    )


st.caption(
    "Data sources: Polymarket public Data API and Kalshi public Trade API. "
    "Data can be delayed, incomplete, or changed by the providers. "
    "This app is informational and does not provide guaranteed signals "
    "or execute trades."
)

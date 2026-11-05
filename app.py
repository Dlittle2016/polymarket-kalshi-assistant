
import json
import re
from datetime import datetime, timezone

import requests
import streamlit as st

st.set_page_config(
    page_title="Polymarket + Kalshi Assistant",
    page_icon="📊",
    layout="wide"
)

POLY = "https://data-api.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
BANKROLL = 55.0


# ============================================================
# GENERAL HELPERS
# ============================================================

def api_get(url, params=None):
    try:
        r = requests.get(
            url,
            params=params,
            timeout=25,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        trace = r.headers.get("x-trace-id", "")
        r.raise_for_status()

        try:
            payload = r.json()
        except ValueError:
            payload = {"raw_text": r.text[:3000]}

        return {
            "ok": True,
            "status": r.status_code,
            "trace": trace,
            "payload": payload,
            "error": None
        }

    except requests.HTTPError as e:
        response = e.response
        try:
            body = response.json() if response is not None else None
        except ValueError:
            body = response.text[:3000] if response is not None else None

        return {
            "ok": False,
            "status": response.status_code if response is not None else None,
            "trace": response.headers.get("x-trace-id", "") if response is not None else "",
            "payload": body,
            "error": str(e)
        }

    except requests.RequestException as e:
        return {
            "ok": False,
            "status": None,
            "trace": "",
            "payload": None,
            "error": str(e)
        }


def get_data(result, default=None):
    if default is None:
        default = []

    if not result.get("ok"):
        return default

    payload = result.get("payload")

    if isinstance(payload, dict):
        return payload.get("data", default)

    return default


def rows(result):
    data = get_data(result, [])
    return data if isinstance(data, list) else []


def dollars(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def cents(value):
    try:
        return f"{float(value):.1f}¢"
    except (TypeError, ValueError):
        return "—"


def diagnostics(label, result):
    st.markdown(f"**{label} API diagnostics**")

    a, b = st.columns(2)
    a.metric("HTTP status", result.get("status") or "No response")
    b.metric("Trace ID", result.get("trace") or "Not supplied")

    if not result.get("ok"):
        st.error(result.get("error") or "Request failed")

    with st.expander(f"View raw {label} response"):
        st.code(
            json.dumps(result.get("payload"), indent=2, default=str)
            if result.get("payload") is not None
            else "No response body",
            language="json"
        )


# ============================================================
# KALSHI MARKET SEARCH
# ============================================================

@st.cache_data(ttl=120, show_spinner=False)
def load_kalshi_events():
    events = []
    cursor = None

    for _ in range(10):
        params = {
            "limit": 200,
            "with_nested_markets": "true"
        }

        if cursor:
            params["cursor"] = cursor

        result = api_get(f"{KALSHI}/events", params)

        if not result["ok"]:
            return events, result

        payload = result["payload"]
        batch = payload.get("events", []) if isinstance(payload, dict) else []

        events.extend(batch)
        cursor = payload.get("cursor")

        if not cursor or not batch:
            break

    return events, {
        "ok": True,
        "status": 200,
        "trace": "",
        "payload": {"events_retrieved": len(events)},
        "error": None
    }


def flatten_markets(events):
    markets = []

    for event in events:
        for market in event.get("markets", []) or []:
            item = dict(market)

            item["_event_title"] = event.get("title", "")

            searchable = [
                market.get("title"),
                market.get("subtitle"),
                market.get("ticker"),
                market.get("yes_sub_title"),
                market.get("no_sub_title"),
                market.get("rules_primary"),
                market.get("rules_secondary"),
                event.get("title"),
                event.get("sub_title"),
                event.get("category"),
                event.get("series_ticker")
            ]

            item["_search"] = " ".join(
                str(x) for x in searchable if x
            ).lower()

            markets.append(item)

    return markets


# ============================================================
# POLYMARKET API
# ============================================================

@st.cache_data(ttl=90, show_spinner=False)
def load_leaderboard(limit=25, period="ALL"):
    return api_get(
        f"{POLY}/v2/leaderboard",
        {
            "limit": limit,
            "timePeriod": period,
            "category": "OVERALL",
            "orderBy": "PNL"
        }
    )


@st.cache_data(ttl=60, show_spinner=False)
def wallet_endpoint(path, wallet, extra=None):
    params = {"user": wallet}

    if extra:
        params.update(extra)

    return api_get(f"{POLY}{path}", params)


@st.cache_data(ttl=60, show_spinner=False)
def regular_positions(wallet, status="OPEN"):
    params = {
        "user": wallet,
        "status": status,
        "limit": 100,
        "sort_by": "CURRENT_VALUE" if status == "OPEN" else "REALIZED_PNL",
        "sort_direction": "DESC",
        "filter_type": "TOKENS"
    }

    if status != "CLOSED":
        params["include_archived"] = "true"

    # Intentionally omit filter_amount. The API has a default dust threshold.
    return api_get(f"{POLY}/v2/positions", params)


@st.cache_data(ttl=60, show_spinner=False)
def combo_positions(wallet):
    return api_get(
        f"{POLY}/v2/positions/combos",
        {
            "user": wallet,
            "status": "OPEN",
            "limit": 100
        }
    )


# ============================================================
# POSITION DISPLAY
# ============================================================

def show_regular_positions(position_rows):
    if not position_rows:
        st.info(
            "The regular /v2/positions endpoint returned zero rows."
        )
        st.caption(
            "This does not rule out combo positions. The API also excludes "
            "inactive markets, even when archived markets are included."
        )
        return

    st.success(f"{len(position_rows)} regular position(s) returned.")

    for i, p in enumerate(position_rows, 1):
        title = p.get("title") or p.get("name") or "Untitled market"

        with st.expander(
            f"{i}. {title} — {p.get('outcome', '')}",
            expanded=(i <= 3)
        ):
            a, b, c, d = st.columns(4)

            a.metric("Current value", dollars(p.get("current_value")))

            size = p.get("current_size")
            b.metric(
                "Shares held",
                f"{size:,.4g}" if isinstance(size, (int, float)) else "—"
            )

            avg = p.get("avg_price")
            c.metric(
                "Average entry",
                cents(avg * 100) if isinstance(avg, (int, float)) else "—"
            )

            d.metric("Unrealized P&L", dollars(p.get("unrealized_pnl")))

            st.write(
                f"**Status:** {p.get('status', '—')}  |  "
                f"**Realized P&L:** {dollars(p.get('realized_pnl'))}  |  "
                f"**Total P&L:** {dollars(p.get('total_pnl'))}"
            )

            st.json(p)


def show_combo_positions(position_rows):
    if not position_rows:
        st.info("The combo-positions endpoint returned zero rows.")
        return

    st.success(f"{len(position_rows)} combo position(s) returned.")

    for i, p in enumerate(position_rows, 1):
        label = p.get("outcome_label") or "Combo position"

        with st.expander(
            f"{i}. {label} — {p.get('status', '—')}",
            expanded=(i <= 3)
        ):
            a, b, c, d = st.columns(4)

            a.metric("Entry cost", dollars(p.get("entry_cost_usdc")))

            size = p.get("current_size")
            b.metric(
                "Current size",
                f"{size:,.4g}" if isinstance(size, (int, float)) else "—"
            )

            c.metric(
                "Average entry",
                dollars(p.get("entry_avg_price_usdc"))
            )

            d.metric(
                "Realized payout",
                dollars(p.get("realized_payout_usdc"))
            )

            st.write(
                f"**Legs resolved:** {p.get('legs_resolved', 0)} / "
                f"{p.get('legs_total', 0)}  |  "
                f"**Redeemable:** {p.get('redeemable', False)}"
            )

            for leg in p.get("legs", []) or []:
                market = leg.get("market") or {}
                event = market.get("event") or {}

                title = (
                    market.get("title")
                    or market.get("question")
                    or event.get("event_title")
                    or "Market leg"
                )

                price = leg.get("leg_current_price")
                mark = cents(price * 100) if isinstance(price, (int, float)) else "—"

                st.markdown(
                    f"- **{title}** — "
                    f"{leg.get('leg_outcome_label', '—')} "
                    f"(mark: {mark})"
                )

            st.json(p)


# ============================================================
# APP HEADER AND TABS
# ============================================================

st.title("Polymarket → Kalshi Research Assistant")

st.caption(
    "Public-data research only. No account connection, automatic trading, "
    "or order placement."
)

tab_markets, tab_leaderboard, tab_wallet, tab_calculator = st.tabs([
    "Economic Markets",
    "Trader Leaderboard",
    "Wallet Inspector",
    "Payoff Calculator"
])


# ============================================================
# TAB 1 — ECONOMIC MARKETS
# ============================================================

with tab_markets:
    st.subheader("Search Kalshi economic markets")

    query = st.text_input(
        "Search markets",
        placeholder="Fed, inflation, CPI, unemployment, rate cuts..."
    )

    categories = {
        "All economic markets": "",
        "Federal Reserve": "federal reserve fed fomc interest rate rate cut rate hike powell",
        "Inflation": "inflation cpi pce prices consumer price index",
        "Employment": "jobs unemployment payrolls labor employment",
        "Economic Growth": "gdp recession economic growth",
        "Consumer Economy": "retail sales consumer spending confidence",
        "Housing": "housing home sales mortgage starts",
        "Treasury & Bonds": "treasury bond yield 10-year 2-year",
        "Business & Manufacturing": "manufacturing ism business factory industrial production"
    }

    category = st.selectbox(
        "Economic category",
        list(categories.keys())
    )

    if st.button("Refresh Kalshi markets"):
        load_kalshi_events.clear()

    with st.spinner("Loading Kalshi events and markets..."):
        events, kalshi_result = load_kalshi_events()

    markets = flatten_markets(events)

    st.caption(
        f"Loaded {len(events):,} events and {len(markets):,} nested markets."
    )

    if not kalshi_result["ok"]:
        diagnostics("Kalshi events", kalshi_result)

    if query.strip():
        search_text = query.strip().lower()
        filtered = [
            m for m in markets
            if search_text in m["_search"]
        ]

    elif category != "All economic markets":
        terms = categories[category].split()

        filtered = [
            m for m in markets
            if any(term in m["_search"] for term in terms)
        ]

    else:
        filtered = markets

    st.write(f"**{len(filtered):,} matching markets**")

    for market in filtered[:100]:
        title = market.get("title") or market.get("ticker") or "Untitled"

        with st.container(border=True):
            st.markdown(f"**{title}**")

            if market.get("_event_title"):
                st.caption(market["_event_title"])

            a, b, c = st.columns(3)

            a.metric("YES ask", cents(market.get("yes_ask")))
            b.metric("NO ask", cents(market.get("no_ask")))

            volume = market.get("volume")
            c.metric(
                "Volume",
                f"{volume:,.0f}" if isinstance(volume, (int, float)) else "—"
            )

            st.caption(
                f"Ticker: {market.get('ticker', '—')}  |  "
                f"Status: {market.get('status', '—')}  |  "
                f"Close: {market.get('close_time') or '—'}"
            )

            if market.get("rules_primary"):
                with st.expander("Market rules"):
                    st.write(market.get("rules_primary"))

                    if market.get("rules_secondary"):
                        st.write(market.get("rules_secondary"))

    if len(filtered) > 100:
        st.caption("Showing the first 100 matches. Narrow your search to see more.")


# ============================================================
# TAB 2 — TRADER LEADERBOARD
# ============================================================

with tab_leaderboard:
    st.subheader("Polymarket trader leaderboard")

    a, b = st.columns(2)

    period = a.selectbox(
        "Leaderboard period",
        ["ALL", "MONTH", "WEEK", "DAY"]
    )

    limit = b.selectbox(
        "Number of traders",
        [10, 25, 50, 100],
        index=1
    )

    if st.button("Refresh leaderboard"):
        load_leaderboard.clear()

    with st.spinner("Loading leaderboard..."):
        leaderboard_result = load_leaderboard(limit, period)

    leaderboard = get_data(leaderboard_result, [])

    if not leaderboard_result["ok"]:
        diagnostics("Leaderboard", leaderboard_result)

    elif isinstance(leaderboard, list) and leaderboard:
        st.caption(
            "Historical leaderboard performance is not proof of repeatable "
            "returns or a recommendation to copy trades."
        )

        for i, trader in enumerate(leaderboard, 1):
            wallet = (
                trader.get("proxyWallet")
                or trader.get("proxy_wallet")
                or trader.get("user")
                or ""
            )

            name = (
                trader.get("userName")
                or trader.get("username")
                or trader.get("name")
                or "Anonymous trader"
            )

            pnl = trader.get("pnl", trader.get("profit"))
            volume = trader.get("volume")

            with st.container(border=True):
                a, b, c = st.columns([2, 1, 1])

                a.markdown(f"**#{i} — {name}**")
                a.caption(wallet or "Wallet not provided")

                b.metric("P&L", dollars(pnl))

                c.metric(
                    "Volume (shares)",
                    f"{volume:,.0f}" if isinstance(volume, (int, float)) else "—"
                )

                if wallet:
                    if st.button(
                        "Inspect this wallet",
                        key=f"inspect_{i}_{wallet}"
                    ):
                        st.session_state["selected_wallet"] = wallet
                        st.info(
                            "Wallet address saved. Open the Wallet Inspector tab."
                        )

    else:
        st.info("No leaderboard entries returned.")
        diagnostics("Leaderboard", leaderboard_result)


# ============================================================
# TAB 3 — WALLET INSPECTOR
# ============================================================

with tab_wallet:
    st.subheader("Inspect a Polymarket wallet")

    default_wallet = st.session_state.get("selected_wallet", "")

    wallet = st.text_input(
        "Polymarket proxy wallet address",
        value=default_wallet,
        placeholder="0x..."
    ).strip()

    if not wallet:
        st.info("Paste a Polymarket wallet address to inspect it.")

    elif not re.fullmatch(r"0x[a-fA-F0-9]{40}", wallet):
        st.warning("That does not look like a valid EVM wallet address.")

    else:
        if st.button("Refresh wallet data"):
            wallet_endpoint.clear()
            regular_positions.clear()
            combo_positions.clear()

        with st.spinner("Loading wallet data..."):
            stats_result = wallet_endpoint(
                "/v2/user-stats",
                wallet
            )

            volume_result = wallet_endpoint(
                "/v2/user-volume",
                wallet
            )

            value_result = wallet_endpoint(
                "/v2/value",
                wallet
            )

            pnl_result = wallet_endpoint(
                "/v2/user-pnl",
                wallet
            )

            activity_result = wallet_endpoint(
                "/v2/activity",
                wallet,
                {"limit": 50}
            )

            open_result = regular_positions(wallet, "OPEN")
            closed_result = regular_positions(wallet, "CLOSED")
            combo_result = combo_positions(wallet)

        stats = get_data(stats_result, {})
        stats = stats if isinstance(stats, dict) else {}

        volume_data = get_data(volume_result, {})
        volume_data = volume_data if isinstance(volume_data, dict) else {}

        value_data = get_data(value_result, {})
        value_data = value_data if isinstance(value_data, dict) else {}

        all_time = stats.get("all_time_pnl") or {}
        all_time = all_time if isinstance(all_time, dict) else {}

        st.markdown("#### Wallet overview")

        a, b, c, d = st.columns(4)

        a.metric(
            "Portfolio value",
            dollars(value_data.get("value"))
        )

        b.metric(
            "All-time realized P&L",
            dollars(all_time.get("realized_pnl"))
        )

        c.metric(
            "Markets traded",
            stats.get("trades", "—")
        )

        d.metric(
            "Volume (USDC)",
            dollars(volume_data.get("volume_usdc"))
        )

        st.caption(
            f"Biggest win: {dollars(stats.get('biggest_win'))}  |  "
            f"Share volume: {volume_data.get('volume', '—')}  |  "
            f"Trade count: {volume_data.get('trade_count', '—')}"
        )

        if not stats_result["ok"]:
            diagnostics("Wallet stats", stats_result)

        if not value_result["ok"]:
            diagnostics("Portfolio value", value_result)

        elif value_data.get("value") == 0:
            st.info(
                "The portfolio-value endpoint reports $0.00. "
                "Review the position results and raw API responses before "
                "concluding that the wallet has no holdings."
            )

        wallet_tabs = st.tabs([
            "Open positions",
            "Combo positions",
            "Closed positions",
            "Activity",
            "P&L history",
            "API diagnostics"
        ])

        # OPEN POSITIONS
        with wallet_tabs[0]:
            open_rows = rows(open_result)

            show_regular_positions(open_rows)

            pagination = (
                open_result.get("payload", {}).get("pagination", {})
                if isinstance(open_result.get("payload"), dict)
                else {}
            )

            st.caption(
                f"Rows returned: {len(open_rows)}  |  "
                f"More available: {pagination.get('has_more', '—')}  |  "
                f"Next cursor: {'Yes' if pagination.get('next_cursor') else 'No'}"
            )

            if not open_result["ok"]:
                diagnostics("Regular open positions", open_result)

        # COMBO POSITIONS
        with wallet_tabs[1]:
            combo_rows = rows(combo_result)

            show_combo_positions(combo_rows)

            pagination = (
                combo_result.get("payload", {}).get("pagination", {})
                if isinstance(combo_result.get("payload"), dict)
                else {}
            )

            st.caption(
                f"Rows returned: {len(combo_rows)}  |  "
                f"More available: {pagination.get('has_more', '—')}  |  "
                f"Next cursor: {'Yes' if pagination.get('next_cursor') else 'No'}"
            )

            if not combo_result["ok"]:
                diagnostics("Combo positions", combo_result)

        # CLOSED POSITIONS
        with wallet_tabs[2]:
            closed_rows = rows(closed_result)

            if not closed_rows:
                st.info("No closed regular positions returned.")

            for i, p in enumerate(closed_rows, 1):
                with st.expander(
                    f"{i}. {p.get('title', 'Untitled')} — {p.get('outcome', '')}"
                ):
                    st.write(
                        f"Realized P&L: **{dollars(p.get('realized_pnl'))}**"
                    )
                    st.json(p)

            if not closed_result["ok"]:
                diagnostics("Closed positions", closed_result)

        # ACTIVITY
        with wallet_tabs[3]:
            activity_rows = rows(activity_result)

            if not activity_rows:
                st.info("No activity rows returned.")

            for item in activity_rows:
                title = (
                    item.get("title")
                    or item.get("market")
                    or item.get("eventSlug")
                    or item.get("type")
                    or "Activity"
                )

                st.markdown(
                    f"- **{title}** — "
                    f"{item.get('type', '—')} "
                    f"{item.get('side', '')} "
                    f"{item.get('size', '')} "
                    f"{item.get('outcome', '')}"
                )

            if not activity_result["ok"]:
                diagnostics("Activity", activity_result)

        # P&L HISTORY
        with wallet_tabs[4]:
            pnl_data = get_data(pnl_result, {})
            points = (
                pnl_data.get("points", [])
                if isinstance(pnl_data, dict)
                else []
            )

            if points:
                chart_rows = []

                for point in points:
                    stamp = point.get("timestamp")
                    pnl = point.get("realized_pnl")

                    if isinstance(stamp, (int, float)) and pnl is not None:
                        chart_rows.append({
                            "Date": datetime.fromtimestamp(
                                stamp,
                                tz=timezone.utc
                            ).strftime("%Y-%m-%d"),
                            "Realized P&L": pnl
                        })

                if chart_rows:
                    st.line_chart(
                        chart_rows,
                        x="Date",
                        y="Realized P&L"
                    )

                st.dataframe(points, use_container_width=True)

            else:
                st.info("No P&L history points returned.")

            if not pnl_result["ok"]:
                diagnostics("P&L history", pnl_result)

        # DIAGNOSTICS
        with wallet_tabs[5]:
            st.markdown("#### Position endpoint comparison")

            regular_count = len(rows(open_result))
            combo_count = len(rows(combo_result))

            st.write(f"Regular open positions: **{regular_count}**")
            st.write(f"Open combo positions: **{combo_count}**")
            st.write(
                f"Portfolio value: **{dollars(value_data.get('value'))}**"
            )

            st.caption(
                "Regular positions and combo positions are separate API "
                "endpoints. A zero result from one does not prove the other "
                "is empty."
            )

            diagnostics("Regular open positions", open_result)
            diagnostics("Combo positions", combo_result)
            diagnostics("Portfolio value", value_result)
            diagnostics("Wallet stats", stats_result)
            diagnostics("Trading volume", volume_result)
            diagnostics("Activity", activity_result)
            diagnostics("P&L history", pnl_result)


# ============================================================
# TAB 4 — PAYOFF CALCULATOR
# ============================================================

with tab_calculator:
    st.subheader("Trade payoff and risk calculator")

    st.caption(
        "This is an estimate. It does not fetch live executable order-book "
        "prices or place trades."
    )

    bankroll = st.number_input(
        "Simulated bankroll (USD)",
        min_value=0.0,
        value=BANKROLL,
        step=1.0
    )

    risk_pct = st.slider(
        "Maximum bankroll risk per trade (%)",
        1,
        25,
        5
    )

    price = st.number_input(
        "Entry price (cents)",
        min_value=1.0,
        max_value=99.0,
        value=50.0,
        step=1.0
    )

    contracts = st.number_input(
        "Number of contracts",
        min_value=1,
        max_value=10000,
        value=1,
        step=1
    )

    fees = st.number_input(
        "Estimated total fees (USD)",
        min_value=0.0,
        value=0.0,
        step=0.01
    )

    cost = contracts * price / 100
    payout = float(contracts)
    profit = payout - cost - fees
    loss = cost + fees
    max_risk = bankroll * risk_pct / 100

    breakeven = (
        (cost + fees) / contracts
        if contracts
        else 0
    )

    a, b, c, d = st.columns(4)

    a.metric("Cost before fees", dollars(cost))
    b.metric("Profit if correct", dollars(profit))
    c.metric("Loss if incorrect", dollars(loss))
    d.metric("Break-even probability", f"{breakeven * 100:.1f}%")

    st.write(
        f"Maximum allowed risk at {risk_pct}%: **{dollars(max_risk)}**"
    )

    if loss > max_risk:
        st.error("This trade exceeds your selected risk limit.")

    elif loss > bankroll:
        st.error("This trade costs more than your simulated bankroll.")

    else:
        st.success(
            "This trade is within the selected risk cap. "
            "That does not mean it is a profitable trade."
        )

    st.markdown("#### Manual approval checklist")

    checklist = [
        "Both contracts resolve on the same underlying event and exact outcome.",
        "I read both platforms' settlement rules and resolution sources.",
        "I checked executable bid and ask prices, not just last-traded prices.",
        "There is enough order-book depth for my intended trade size.",
        "I included fees, spread, slippage, and settlement differences.",
        "I can afford to lose the entire amount invested.",
        "I am manually approving this trade; the app will not place it."
    ]

    checked = [
        st.checkbox(item, key=f"approval_{i}")
        for i, item in enumerate(checklist)
    ]

    if all(checked):
        st.success(
            "Checklist complete. This is a review confirmation only, "
            "not a trade instruction or execution."
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Risk notice: Prediction-market contracts can lose 100% of the amount "
    "paid. Leaderboard performance is historical. Copy trading is not "
    "guaranteed to work. Market matching must be verified manually. "
    "This app is a research aid, not financial advice."
)

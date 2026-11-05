import re
from datetime import datetime, timezone, date

import requests
import streamlit as st

st.set_page_config(page_title="Polymarket → Kalshi Assistant", page_icon="📊", layout="wide")

POLY_BASE = "https://data-api.polymarket.com"
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketResearchAssistant/9.0)"}

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


def get_json(url, params=None, timeout=25):
    response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.json(), response.status_code, response.headers.get("x-request-id") or response.headers.get("x-trace-id")


def data_rows(payload):
    data = payload.get("data", []) if isinstance(payload, dict) else []
    if isinstance(data, dict):
        for key in ("positions", "results", "items", "data", "leaderboard"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data if isinstance(data, list) else []


def norm(value):
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def phrase_in(text, phrase):
    clean_text = " " + re.sub(r"[^a-z0-9]+", " ", norm(text)) + " "
    clean_phrase = " " + re.sub(r"[^a-z0-9]+", " ", norm(phrase)) + " "
    return clean_phrase in clean_text


def topics_for(text):
    return [topic for topic, phrases in TOPICS.items() if any(phrase_in(text, p) for p in phrases)]


def money(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def number(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def wallet_of(row):
    candidates = [row.get(k) for k in ("proxyWallet", "proxy_wallet", "proxy_wallet_address", "user_id", "userId", "wallet", "address", "user")]
    for value in candidates:
        if isinstance(value, str) and re.fullmatch(r"0x[a-fA-F0-9]{40}", value):
            return value
    for value in row.values():
        if isinstance(value, dict):
            found = wallet_of(value)
            if found:
                return found
    return ""


def display_leader(row):
    for key in ("userName", "user_name", "username", "name", "displayName", "display_name", "pseudonym"):
        if row.get(key):
            return str(row[key])
    wallet = wallet_of(row)
    return wallet[:10] + "…" if wallet else "Anonymous trader"


def market_is_active(pos):
    if pos.get("archived") is True:
        return False
    raw = pos.get("end_date") or pos.get("endDate") or pos.get("end_date_iso")
    if raw:
        try:
            end_day = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            return end_day >= datetime.now(timezone.utc).date()
        except ValueError:
            try:
                return date.fromisoformat(str(raw)[:10]) >= datetime.now(timezone.utc).date()
            except ValueError:
                pass
    return True


@st.cache_data(ttl=45, show_spinner=False)
def fetch_kalshi_events(max_pages=10):
    events, cursor = [], None
    for _ in range(max_pages):
        params = {"status": "open", "limit": 200, "with_nested_markets": "true"}
        if cursor:
            params["cursor"] = cursor
        payload, _, _ = get_json(f"{KALSHI_BASE}/events", params)
        events.extend(payload.get("events", []) or [])
        cursor = payload.get("cursor")
        if not cursor:
            break
    return events


@st.cache_data(ttl=120, show_spinner=False)
def fetch_leaderboard(period, category, sort_by, limit):
    params = {"time_period": period.lower(), "category": category.lower(), "sort_by": sort_by.upper(), "limit": int(limit)}
    payload, status, trace = get_json(f"{POLY_BASE}/v2/leaderboard", params)
    rows = data_rows(payload)
    if not rows and isinstance(payload, dict) and isinstance(payload.get("leaderboard"), list):
        rows = payload["leaderboard"]
    return rows, payload.get("pagination", {}) if isinstance(payload, dict) else {}, status, trace


@st.cache_data(ttl=90, show_spinner=False)
def fetch_wallet_endpoint(path, wallet, params=None, ttl_marker=""):
    query = {"user": wallet}
    if params:
        query.update(params)
    payload, status, trace = get_json(f"{POLY_BASE}{path}", query)
    return payload, status, trace


def fetch_wallet_bundle(wallet):
    results = {}
    calls = {
        "stats": ("/v2/user-stats", {}),
        "value": ("/v2/value", {}),
        "open": ("/v2/positions", {"status": "OPEN", "limit": 100, "sort_by": "CURRENT_VALUE", "sort_direction": "DESC", "include_archived": "true", "filter_amount": 0}),
        "closed": ("/v2/positions", {"status": "CLOSED", "limit": 100, "sort_by": "REALIZED_PNL", "sort_direction": "DESC"}),
        "combos": ("/v2/positions/combos", {"status": "OPEN", "limit": 100}),
        "activity": ("/v2/activity", {"limit": 100, "sort_by": "TIMESTAMP", "sort_direction": "DESC"}),
        "pnl": ("/v2/user-pnl", {"interval": "max", "fidelity": "1d"}),
        "volume": ("/v2/user-volume", {}),
    }
    for name, (path, params) in calls.items():
        try:
            payload, status, trace = fetch_wallet_endpoint(path, wallet, params)
            results[name] = {"payload": payload, "status": status, "trace": trace, "error": None}
        except Exception as exc:
            results[name] = {"payload": {}, "status": None, "trace": None, "error": str(exc)}
    return results


def get_data(payload):
    return payload.get("data") if isinstance(payload, dict) else None


def get_list(payload):
    return data_rows(payload)


def group_positions(positions):
    """Aggregate every outcome token in each market condition, not only YES/NO."""
    groups = {}
    for pos in positions:
        condition = str(
            pos.get("condition_id") or pos.get("conditionId") or
            pos.get("slug") or pos.get("title") or "unknown"
        )
        group = groups.setdefault(condition, {
            "condition": condition,
            "title": pos.get("title") or pos.get("name") or "Untitled market",
            "positions": [], "outcomes": {},
            "yes_shares": 0.0, "no_shares": 0.0,
            "yes_cost": 0.0, "no_cost": 0.0,
            "yes_value": 0.0, "no_value": 0.0,
            "yes_pnl": 0.0, "no_pnl": 0.0,
            "archived": False, "end_date": pos.get("end_date"),
            "active": True,
        })
        group["positions"].append(pos)
        outcome_raw = pos.get("outcome") or "Unknown outcome"
        outcome_key = norm(outcome_raw) or "unknown outcome"
        shares = number(pos.get("current_size"))
        cost = number(pos.get("total_cost_usdc", pos.get("entry_cost_usdc")))
        value = number(pos.get("current_value"))
        pnl = number(pos.get("unrealized_pnl", pos.get("total_pnl")))
        outcome = group["outcomes"].setdefault(outcome_key, {
            "label": str(outcome_raw), "shares": 0.0, "cost": 0.0,
            "value": 0.0, "pnl": 0.0, "positions": 0,
        })
        outcome["shares"] += shares
        outcome["cost"] += cost
        outcome["value"] += value
        outcome["pnl"] += pnl
        outcome["positions"] += 1

        # Keep binary YES/NO totals only when the actual outcome labels say YES/NO.
        if outcome_key == "yes":
            group["yes_shares"] += shares
            group["yes_cost"] += cost
            group["yes_value"] += value
            group["yes_pnl"] += pnl
        elif outcome_key == "no":
            group["no_shares"] += shares
            group["no_cost"] += cost
            group["no_value"] += value
            group["no_pnl"] += pnl

        group["archived"] = group["archived"] or bool(pos.get("archived"))
        group["active"] = group["active"] and market_is_active(pos)
        if pos.get("end_date"):
            group["end_date"] = pos.get("end_date")

    for group in groups.values():
        group["total_cost"] = sum(x["cost"] for x in group["outcomes"].values())
        group["total_value"] = sum(x["value"] for x in group["outcomes"].values())
        group["total_pnl"] = sum(x["pnl"] for x in group["outcomes"].values())
        group["net_yes_shares"] = group["yes_shares"] - group["no_shares"]
        group["has_both_sides"] = group["yes_shares"] > 0 and group["no_shares"] > 0
        group["outcome_count"] = len(group["outcomes"])
        group["has_multiple_outcomes"] = group["outcome_count"] > 1
        group["position_count"] = len(group["positions"])
        group["outcomes"] = sorted(group["outcomes"].values(), key=lambda x: x["value"], reverse=True)
    return list(groups.values())


def render_group(group):
    with st.container(border=True):
        label = "ACTIVE MARKET" if group["active"] else "ARCHIVED / ENDED MARKET"
        st.markdown(f"**{group['title']}**")
        st.caption(f"{label} · {group['position_count']} token position(s) · {group['outcome_count']} distinct outcome(s) · End date: {group['end_date'] or 'not supplied'}")
        if group["has_both_sides"]:
            st.warning("BINARY OPPOSITE-SIDE HOLDING: both YES and NO are held in this same condition.")
        elif group["has_multiple_outcomes"]:
            st.info("MULTI-OUTCOME EXPOSURE: this market uses named outcomes. These are not being misclassified as YES/NO.")
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Distinct outcomes", f"{group['outcome_count']:,}")
        a2.metric("Combined cost", money(group["total_cost"]))
        a3.metric("Combined value", money(group["total_value"]))
        a4.metric("Combined P&L", money(group["total_pnl"]))
        b1, b2 = st.columns(2)
        b1.metric("Combined return", f"{(group['total_pnl'] / group['total_cost'] * 100):.2f}%" if group["total_cost"] else "—")
        b2.metric("Position count", f"{group['position_count']:,}")
        st.markdown("**Outcome-by-outcome exposure**")
        for outcome in group["outcomes"]:
            st.caption(
                f"{outcome['label'].upper()}: {outcome['shares']:,.4f} shares · "
                f"Cost {money(outcome['cost'])} · Value {money(outcome['value'])} · "
                f"P&L {money(outcome['pnl'])} · {outcome['positions']} position(s)"
            )
        with st.expander("Individual token positions"):
            for pos in group["positions"]:
                st.write(
                    f"**{str(pos.get('outcome', 'Unknown')).upper()}** · "
                    f"{number(pos.get('current_size')):,.4f} shares · "
                    f"Entry {number(pos.get('avg_price')):.4f} · "
                    f"Current {number(pos.get('current_price')):.4f} · "
                    f"P&L {money(pos.get('unrealized_pnl'))} · "
                    f"Archived={bool(pos.get('archived'))}"
                )
        st.caption(f"Condition ID: {group['condition']}")


st.title("📊 Polymarket → Kalshi Trading Assistant")
st.caption("Version 10 · Multi-Outcome Trader Analyzer · Public data · Read-only · Manual approval only · No automatic trading")

with st.sidebar:
    st.subheader("Research settings")
    bankroll = st.number_input("Simulated bankroll ($)", min_value=1.0, max_value=100000.0, value=55.0, step=5.0)
    st.caption("Planning value only. No Kalshi account connection or order placement.")

market_tab, trader_tab, wallet_tab, calculator_tab = st.tabs(["Economic Markets", "Trader Leaderboard", "Wallet Inspector", "Payoff Calculator"])

with market_tab:
    st.subheader("Open Kalshi economic markets")
    left, right = st.columns([1, 2])
    with left:
        selected_topic = st.selectbox("Economic category", ["All economic topics"] + list(TOPICS.keys()))
    with right:
        keyword = st.text_input("Optional keyword", placeholder="e.g. Fed, CPI, Powell, GDP")
    if st.button("Search Kalshi markets", type="primary", key="search_markets"):
        st.session_state["run_market_search"] = True
    if st.session_state.get("run_market_search"):
        try:
            with st.spinner("Loading Kalshi events and nested markets..."):
                events = fetch_kalshi_events()
            matches = []
            for event in events:
                for market in event.get("markets", []) or []:
                    searchable = " ".join([event.get("title", ""), event.get("subtitle", ""), event.get("category", ""), market.get("title", ""), market.get("subtitle", "")])
                    found = topics_for(searchable)
                    if selected_topic != "All economic topics" and selected_topic not in found:
                        continue
                    if selected_topic == "All economic topics" and not found:
                        continue
                    if keyword and not phrase_in(searchable, keyword):
                        tokens = set(re.findall(r"[a-z0-9]+", norm(searchable)))
                        if norm(keyword) not in tokens:
                            continue
                    matches.append((event, market, found))
            st.success(f"Retrieved {len(events):,} events · Found {len(matches):,} matching markets")
            if not matches:
                st.info("No matching markets found. Try a broader category or shorter keyword.")
            for event, market, found in matches[:60]:
                with st.container(border=True):
                    st.markdown(f"**{market.get('title') or event.get('title') or 'Untitled market'}**")
                    st.caption(f"{event.get('title', '')} · {' / '.join(found)}")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("YES ask", market.get("yes_ask_dollars") or (f"{market.get('yes_ask')}¢" if market.get("yes_ask") is not None else "—"))
                    c2.metric("NO ask", market.get("no_ask_dollars") or (f"{market.get('no_ask')}¢" if market.get("no_ask") is not None else "—"))
                    c3.metric("Ticker", market.get("ticker", "—"))
                    if market.get("close_time"):
                        st.caption(f"Closes: {market.get('close_time')}")
                    if market.get("rules_primary"):
                        with st.expander("Settlement rules"):
                            st.write(market.get("rules_primary"))
        except Exception as exc:
            st.error(f"Kalshi market search failed: {exc}")

with trader_tab:
    st.subheader("Find traders by reported Polymarket performance")
    st.warning("Leaderboard P&L is a ranking signal, not proof of repeatable edge. Volume is reported in shares, not dollars.")
    a, b, c, d = st.columns(4)
    with a:
        period = st.selectbox("Performance window", ["ALL", "MONTH", "WEEK", "DAY"])
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
            with st.spinner("Loading leaderboard..."):
                leaders, pagination, status, trace = fetch_leaderboard(period, category, rank_by, row_limit)
            st.caption(f"HTTP {status} · {len(leaders)} entries · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
            for row in leaders:
                wallet = wallet_of(row)
                with st.container(border=True):
                    lcol, rcol = st.columns([3, 2])
                    lcol.markdown(f"**#{row.get('rank', '—')} · {display_leader(row)}**")
                    lcol.caption(wallet or "Wallet not supplied")
                    rcol.metric("P&L", money(row.get("pnl", row.get("profit"))))
                    rcol.metric("Volume (shares)", f"{number(row.get('volume', row.get('vol'))):,.0f}")
                    if wallet and st.button("Inspect this wallet", key=f"inspect_{wallet}"):
                        st.session_state["selected_wallet"] = wallet
                        st.session_state["selected_wallet_name"] = display_leader(row)
                        st.session_state["wallet_to_analyze"] = wallet
                        st.info("Wallet selected. Open Wallet Inspector.")
            if pagination.get("has_more"):
                st.caption("More leaderboard entries may be available through cursor pagination.")
            if trace:
                st.caption(f"Trace ID: {trace}")
        except Exception as exc:
            st.error(f"Leaderboard request failed: {exc}")

with wallet_tab:
    st.subheader("Trader Strategy Analyzer")
    st.caption("Aggregates all outcome tokens by market, distinguishes binary YES/NO from named outcomes such as teams, players, OVER and UNDER, and separates archived/ended markets from active markets.")
    default_wallet = st.session_state.get("selected_wallet", "0x56687bf447db6ffa42ffe2204a05edaa20f55839")
    default_name = st.session_state.get("selected_wallet_name", "Theo4")
    st.write(f"Selected research target: **{default_name}**")
    wallet_input = st.text_input("Polymarket proxy wallet", value=default_wallet, placeholder="0x…")
    if st.button("Analyze wallet", type="primary", key="analyze_wallet"):
        st.session_state["wallet_to_analyze"] = wallet_input.strip()
    target = st.session_state.get("wallet_to_analyze", default_wallet)
    if target:
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", target):
            st.error("Enter a valid 42-character proxy wallet address beginning with 0x.")
        else:
            if st.button("Refresh wallet data", key="refresh_wallet"):
                fetch_wallet_endpoint.clear()
            try:
                with st.spinner("Loading wallet profile, holdings, combos, and diagnostics..."):
                    bundle = fetch_wallet_bundle(target)
                payloads = {k: v["payload"] for k, v in bundle.items()}
                stats = get_data(payloads["stats"]) or {}
                value_data = get_data(payloads["value"]) or {}
                open_positions = get_list(payloads["open"])
                closed_positions = get_list(payloads["closed"])
                combo_positions = get_list(payloads["combos"])
                activity = get_list(payloads["activity"])
                volume_data = get_data(payloads["volume"]) or {}
                pnl_data = get_data(payloads["pnl"])
                groups = group_positions(open_positions)
                active_groups = [g for g in groups if g["active"]]
                archived_groups = [g for g in groups if not g["active"]]
                both_sides = [g for g in groups if g["has_both_sides"]]

                v1, v2, v3, v4 = st.columns(4)
                v1.metric("Portfolio value", money(value_data.get("value")))
                v2.metric("Open token positions", f"{len(open_positions):,}")
                v3.metric("Distinct markets", f"{len(groups):,}")
                v4.metric("Markets with YES + NO", f"{len(both_sides):,}")
                st.caption(f"Proxy wallet returned by value endpoint: {value_data.get('proxy_wallet', 'not supplied')}")

                if stats:
                    all_time = stats.get("all_time_pnl") or {}
                    realized = all_time.get("realized_pnl")
                    if realized is None:
                        realized = number(all_time.get("realized_market_pnl")) + number(all_time.get("realized_combo_pnl"))
                    s1, s2, s3 = st.columns(3)
                    s1.metric("All-time realized P&L", money(realized))
                    s2.metric("Markets traded", f"{int(number(stats.get('trades'))):,}")
                    s3.metric("Lifetime volume", money(volume_data.get("volume_usdc")))

                st.markdown("### Strategy overview")
                st.write(f"**Active-market groups:** {len(active_groups)} · **Archived/ended groups:** {len(archived_groups)} · **Binary YES + NO groups:** {len(both_sides)} · **Combo positions:** {len(combo_positions)}")
                if both_sides:
                    st.warning("This trader holds YES and NO on at least one identical market. Do not copy one side in isolation without understanding the combined exposure.")


                st.markdown("#### Active-market holdings — candidates for further review")
                if active_groups:
                    for group in active_groups:
                        render_group(group)
                else:
                    st.info("No currently active-market holdings were identified. This trader's returned positions may all be archived or ended.")
                st.markdown("#### Archived / ended holdings — not copy-trading candidates")
                if archived_groups:
                    for group in archived_groups:
                        render_group(group)
                else:
                    st.success("No archived/ended holdings in the returned open-position list.")

                st.markdown("#### Combo positions")
                if combo_positions:
                    for combo in combo_positions:
                        with st.container(border=True):
                            st.markdown(f"**{combo.get('title') or combo.get('name') or 'Combo position'}**")
                            st.write(f"Status: {combo.get('status', '—')} · Value: {money(combo.get('current_value'))} · P&L: {money(combo.get('total_pnl', combo.get('unrealized_pnl')))}")
                            st.caption("Combo positions can span multiple conditions. They are intentionally not folded into single-market YES/NO exposure calculations.")
                            st.json(combo)
                else:
                    st.info("No open combo positions returned for this wallet.")

                with st.expander("Recent activity"):
                    if not activity:
                        st.info("No recent activity returned.")
                    for item in activity[:30]:
                        ts = item.get("timestamp")
                        when = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if isinstance(ts, (int, float)) else str(ts or "Time unavailable")
                        title = item.get("title") or item.get("name") or item.get("eventSlug") or "Untitled market"
                        st.write(f"**{when} · {item.get('side') or item.get('type') or 'Activity'} · {title}**")
                        st.caption(f"Outcome: {item.get('outcome', '—')} · Price: {item.get('price', '—')} · Size: {item.get('size', '—')}")

                with st.expander("Recently closed positions"):
                    if not closed_positions:
                        st.info("No closed positions returned.")
                    for pos in closed_positions[:40]:
                        st.write(f"**{pos.get('title') or 'Untitled'}** · {pos.get('outcome', '—')} · Realized P&L {money(pos.get('realized_pnl'))} · Last activity {pos.get('last_event_at', '—')}")

                with st.expander("P&L history"):
                    points = pnl_data.get("points", []) if isinstance(pnl_data, dict) else []
                    if points:
                        import pandas as pd
                        rows = []
                        for point in points:
                            stamp = point.get("timestamp")
                            if stamp is not None:
                                rows.append({"Date": datetime.fromtimestamp(stamp, timezone.utc), "Realized P&L": point.get("realized_pnl"), "Unrealized P&L": point.get("unrealized_pnl")})
                        if rows:
                            frame = pd.DataFrame(rows).set_index("Date").sort_index()
                            st.line_chart(frame)
                            st.dataframe(frame.tail(30), use_container_width=True)
                    else:
                        st.info("No P&L history returned.")

                with st.expander("API diagnostics — HTTP status, trace IDs, and raw responses"):
                    for name, result in bundle.items():
                        st.markdown(f"**{name.upper()}**")
                        if result["error"]:
                            st.error(result["error"])
                        else:
                            st.caption(f"HTTP {result['status']} · Trace ID: {result['trace'] or 'not supplied'}")
                            st.json(result["payload"])
                st.warning("Research caution: an OPEN position can belong to an archived or ended market. The app labels market availability separately from position status. Position data can be delayed or incomplete. Never copy without verifying current executable prices, depth, fees, settlement rules, and whether the trader has since changed the position.")
            except Exception as exc:
                st.error(f"Wallet analysis failed: {exc}")
                st.caption("Copy the full error text if this happens again.")

with calculator_tab:
    st.subheader("Binary contract payoff calculator")
    st.caption("Use an executable ask, not the midpoint or last-traded price.")
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
    ev = contracts * (estimated_probability / 100.0 * (1.0 - price) - (1.0 - estimated_probability / 100.0) * price - fee_per_contract)
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Contracts", f"{contracts:,}")
    q2.metric("Total cost", money(total_cost))
    q3.metric("Profit if win", money(profit_if_win))
    q4.metric("Estimated EV", money(ev))
    st.write(f"Maximum loss if it loses: **{money(total_cost)}** · Remaining bankroll: **{money(max(0, bankroll - total_cost))}**")
    st.caption("Estimate excludes unentered fees, spread changes, partial fills, slippage, and settlement risk. EV depends entirely on the probability estimate.")

st.divider()
st.subheader("Before approving any trade")
checks = [
    "The Polymarket and Kalshi contracts resolve on the same real-world event.",
    "The outcome, threshold, measurement period, deadline, and timezone match exactly.",
    "The settlement sources and exception rules are compatible.",
    "The Polymarket position is current and the trader has not exited or reversed it.",
    "The Kalshi price is an executable ask with enough order-book depth.",
    "Fees, spread, slippage, and full-stake loss are included.",
    "The stake is within the bankroll limit and affordable to lose completely.",
]
for idx, item in enumerate(checks):
    st.checkbox(item, key=f"approval_check_{idx}")

st.caption("Data sources: Polymarket public Data API and Kalshi public Trade API. Informational research only; no guaranteed signals, account connection, or automatic trading.")

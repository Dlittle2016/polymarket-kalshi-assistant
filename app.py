
import re
from datetime import datetime, timezone, date

import requests
import streamlit as st

st.set_page_config(
    page_title="Polymarket → Kalshi Assistant",
    page_icon="📊",
    layout="wide",
)

POLY_BASE = "https://data-api.polymarket.com"
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MarketResearchAssistant/12.0)"
}

TOPICS = {
    "Federal Reserve": [
        "federal reserve", "fomc", "fed funds", "federal funds rate",
        "interest rate", "rate decision", "rate cut", "rate hike",
        "rate increase", "rate reduction", "monetary policy",
        "fed chair", "fed meeting",
    ],
    "Inflation": [
        "inflation", "cpi", "core cpi", "pce", "ppi", "price index",
    ],
    "Employment": [
        "unemployment", "nonfarm payrolls", "jobs report",
        "jobless claims", "employment", "labor market",
        "payrolls", "job creation",
    ],
    "Economic Growth": [
        "gdp", "economic growth", "recession", "contraction",
        "expansion",
    ],
    "Consumer Economy": [
        "retail sales", "consumer spending", "consumer confidence",
        "consumer sentiment", "personal income", "personal spending",
    ],
    "Housing": [
        "housing starts", "home sales", "home prices",
        "housing market", "building permits", "mortgage rates",
    ],
    "Treasury & Bonds": [
        "treasury yields", "10-year yield", "2-year yield",
        "bond yield", "treasury bonds", "treasury rate",
    ],
    "Business & Manufacturing": [
        "manufacturing", "industrial production", "pmi", "ism",
        "business activity", "factory orders", "durable goods",
    ],
}


# ============================================================
# GENERAL HELPERS
# ============================================================

def get_json(url, params=None, timeout=25):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()

    return (
        response.json(),
        response.status_code,
        response.headers.get("x-request-id")
        or response.headers.get("x-trace-id"),
    )


def data_rows(payload):
    if isinstance(payload, list):
        return payload

    data = payload.get("data", []) if isinstance(payload, dict) else []

    if isinstance(data, dict):
        for key in (
            "positions",
            "results",
            "items",
            "data",
            "leaderboard",
        ):
            if isinstance(data.get(key), list):
                return data[key]

        return []

    return data if isinstance(data, list) else []


def norm(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "").lower(),
    ).strip()


def phrase_in(text, phrase):
    clean_text = (
        " "
        + re.sub(r"[^a-z0-9]+", " ", norm(text))
        + " "
    )

    clean_phrase = (
        " "
        + re.sub(r"[^a-z0-9]+", " ", norm(phrase))
        + " "
    )

    return clean_phrase in clean_text


def topics_for(text):
    return [
        topic
        for topic, phrases in TOPICS.items()
        if any(phrase_in(text, phrase) for phrase in phrases)
    ]


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
    candidates = [
        row.get(key)
        for key in (
            "proxyWallet",
            "proxy_wallet",
            "proxy_wallet_address",
            "user_id",
            "userId",
            "wallet",
            "address",
            "user",
        )
    ]

    for value in candidates:
        if (
            isinstance(value, str)
            and re.fullmatch(r"0x[a-fA-F0-9]{40}", value)
        ):
            return value

    for value in row.values():
        if isinstance(value, dict):
            found = wallet_of(value)
            if found:
                return found

    return ""


def display_leader(row):
    for key in (
        "userName",
        "user_name",
        "username",
        "name",
        "displayName",
        "display_name",
        "pseudonym",
    ):
        if row.get(key):
            return str(row[key])

    wallet = wallet_of(row)

    return wallet[:10] + "…" if wallet else "Anonymous trader"


def market_is_active(pos):
    if pos.get("archived") is True:
        return False

    raw = (
        pos.get("end_date")
        or pos.get("endDate")
        or pos.get("end_date_iso")
    )

    if raw:
        try:
            end_day = datetime.fromisoformat(
                str(raw).replace("Z", "+00:00")
            ).date()

            return end_day >= datetime.now(timezone.utc).date()

        except ValueError:
            try:
                return (
                    date.fromisoformat(str(raw)[:10])
                    >= datetime.now(timezone.utc).date()
                )
            except ValueError:
                pass

    return True


# ============================================================
# KALSHI MARKET DATA
# ============================================================

@st.cache_data(ttl=45, show_spinner=False)
def fetch_kalshi_events(max_pages=10):
    events = []
    cursor = None

    for _ in range(max_pages):
        params = {
            "status": "open",
            "limit": 200,
            "with_nested_markets": "true",
        }

        if cursor:
            params["cursor"] = cursor

        payload, _, _ = get_json(
            f"{KALSHI_BASE}/events",
            params,
        )

        events.extend(payload.get("events", []) or [])

        cursor = payload.get("cursor")

        if not cursor:
            break

    return events


# ============================================================
# POLYMARKET LEADERBOARD
# ============================================================

@st.cache_data(ttl=120, show_spinner=False)
def fetch_leaderboard(period, category, sort_by, limit):
    params = {
        "time_period": period.lower(),
        "category": category.lower(),
        "sort_by": sort_by.upper(),
        "limit": int(limit),
    }

    payload, status, trace = get_json(
        f"{POLY_BASE}/v2/leaderboard",
        params,
    )

    rows = data_rows(payload)

    if (
        not rows
        and isinstance(payload, dict)
        and isinstance(payload.get("leaderboard"), list)
    ):
        rows = payload["leaderboard"]

    pagination = (
        payload.get("pagination", {})
        if isinstance(payload, dict)
        else {}
    )

    return rows, pagination, status, trace


# ============================================================
# POLYMARKET WALLET DATA
# ============================================================

@st.cache_data(ttl=90, show_spinner=False)
def fetch_wallet_endpoint(path, wallet, params=None, ttl_marker=""):
    query = {"user": wallet}

    if params:
        query.update(params)

    payload, status, trace = get_json(
        f"{POLY_BASE}{path}",
        query,
    )

    return payload, status, trace


def fetch_wallet_bundle(wallet):
    results = {}

    calls = {
        "stats": ("/v2/user-stats", {}),
        "value": ("/v2/value", {}),
        "open": (
            "/v2/positions",
            {
                "status": "OPEN",
                "limit": 100,
                "sort_by": "CURRENT_VALUE",
                "sort_direction": "DESC",
                "include_archived": "true",
                "filter_amount": 0,
            },
        ),
        "closed": (
            "/v2/positions",
            {
                "status": "CLOSED",
                "limit": 100,
                "sort_by": "REALIZED_PNL",
                "sort_direction": "DESC",
            },
        ),
        "combos": (
            "/v2/positions/combos",
            {
                "status": "OPEN",
                "limit": 100,
            },
        ),
        "activity": (
            "/v2/activity",
            {
                "limit": 100,
                "sort_by": "TIMESTAMP",
                "sort_direction": "DESC",
            },
        ),
        "pnl": (
            "/v2/user-pnl",
            {
                "interval": "max",
                "fidelity": "1d",
            },
        ),
        "volume": ("/v2/user-volume", {}),
    }

    for name, (path, params) in calls.items():
        try:
            payload, status, trace = fetch_wallet_endpoint(
                path,
                wallet,
                params,
            )

            results[name] = {
                "payload": payload,
                "status": status,
                "trace": trace,
                "error": None,
            }

        except Exception as exc:
            results[name] = {
                "payload": {},
                "status": None,
                "trace": None,
                "error": str(exc),
            }

    return results


def get_data(payload):
    return payload.get("data") if isinstance(payload, dict) else None


def get_list(payload):
    return data_rows(payload)


# ============================================================
# MARKET POSITION GROUPING
# ============================================================

def group_positions(positions):
    """Group all outcome tokens belonging to the same market condition."""

    groups = {}

    for pos in positions:
        condition = str(
            pos.get("condition_id")
            or pos.get("conditionId")
            or pos.get("slug")
            or pos.get("title")
            or "unknown"
        )

        group = groups.setdefault(
            condition,
            {
                "condition": condition,
                "title": pos.get("title") or pos.get("name") or "Untitled market",
                "positions": [],
                "outcomes": {},
                "yes_shares": 0.0,
                "no_shares": 0.0,
                "yes_cost": 0.0,
                "no_cost": 0.0,
                "yes_value": 0.0,
                "no_value": 0.0,
                "yes_pnl": 0.0,
                "no_pnl": 0.0,
                "archived": False,
                "end_date": pos.get("end_date"),
                "active": True,
            },
        )

        group["positions"].append(pos)

        outcome_raw = pos.get("outcome") or "Unknown outcome"
        outcome_key = norm(outcome_raw) or "unknown outcome"

        shares = number(pos.get("current_size"))

        cost = number(
            pos.get(
                "total_cost_usdc",
                pos.get("entry_cost_usdc"),
            )
        )

        value = number(pos.get("current_value"))

        pnl = number(
            pos.get(
                "unrealized_pnl",
                pos.get("total_pnl"),
            )
        )

        outcome = group["outcomes"].setdefault(
            outcome_key,
            {
                "label": str(outcome_raw),
                "shares": 0.0,
                "cost": 0.0,
                "value": 0.0,
                "pnl": 0.0,
                "positions": 0,
            },
        )

        outcome["shares"] += shares
        outcome["cost"] += cost
        outcome["value"] += value
        outcome["pnl"] += pnl
        outcome["positions"] += 1

        # Only actual YES and NO labels count as binary sides.
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

        group["archived"] = (
            group["archived"] or bool(pos.get("archived"))
        )

        group["active"] = (
            group["active"] and market_is_active(pos)
        )

        if pos.get("end_date"):
            group["end_date"] = pos.get("end_date")

    for group in groups.values():
        group["total_cost"] = sum(
            item["cost"]
            for item in group["outcomes"].values()
        )

        group["total_value"] = sum(
            item["value"]
            for item in group["outcomes"].values()
        )

        group["total_pnl"] = sum(
            item["pnl"]
            for item in group["outcomes"].values()
        )

        group["net_yes_shares"] = (
            group["yes_shares"] - group["no_shares"]
        )

        group["has_both_sides"] = (
            group["yes_shares"] > 0
            and group["no_shares"] > 0
        )

        group["outcome_count"] = len(group["outcomes"])

        group["has_multiple_outcomes"] = (
            group["outcome_count"] > 1
        )

        group["position_count"] = len(group["positions"])

        group["outcomes"] = sorted(
            group["outcomes"].values(),
            key=lambda item: item["value"],
            reverse=True,
        )

    return list(groups.values())


# ============================================================
# MARKET CLASSIFICATION
# ============================================================

def classify_market(title):
    text = norm(title)
    found = topics_for(title)

    if found:
        return found[0]

    if any(
        item in text
        for item in (
            "bitcoin", "btc", "ethereum", "eth",
            "solana", "crypto",
        )
    ):
        return "Crypto"

    if any(
        item in text
        for item in (
            "nba", "nfl", "mlb", "nhl", "soccer",
            "football", "tennis", "match", "vs.",
            " vs ", "counter-strike", "esports",
            "over/under", "o/u",
        )
    ):
        return "Sports & Esports"

    if any(
        item in text
        for item in (
            "election", "president", "congress",
            "senate", "governor", "politics",
        )
    ):
        return "Politics"

    return "Other / Unclassified"


# ============================================================
# WALLET INTELLIGENCE ANALYSIS ENGINE
# ============================================================

def analyze_wallet_strategy(
    open_positions,
    closed_positions,
    activity,
    pnl_history,
    combo_positions,
    wallet_stats,
    market_metadata=None,
):
    """
    Reusable evidence-led wallet analysis.

    Separates observed API data, arithmetic, and cautious
    interpretations. Does not claim to know trader intent.
    """

    groups = group_positions(open_positions or [])

    active_groups = [
        group for group in groups if group["active"]
    ]

    ended_groups = [
        group for group in groups if not group["active"]
    ]

    total_cost = sum(
        group["total_cost"]
        for group in active_groups
    )

    total_value = sum(
        group["total_value"]
        for group in active_groups
    )

    total_unrealized = sum(
        group["total_pnl"]
        for group in active_groups
    )

    all_open_cost = sum(
        group["total_cost"]
        for group in groups
    )

    # Category exposure
    category_totals = {}

    for group in active_groups:
        category = classify_market(group["title"])

        bucket = category_totals.setdefault(
            category,
            {
                "markets": 0,
                "cost": 0.0,
                "value": 0.0,
                "pnl": 0.0,
            },
        )

        bucket["markets"] += 1
        bucket["cost"] += group["total_cost"]
        bucket["value"] += group["total_value"]
        bucket["pnl"] += group["total_pnl"]

    market_rows = []
    scenario_rows = []

    one_sided = []
    multi_outcome = []
    expensive_two_sided = []

    for group in active_groups:
        outcomes = group["outcomes"]
        cost = group["total_cost"]

        scenarios = []

        for outcome in outcomes:
            payout = outcome["shares"]
            net = payout - cost

            scenarios.append(net)

            scenario_rows.append(
                {
                    "Market": group["title"],
                    "If this outcome wins": outcome["label"],
                    "Approx. payout": payout,
                    "Net vs. total cost": net,
                    "Assumption": (
                        "$1 per winning share; excludes fees "
                        "and execution costs"
                    ),
                }
            )

        best_held = max(scenarios) if scenarios else None
        worst_held = min(scenarios) if scenarios else None

        # If an unheld outcome wins, all held tokens could pay zero.
        worst_all = (
            min(worst_held, -cost)
            if worst_held is not None
            else -cost
        )

        market_rows.append(
            {
                "Market": group["title"],
                "Outcomes held": len(outcomes),
                "Position count": group["position_count"],
                "Cost": cost,
                "Current value": group["total_value"],
                "Unrealized P&L": group["total_pnl"],
                "Return %": (
                    group["total_pnl"] / cost * 100
                    if cost
                    else None
                ),
                "Largest outcome share %": (
                    max(
                        (item["cost"] for item in outcomes),
                        default=0,
                    ) / cost * 100
                    if cost
                    else None
                ),
                "Best held-outcome net": best_held,
                "Worst held-outcome net": worst_held,
                "Worst case if an unheld outcome can win": worst_all,
                "Outcome set completeness": (
                    "Not verified"
                    if len(outcomes) > 1
                    else "Single held outcome; other outcomes may exist"
                ),
            }
        )

        if len(outcomes) == 1:
            one_sided.append(group)

        if len(outcomes) > 1:
            multi_outcome.append(group)

            if scenarios and all(value < 0 for value in scenarios):
                expensive_two_sided.append(group)

    market_rows.sort(
        key=lambda item: item["Cost"],
        reverse=True,
    )

    scenario_rows.sort(
        key=lambda item: item["Net vs. total cost"],
    )

    largest_market = max(
        active_groups,
        key=lambda group: group["total_cost"],
        default=None,
    )

    largest_exposure_pct = (
        largest_market["total_cost"] / total_cost * 100
        if largest_market and total_cost
        else 0.0
    )

    # Closed-position sample
    realized_values = [
        number(item.get("realized_pnl"))
        for item in (closed_positions or [])
        if item.get("realized_pnl") is not None
    ]

    closed_realized = (
        sum(realized_values)
        if realized_values
        else None
    )

    stats = wallet_stats or {}

    all_time = stats.get("all_time_pnl") or {}

    if not isinstance(all_time, dict):
        all_time = {}

    reported_realized = all_time.get("realized_pnl")

    if (
        reported_realized is None
        and (
            "realized_market_pnl" in all_time
            or "realized_combo_pnl" in all_time
        )
    ):
        reported_realized = (
            number(all_time.get("realized_market_pnl"))
            + number(all_time.get("realized_combo_pnl"))
        )

    pnl_points = (
        pnl_history.get("points", [])
        if isinstance(pnl_history, dict)
        else []
    )

    activity_types = {}

    for item in activity or []:
        kind = str(
            item.get("type")
            or item.get("side")
            or "Unknown"
        )

        activity_types[kind] = (
            activity_types.get(kind, 0) + 1
        )

    # Data coverage warnings
    warnings = []

    if not open_positions:
        warnings.append(
            "No open-position rows were returned. "
            "Current exposure and style conclusions are limited."
        )

    if not closed_positions:
        warnings.append(
            "No closed-position rows were returned. "
            "A complete realized win rate cannot be calculated."
        )

    if not activity:
        warnings.append(
            "No activity rows were returned. "
            "Entry timing, exits, and trade sequencing cannot be inferred."
        )

    if not pnl_points:
        warnings.append(
            "No P&L history points were returned. "
            "Performance trend and drawdown cannot be assessed."
        )

    if not combo_positions:
        warnings.append(
            "No combo positions were returned. "
            "This may mean none exist or the endpoint returned no data."
        )

    if len(open_positions or []) >= 100:
        warnings.append(
            "The open-position response reached 100 rows. "
            "Holdings may be paginated or truncated."
        )

    if len(closed_positions or []) >= 100:
        warnings.append(
            "The closed-position response reached 100 rows. "
            "The realized-performance sample may be incomplete."
        )

    if len(activity or []) >= 100:
        warnings.append(
            "The activity response reached 100 rows. "
            "Behavioral analysis may be based on a partial sample."
        )

    # Evidence-based observations
    observations = []

    if active_groups:
        observations.append(
            f"The wallet has {len(active_groups)} active-market "
            f"groups with approximately {money(total_cost)} "
            "in reported entry cost."
        )

    if one_sided:
        observations.append(
            f"{len(one_sided)} active groups have only one outcome "
            "represented in the returned positions. This does not "
            "prove that no other outcome tokens exist."
        )

    if multi_outcome:
        observations.append(
            f"{len(multi_outcome)} active groups contain multiple "
            "distinct outcomes. These need settlement-scenario "
            "analysis rather than a simple YES/NO label."
        )

    if expensive_two_sided:
        observations.append(
            f"{len(expensive_two_sided)} multi-outcome groups have "
            "negative net results in every currently held-outcome "
            "scenario. Unheld outcomes and data completeness still "
            "need checking."
        )

    if largest_market:
        observations.append(
            f"The largest active market accounts for "
            f"{largest_exposure_pct:.1f}% of active reported cost: "
            f"{largest_market['title']}."
        )

    return {
        "groups": groups,
        "active_groups": active_groups,
        "ended_groups": ended_groups,
        "total_active_cost": total_cost,
        "total_active_value": total_value,
        "total_active_unrealized_pnl": total_unrealized,
        "all_open_cost": all_open_cost,
        "category_totals": category_totals,
        "market_rows": market_rows,
        "scenario_rows": scenario_rows,
        "one_sided_groups": one_sided,
        "multi_outcome_groups": multi_outcome,
        "negative_all_held_scenarios": expensive_two_sided,
        "largest_market": largest_market,
        "largest_exposure_pct": largest_exposure_pct,
        "closed_realized_sample": closed_realized,
        "reported_realized": reported_realized,
        "closed_count": len(closed_positions or []),
        "activity_count": len(activity or []),
        "activity_types": activity_types,
        "pnl_point_count": len(pnl_points),
        "combo_count": len(combo_positions or []),
        "observations": observations,
        "warnings": warnings,
    }


# ============================================================
# WALLET INTELLIGENCE REPORT
# ============================================================

def render_wallet_intelligence(analysis):
    st.markdown("### Wallet Intelligence")

    st.caption(
        "Reusable analysis of the selected wallet. "
        "Observations are calculated from returned data; "
        "interpretations are not claims about the trader's intent."
    )

    a, b, c, d = st.columns(4)

    a.metric(
        "Active-market entry cost",
        money(analysis["total_active_cost"]),
    )

    b.metric(
        "Active unrealized P&L",
        money(analysis["total_active_unrealized_pnl"]),
    )

    c.metric(
        "Multi-outcome markets",
        f"{len(analysis['multi_outcome_groups']):,}",
    )

    d.metric(
        "Largest-market concentration",
        f"{analysis['largest_exposure_pct']:.1f}%",
    )

    if analysis["observations"]:
        st.markdown("**What the returned data shows**")

        for item in analysis["observations"]:
            st.write(f"• {item}")

    else:
        st.info(
            "There is not enough returned position data "
            "to produce meaningful wallet observations."
        )

    if analysis["category_totals"]:
        st.markdown("#### Exposure by market category")

        import pandas as pd

        rows = []

        for category, values in sorted(
            analysis["category_totals"].items(),
            key=lambda item: item[1]["cost"],
            reverse=True,
        ):
            rows.append(
                {
                    "Category": category,
                    "Markets": values["markets"],
                    "Entry cost": values["cost"],
                    "Current value": values["value"],
                    "Unrealized P&L": values["pnl"],
                }
            )

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )

    if analysis["market_rows"]:
        st.markdown("#### Largest active exposures")

        import pandas as pd

        df = pd.DataFrame(
            analysis["market_rows"][:20]
        )

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

    if analysis["scenario_rows"]:
        with st.expander(
            "Settlement scenarios for held outcomes"
        ):
            import pandas as pd

            st.dataframe(
                pd.DataFrame(analysis["scenario_rows"]),
                use_container_width=True,
                hide_index=True,
            )

            st.caption(
                "Approximation: a winning outcome token pays "
                "$1 per share. This is not a guaranteed maximum "
                "or minimum payoff calculation unless the full "
                "outcome set, contract mechanics, fees, and all "
                "related positions are verified."
            )

    if analysis["activity_types"]:
        with st.expander("Activity sample"):
            st.write(
                "Activity types in the returned sample:"
            )

            st.json(analysis["activity_types"])

    with st.expander("Data coverage and confidence limits"):
        st.write(
            f"Returned rows: "
            f"{analysis['closed_count']} closed positions · "
            f"{analysis['activity_count']} activity events · "
            f"{analysis['pnl_point_count']} P&L history points · "
            f"{analysis['combo_count']} combo positions"
        )

        if analysis["reported_realized"] is not None:
            st.write(
                "API-reported all-time realized P&L: "
                f"**{money(analysis['reported_realized'])}**"
            )

        if analysis["closed_realized_sample"] is not None:
            st.write(
                "Sum of realized P&L in returned closed-position "
                f"sample: **{money(analysis['closed_realized_sample'])}**"
            )

            st.caption(
                "These totals may differ because the closed-position "
                "endpoint may be paginated and the all-time statistic "
                "may include combo results."
            )

        for warning in analysis["warnings"]:
            st.warning(warning)


# ============================================================
# INDIVIDUAL MARKET DISPLAY
# ============================================================

def render_group(group):
    with st.container(border=True):
        label = (
            "ACTIVE MARKET"
            if group["active"]
            else "ARCHIVED / ENDED MARKET"
        )

        st.markdown(f"**{group['title']}**")

        st.caption(
            f"{label} · "
            f"{group['position_count']} token position(s) · "
            f"{group['outcome_count']} distinct outcome(s) · "
            f"End date: {group['end_date'] or 'not supplied'}"
        )

        if group["has_both_sides"]:
            st.warning(
                "BINARY OPPOSITE-SIDE HOLDING: "
                "both YES and NO are held in this same condition."
            )

        elif group["has_multiple_outcomes"]:
            st.info(
                "MULTI-OUTCOME EXPOSURE: this market uses named "
                "outcomes. These are not being misclassified as YES/NO."
            )

        a1, a2, a3, a4 = st.columns(4)

        a1.metric(
            "Distinct outcomes",
            f"{group['outcome_count']:,}",
        )

        a2.metric(
            "Combined cost",
            money(group["total_cost"]),
        )

        a3.metric(
            "Combined value",
            money(group["total_value"]),
        )

        a4.metric(
            "Combined P&L",
            money(group["total_pnl"]),
        )

        b1, b2 = st.columns(2)

        b1.metric(
            "Combined return",
            (
                f"{group['total_pnl'] / group['total_cost'] * 100:.2f}%"
                if group["total_cost"]
                else "—"
            ),
        )

        b2.metric(
            "Position count",
            f"{group['position_count']:,}",
        )

        st.markdown("**Outcome-by-outcome exposure**")

        for outcome in group["outcomes"]:
            st.caption(
                f"{outcome['label'].upper()}: "
                f"{outcome['shares']:,.4f} shares · "
                f"Cost {money(outcome['cost'])} · "
                f"Value {money(outcome['value'])} · "
                f"P&L {money(outcome['pnl'])} · "
                f"{outcome['positions']} position(s)"
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

        st.caption(
            f"Condition ID: {group['condition']}"
        )


# ============================================================
# APP HEADER
# ============================================================

st.title("📊 Polymarket → Kalshi Trading Assistant")

st.caption(
    "Version 12 · Wallet Intelligence · Public data · "
    "Read-only · Manual approval only · No automatic trading"
)

with st.sidebar:
    st.subheader("Research settings")

    bankroll = st.number_input(
        "Simulated bankroll ($)",
        min_value=1.0,
        max_value=100000.0,
        value=55.0,
        step=5.0,
    )

    st.caption(
        "Planning value only. No Kalshi account connection "
        "or order placement."
    )


market_tab, trader_tab, wallet_tab, calculator_tab = st.tabs(
    [
        "Economic Markets",
        "Trader Leaderboard",
        "Wallet Inspector",
        "Payoff Calculator",
    ]
)


# ============================================================
# TAB 1: KALSHI ECONOMIC MARKETS
# ============================================================

with market_tab:
    st.subheader("Open Kalshi economic markets")

    left, right = st.columns([1, 2])

    with left:
        selected_topic = st.selectbox(
            "Economic category",
            ["All economic topics"] + list(TOPICS.keys()),
        )

    with right:
        keyword = st.text_input(
            "Optional keyword",
            placeholder="e.g. Fed, CPI, Powell, GDP",
        )

    if st.button(
        "Search Kalshi markets",
        type="primary",
        key="search_markets",
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
                for market in event.get("markets", []) or []:
                    searchable = " ".join(
                        [
                            event.get("title", ""),
                            event.get("subtitle", ""),
                            event.get("category", ""),
                            market.get("title", ""),
                            market.get("subtitle", ""),
                        ]
                    )

                    found = topics_for(searchable)

                    if (
                        selected_topic != "All economic topics"
                        and selected_topic not in found
                    ):
                        continue

                    if (
                        selected_topic == "All economic topics"
                        and not found
                    ):
                        continue

                    if keyword and not phrase_in(
                        searchable,
                        keyword,
                    ):
                        tokens = set(
                            re.findall(
                                r"[a-z0-9]+",
                                norm(searchable),
                            )
                        )

                        if norm(keyword) not in tokens:
                            continue

                    matches.append(
                        (event, market, found)
                    )

            st.success(
                f"Retrieved {len(events):,} events · "
                f"Found {len(matches):,} matching markets"
            )

            if not matches:
                st.info(
                    "No matching markets found. "
                    "Try a broader category or shorter keyword."
                )

            for event, market, found in matches[:60]:
                with st.container(border=True):
                    st.markdown(
                        f"**{market.get('title') or event.get('title') or 'Untitled market'}**"
                    )

                    st.caption(
                        f"{event.get('title', '')} · "
                        f"{' / '.join(found)}"
                    )

                    c1, c2, c3 = st.columns(3)

                    c1.metric(
                        "YES ask",
                        market.get("yes_ask_dollars")
                        or (
                            f"{market.get('yes_ask')}¢"
                            if market.get("yes_ask") is not None
                            else "—"
                        ),
                    )

                    c2.metric(
                        "NO ask",
                        market.get("no_ask_dollars")
                        or (
                            f"{market.get('no_ask')}¢"
                            if market.get("no_ask") is not None
                            else "—"
                        ),
                    )

                    c3.metric(
                        "Ticker",
                        market.get("ticker", "—"),
                    )

                    if market.get("close_time"):
                        st.caption(
                            f"Closes: {market.get('close_time')}"
                        )

                    if market.get("rules_primary"):
                        with st.expander("Settlement rules"):
                            st.write(market.get("rules_primary"))

        except Exception as exc:
            st.error(
                f"Kalshi market search failed: {exc}"
            )


# ============================================================
# TAB 2: POLYMARKET TRADER LEADERBOARD
# ============================================================

with trader_tab:
    st.subheader(
        "Find traders by reported Polymarket performance"
    )

    st.warning(
        "Leaderboard P&L is a ranking signal, not proof of "
        "repeatable edge. Volume is reported in shares, not dollars."
    )

    a, b, c, d = st.columns(4)

    with a:
        period = st.selectbox(
            "Performance window",
            ["ALL", "MONTH", "WEEK", "DAY"],
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
                "MENTIONS",
            ],
        )

    with c:
        rank_by = st.selectbox(
            "Rank by",
            ["PNL", "VOLUME"],
        )

    with d:
        row_limit = st.selectbox(
            "Rows",
            [10, 25, 50],
            index=1,
        )

    if st.button(
        "Load Polymarket leaderboard",
        type="primary",
        key="load_leaderboard",
    ):
        st.session_state["run_leaderboard"] = True

    if st.session_state.get("run_leaderboard"):
        try:
            with st.spinner("Loading leaderboard..."):
                leaders, pagination, status, trace = (
                    fetch_leaderboard(
                        period,
                        category,
                        rank_by,
                        row_limit,
                    )
                )

            st.caption(
                f"HTTP {status} · {len(leaders)} entries · "
                f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            )

            for row in leaders:
                wallet = wallet_of(row)

                with st.container(border=True):
                    lcol, rcol = st.columns([3, 2])

                    lcol.markdown(
                        f"**#{row.get('rank', '—')} · "
                        f"{display_leader(row)}**"
                    )

                    lcol.caption(
                        wallet or "Wallet not supplied"
                    )

                    rcol.metric(
                        "P&L",
                        money(row.get("pnl", row.get("profit"))),
                    )

                    rcol.metric(
                        "Volume (shares)",
                        f"{number(row.get('volume', row.get('vol'))):,.0f}",
                    )

                    if wallet and st.button(
                        "Inspect this wallet",
                        key=f"inspect_{wallet}",
                    ):
                        st.session_state["selected_wallet"] = wallet
                        st.session_state["selected_wallet_name"] = (
                            display_leader(row)
                        )
                        st.session_state["wallet_to_analyze"] = wallet

                        st.info(
                            "Wallet selected. Open Wallet Inspector."
                        )

            if pagination.get("has_more"):
                st.caption(
                    "More leaderboard entries may be available "
                    "through cursor pagination."
                )

            if trace:
                st.caption(f"Trace ID: {trace}")

        except Exception as exc:
            st.error(
                f"Leaderboard request failed: {exc}"
            )


# ============================================================
# TAB 3: WALLET INSPECTOR + WALLET INTELLIGENCE
# ============================================================

with wallet_tab:
    st.subheader("Trader Strategy Analyzer")

    st.caption(
        "Aggregates all outcome tokens by market, distinguishes "
        "binary YES/NO from named outcomes such as teams, players, "
        "OVER and UNDER, and separates archived/ended markets "
        "from active markets."
    )

    default_wallet = st.session_state.get(
        "selected_wallet",
        "0x56687bf447db6ffa42ffe2204a05edaa20f55839",
    )

    default_name = st.session_state.get(
        "selected_wallet_name",
        "Theo4",
    )

    st.write(
        f"Selected research target: **{default_name}**"
    )

    wallet_input = st.text_input(
        "Polymarket proxy wallet",
        value=default_wallet,
        placeholder="0x…",
    )

    if st.button(
        "Analyze wallet",
        type="primary",
        key="analyze_wallet",
    ):
        st.session_state["wallet_to_analyze"] = (
            wallet_input.strip()
        )

    target = st.session_state.get(
        "wallet_to_analyze",
        default_wallet,
    )

    if target:
        if not re.fullmatch(
            r"0x[a-fA-F0-9]{40}",
            target,
        ):
            st.error(
                "Enter a valid 42-character proxy wallet "
                "address beginning with 0x."
            )

        else:
            if st.button(
                "Refresh wallet data",
                key="refresh_wallet",
            ):
                fetch_wallet_endpoint.clear()

            try:
                with st.spinner(
                    "Loading wallet profile, holdings, combos, "
                    "and diagnostics..."
                ):
                    bundle = fetch_wallet_bundle(target)

                payloads = {
                    key: result["payload"]
                    for key, result in bundle.items()
                }

                stats = get_data(
                    payloads["stats"]
                ) or {}

                value_data = get_data(
                    payloads["value"]
                ) or {}

                open_positions = get_list(
                    payloads["open"]
                )

                closed_positions = get_list(
                    payloads["closed"]
                )

                combo_positions = get_list(
                    payloads["combos"]
                )

                activity = get_list(
                    payloads["activity"]
                )

                volume_data = get_data(
                    payloads["volume"]
                ) or {}

                pnl_data = get_data(
                    payloads["pnl"]
                )

                # Build the reusable analysis object.
                analysis = analyze_wallet_strategy(
                    open_positions=open_positions,
                    closed_positions=closed_positions,
                    activity=activity,
                    pnl_history=pnl_data,
                    combo_positions=combo_positions,
                    wallet_stats=stats,
                    market_metadata={},
                )

                groups = analysis["groups"]
                active_groups = analysis["active_groups"]
                archived_groups = analysis["ended_groups"]

                both_sides = [
                    group
                    for group in groups
                    if group["has_both_sides"]
                ]

                # Portfolio overview
                v1, v2, v3, v4 = st.columns(4)

                v1.metric(
                    "Portfolio value",
                    money(value_data.get("value")),
                )

                v2.metric(
                    "Open token positions",
                    f"{len(open_positions):,}",
                )

                v3.metric(
                    "Distinct markets",
                    f"{len(groups):,}",
                )

                v4.metric(
                    "Markets with YES + NO",
                    f"{len(both_sides):,}",
                )

                st.caption(
                    "Proxy wallet returned by value endpoint: "
                    f"{value_data.get('proxy_wallet', 'not supplied')}"
                )

                # Lifetime statistics
                if stats:
                    all_time = stats.get("all_time_pnl") or {}

                    if not isinstance(all_time, dict):
                        all_time = {}

                    realized = all_time.get("realized_pnl")

                    if realized is None:
                        realized = (
                            number(
                                all_time.get("realized_market_pnl")
                            )
                            + number(
                                all_time.get("realized_combo_pnl")
                            )
                        )

                    s1, s2, s3 = st.columns(3)

                    s1.metric(
                        "All-time realized P&L",
                        money(realized),
                    )

                    s2.metric(
                        "Markets traded",
                        f"{int(number(stats.get('trades'))):,}",
                    )

                    s3.metric(
                        "Lifetime volume",
                        money(volume_data.get("volume_usdc")),
                    )

                # Strategy overview
                st.markdown("### Strategy overview")

                st.write(
                    f"**Active-market groups:** {len(active_groups)} · "
                    f"**Archived/ended groups:** {len(archived_groups)} · "
                    f"**Binary YES + NO groups:** {len(both_sides)} · "
                    f"**Combo positions:** {len(combo_positions)}"
                )

                if both_sides:
                    st.warning(
                        "This trader holds YES and NO on at least "
                        "one identical market. Do not copy one side "
                        "in isolation without understanding the "
                        "combined exposure."
                    )

                # IMPORTANT: Wallet Intelligence report.
                # This is intentionally between Strategy Overview
                # and Active-market holdings.
                render_wallet_intelligence(analysis)

                # Active holdings
                st.markdown(
                    "#### Active-market holdings — candidates for further review"
                )

                if active_groups:
                    for group in active_groups:
                        render_group(group)

                else:
                    st.info(
                        "No currently active-market holdings were "
                        "identified. This trader's returned positions "
                        "may all be archived or ended."
                    )

                # Archived holdings
                st.markdown(
                    "#### Archived / ended holdings — not copy-trading candidates"
                )

                if archived_groups:
                    for group in archived_groups:
                        render_group(group)

                else:
                    st.success(
                        "No archived/ended holdings in the returned "
                        "open-position list."
                    )

                # Combo positions
                st.markdown("#### Combo positions")

                if combo_positions:
                    for combo in combo_positions:
                        with st.container(border=True):
                            st.markdown(
                                f"**{combo.get('title') or combo.get('name') or 'Combo position'}**"
                            )

                            st.write(
                                f"Status: {combo.get('status', '—')} · "
                                f"Value: {money(combo.get('current_value'))} · "
                                f"P&L: {money(combo.get('total_pnl', combo.get('unrealized_pnl')))}"
                            )

                            st.caption(
                                "Combo positions can span multiple "
                                "conditions. They are intentionally "
                                "not folded into single-market "
                                "YES/NO exposure calculations."
                            )

                            st.json(combo)

                else:
                    st.info(
                        "No open combo positions returned for this wallet."
                    )

                # Recent activity
                with st.expander("Recent activity"):
                    if not activity:
                        st.info(
                            "No recent activity returned."
                        )

                    for item in activity[:30]:
                        ts = item.get("timestamp")

                        if isinstance(ts, (int, float)):
                            when = datetime.fromtimestamp(
                                ts,
                                timezone.utc,
                            ).strftime("%Y-%m-%d %H:%M UTC")
                        else:
                            when = str(
                                ts or "Time unavailable"
                            )

                        title = (
                            item.get("title")
                            or item.get("name")
                            or item.get("eventSlug")
                            or "Untitled market"
                        )

                        st.write(
                            f"**{when} · "
                            f"{item.get('side') or item.get('type') or 'Activity'} · "
                            f"{title}**"
                        )

                        st.caption(
                            f"Outcome: {item.get('outcome', '—')} · "
                            f"Price: {item.get('price', '—')} · "
                            f"Size: {item.get('size', '—')}"
                        )

                # Recently closed positions
                with st.expander("Recently closed positions"):
                    if not closed_positions:
                        st.info(
                            "No closed positions returned."
                        )

                    for pos in closed_positions[:40]:
                        st.write(
                            f"**{pos.get('title') or 'Untitled'}** · "
                            f"{pos.get('outcome', '—')} · "
                            f"Realized P&L {money(pos.get('realized_pnl'))} · "
                            f"Last activity {pos.get('last_event_at', '—')}"
                        )

                # P&L history
                with st.expander("P&L history"):
                    points = (
                        pnl_data.get("points", [])
                        if isinstance(pnl_data, dict)
                        else []
                    )

                    if points:
                        import pandas as pd

                        rows = []

                        for point in points:
                            stamp = point.get("timestamp")

                            if stamp is not None:
                                rows.append(
                                    {
                                        "Date": datetime.fromtimestamp(
                                            stamp,
                                            timezone.utc,
                                        ),
                                        "Realized P&L": point.get(
                                            "realized_pnl"
                                        ),
                                        "Unrealized P&L": point.get(
                                            "unrealized_pnl"
                                        ),
                                    }
                                )

                        if rows:
                            frame = (
                                pd.DataFrame(rows)
                                .set_index("Date")
                                .sort_index()
                            )

                            st.line_chart(frame)

                            st.dataframe(
                                frame.tail(30),
                                use_container_width=True,
                            )

                    else:
                        st.info(
                            "No P&L history returned."
                        )

                # API diagnostics
                with st.expander(
                    "API diagnostics — HTTP status, trace IDs, and raw responses"
                ):
                    for name, result in bundle.items():
                        st.markdown(f"**{name.upper()}**")

                        if result["error"]:
                            st.error(result["error"])

                        else:
                            st.caption(
                                f"HTTP {result['status']} · "
                                f"Trace ID: {result['trace'] or 'not supplied'}"
                            )

                            st.json(result["payload"])

                st.warning(
                    "Research caution: an OPEN position can belong "
                    "to an archived or ended market. The app labels "
                    "market availability separately from position "
                    "status. Position data can be delayed or "
                    "incomplete. Never copy without verifying current "
                    "executable prices, depth, fees, settlement rules, "
                    "and whether the trader has since changed the position."
                )

            except Exception as exc:
                st.error(
                    f"Wallet analysis failed: {exc}"
                )

                st.caption(
                    "Copy the full error text if this happens again."
                )


# ============================================================
# TAB 4: PAYOFF CALCULATOR
# ============================================================

with calculator_tab:
    st.subheader("Binary contract payoff calculator")

    st.caption(
        "Use an executable ask, not the midpoint or last-traded price."
    )

    x, y, z = st.columns(3)

    with x:
        stake = st.number_input(
            "Maximum stake ($)",
            min_value=1.0,
            value=float(min(bankroll, 55.0)),
            step=1.0,
        )

    with y:
        ask_cents = st.number_input(
            "Executable ask (cents)",
            min_value=1.0,
            max_value=99.0,
            value=50.0,
            step=1.0,
        )

    with z:
        fee_per_contract = st.number_input(
            "Estimated fee per contract ($)",
            min_value=0.0,
            value=0.01,
            step=0.01,
            format="%.3f",
        )

    estimated_probability = st.slider(
        "Your estimated probability of winning",
        min_value=1,
        max_value=99,
        value=55,
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

    probability = estimated_probability / 100.0

    ev = contracts * (
        probability * (1.0 - price)
        - (1.0 - probability) * price
        - fee_per_contract
    )

    q1, q2, q3, q4 = st.columns(4)

    q1.metric(
        "Contracts",
        f"{contracts:,}",
    )

    q2.metric(
        "Total cost",
        money(total_cost),
    )

    q3.metric(
        "Profit if win",
        money(profit_if_win),
    )

    q4.metric(
        "Estimated EV",
        money(ev),
    )

    st.write(
        f"Maximum loss if it loses: **{money(total_cost)}** · "
        f"Remaining bankroll: **{money(max(0, bankroll - total_cost))}**"
    )

    st.caption(
        "Estimate excludes unentered fees, spread changes, "
        "partial fills, slippage, and settlement risk. "
        "EV depends entirely on the probability estimate."
    )


# ============================================================
# FINAL TRADE APPROVAL CHECKLIST
# ============================================================

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
    st.checkbox(
        item,
        key=f"approval_check_{idx}",
    )

st.caption(
    "Data sources: Polymarket public Data API and Kalshi public Trade API. "
    "Informational research only; no guaranteed signals, account connection, "
    "or automatic trading."
)

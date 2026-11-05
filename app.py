
import streamlit as st
import requests
import re
from difflib import SequenceMatcher

# --------------------------------------------------
# APP CONFIGURATION
# --------------------------------------------------

st.set_page_config(
    page_title="Polymarket → Kalshi Assistant",
    page_icon="📊",
    layout="wide"
)

st.title("Polymarket → Kalshi Trading Assistant")
st.caption(
    "v4 · Read-only research · Approval mode · "
    "Simulated bankroll $55"
)

# Use the public Kalshi market-data API.
BASE = "https://api.elections.kalshi.com/trade-api/v2"
POLY = "https://data-api.polymarket.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
}


# --------------------------------------------------
# KALSHI EVENT AND MARKET RETRIEVAL
# --------------------------------------------------

@st.cache_data(ttl=45, show_spinner=False)
def fetch_markets(max_pages=10):

    markets = []
    cursor = None
    seen_cursors = set()
    event_count = 0

    for page in range(max_pages):

        params = {
            "status": "open",
            "limit": 200,
            "with_nested_markets": "true"
        }

        if cursor:
            params["cursor"] = cursor

        response = requests.get(
            BASE + "/events",
            params=params,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()
        payload = response.json()

        events = payload.get("events", [])
        event_count += len(events)

        for event in events:

            event_title = event.get("title", "") or ""
            event_subtitle = event.get("sub_title", "") or ""
            category = event.get("category", "") or ""
            event_ticker = event.get("event_ticker", "") or ""

            nested_markets = event.get("markets", [])

            for market in nested_markets:

                item = dict(market)

                item["event_title"] = event_title
                item["event_subtitle"] = event_subtitle
                item["event_category"] = category
                item["event_ticker"] = event_ticker

                markets.append(item)

        cursor = payload.get("cursor")

        if not cursor or cursor in seen_cursors:
            break

        seen_cursors.add(cursor)

    return markets, event_count


# --------------------------------------------------
# TEXT SEARCH AND MATCHING
# --------------------------------------------------

def norm(value):

    value = str(value or "").lower()

    value = re.sub(
        r"[^a-z0-9 ]",
        " ",
        value
    )

    return " ".join(value.split())


def tokens(value):
    return set(norm(value).split())


def score(a, b):

    aa = norm(a)
    bb = norm(b)

    if not aa or not bb:
        return 0.0

    sequence_score = SequenceMatcher(
        None,
        aa,
        bb
    ).ratio()

    x = tokens(aa)
    y = tokens(bb)

    jaccard_score = len(x & y) / max(1, len(x | y))

    return round(
        max(sequence_score, jaccard_score),
        3
    )


def search_terms(raw):

    query = norm(raw)

    aliases = {
        "fed": [
            "federal reserve",
            "fomc",
            "federal funds rate",
            "interest rate",
            "fed funds",
            "rate decision",
            "fed rate",
            "fed meeting"
        ],

        "federal reserve": [
            "federal reserve",
            "fomc",
            "federal funds rate",
            "interest rate",
            "fed funds",
            "rate decision"
        ],

        "rates": [
            "interest rate",
            "federal funds rate",
            "fomc",
            "rate decision"
        ],

        "interest rates": [
            "interest rate",
            "federal funds rate",
            "fomc",
            "fed funds"
        ],

        "inflation": [
            "inflation",
            "consumer price index",
            "cpi",
            "producer price index",
            "ppi"
        ]
    }

    return aliases.get(query, [query])


def market_search_text(market):

    fields = [
        market.get("title", ""),
        market.get("subtitle", ""),
        market.get("yes_sub_title", ""),
        market.get("no_sub_title", ""),
        market.get("rules_primary", ""),
        market.get("event_title", ""),
        market.get("event_subtitle", ""),
        market.get("event_category", ""),
        market.get("event_ticker", "")
    ]

    return norm(" ".join(str(x or "") for x in fields))


# --------------------------------------------------
# PRICE FORMATTING
# --------------------------------------------------

def price(value, dollars=False):

    if value is None or value == "":
        return "—"

    try:

        number = float(value)

        if dollars:
            number *= 100

        return f"{number:.1f}¢"

    except (ValueError, TypeError):
        return str(value)


def market_price(market, field):

    # Prefer dollar-denominated fields when available.
    dollar_field = field + "_dollars"

    if market.get(dollar_field) is not None:
        return price(
            market.get(dollar_field),
            dollars=True
        )

    return price(market.get(field))


# --------------------------------------------------
# SIDEBAR: BANKROLL AND SAFEGUARDS
# --------------------------------------------------

with st.sidebar:

    st.header("Bankroll & safeguards")

    bankroll = st.number_input(
        "Simulated bankroll ($)",
        min_value=1.0,
        max_value=100000.0,
        value=55.0,
        step=1.0
    )

    risk = st.slider(
        "Maximum stake (% bankroll)",
        min_value=1,
        max_value=25,
        value=5
    )

    stake = bankroll * risk / 100

    st.metric(
        "Per-trade stake cap",
        f"${stake:.2f}"
    )

    pages = st.select_slider(
        "Market catalog depth",
        options=[2, 5, 10, 20],
        value=10,
        help="Number of event pages to retrieve. Each page contains up to 200 events."
    )

    st.caption(
        "Read-only research. No account connection "
        "and no orders are placed."
    )


# --------------------------------------------------
# MAIN TABS
# --------------------------------------------------

trader, matcher, calc, check = st.tabs([
    "Trader activity",
    "Market matcher",
    "Payoff calculator",
    "Approval checklist"
])


# --------------------------------------------------
# TAB 1: POLYMARKET TRADER ACTIVITY
# --------------------------------------------------

with trader:

    st.subheader("Look up a Polymarket wallet")

    wallet = st.text_input(
        "Public wallet address",
        placeholder="0x…"
    )

    count = st.selectbox(
        "Recent trades",
        [10, 25, 50],
        index=1
    )

    if st.button("Load wallet trades"):

        if not wallet.strip():

            st.warning("Enter a wallet address.")

        else:

            try:

                response = requests.get(
                    POLY + "/trades",
                    params={
                        "user": wallet.strip(),
                        "limit": count
                    },
                    timeout=20,
                    headers=HEADERS
                )

                response.raise_for_status()

                data = response.json()

                if isinstance(data, dict):
                    data = data.get("data", [])

                if data:

                    st.dataframe(
                        data,
                        use_container_width=True,
                        hide_index=True
                    )

                else:

                    st.info(
                        "No recent trades returned for that wallet."
                    )

            except Exception as error:

                st.error(
                    f"Polymarket request failed: {error}"
                )


# --------------------------------------------------
# TAB 2: KALSHI MARKET MATCHER
# --------------------------------------------------

with matcher:

    st.subheader("Search open Kalshi markets")

    st.write(
        "Search event names, market titles, descriptions, "
        "categories, and resolution rules."
    )

    keyword = st.text_input(
        "Keyword",
        placeholder="Fed, FOMC, inflation, interest rates"
    )

    reference = st.text_input(
        "Polymarket market title (optional)",
        placeholder="Paste the market title to improve matching"
    )

    search_button = st.button(
        "Search open markets",
        type="primary"
    )

    if search_button:

        if not keyword.strip() and not reference.strip():

            st.warning("Enter a keyword or market title.")

        else:

            try:

                with st.spinner(
                    "Retrieving Kalshi events and their markets..."
                ):

                    markets, event_count = fetch_markets(pages)

                raw_query = (
                    reference.strip()
                    if reference.strip()
                    else keyword.strip()
                )

                concepts = search_terms(
                    keyword.strip()
                    if keyword.strip()
                    else reference.strip()
                )

                matches = []

                for market in markets:

                    searchable = market_search_text(market)

                    if not any(
                        norm(term) in searchable
                        for term in concepts
                    ):
                        continue

                    comparison_text = (
                        market.get("title", "")
                        + " "
                        + market.get("subtitle", "")
                        + " "
                        + market.get("event_title", "")
                    )

                    similarity = score(
                        raw_query,
                        comparison_text
                    )

                    matches.append(
                        (similarity, market)
                    )

                matches.sort(
                    key=lambda item: item[0],
                    reverse=True
                )

                st.write(
                    f"Retrieved **{event_count:,} events** "
                    f"containing **{len(markets):,} nested markets** "
                    f"across up to {pages} pages."
                )

                st.write(
                    f"Found **{len(matches):,} relevant text matches**."
                )

                if not matches:

                    st.info(
                        "No matching markets were found in the "
                        "events retrieved. Try Federal Reserve, "
                        "FOMC, interest rate, or increase catalog depth."
                    )

                    st.caption(
                        "The search only covers the event pages retrieved. "
                        "It does not guarantee that every open Kalshi "
                        "market has been searched."
                    )

                else:

                    for index, (similarity, market) in enumerate(
                        matches[:40],
                        start=1
                    ):

                        with st.container(border=True):

                            st.markdown(
                                f"**{index}. "
                                f"{market.get('title') or 'Untitled market'}**"
                            )

                            event_title = market.get(
                                "event_title",
                                ""
                            )

                            if event_title:

                                st.caption(
                                    f"Event: {event_title}"
                                )

                            subtitle = (
                                market.get("subtitle")
                                or market.get("yes_sub_title")
                                or ""
                            )

                            if subtitle:

                                st.caption(subtitle)

                            st.caption(
                                f"Ticker: `{market.get('ticker', '—')}` "
                                f"· Similarity screen: {similarity:.0%}"
                            )

                            left, right = st.columns(2)

                            with left:

                                st.metric(
                                    "YES ask",
                                    market_price(
                                        market,
                                        "yes_ask"
                                    )
                                )

                            with right:

                                st.metric(
                                    "NO ask",
                                    market_price(
                                        market,
                                        "no_ask"
                                    )
                                )

                            close_time = market.get("close_time")

                            if close_time:

                                st.caption(
                                    f"Close: {close_time}"
                                )

                            rules = market.get(
                                "rules_primary",
                                ""
                            )

                            if rules:

                                with st.expander(
                                    "Resolution rules"
                                ):

                                    st.write(rules)

                    st.warning(
                        "These are text matches, not verified "
                        "equivalent contracts. Confirm the exact event, "
                        "threshold, deadline, timezone, resolution source, "
                        "and settlement rules before considering a trade."
                    )

            except requests.HTTPError as error:

                st.error(
                    f"Kalshi API HTTP error: {error}"
                )

            except requests.RequestException as error:

                st.error(
                    f"Network request failed: {error}"
                )

            except Exception as error:

                st.error(
                    f"Market search failed: "
                    f"{type(error).__name__}: {error}"
                )


# --------------------------------------------------
# TAB 3: PAYOFF CALCULATOR
# --------------------------------------------------

with calc:

    st.subheader("Manual trade estimate")

    a, b, c = st.columns(3)

    with a:

        side = st.selectbox(
            "Contract side",
            ["YES", "NO"]
        )

    with b:

        ask = st.number_input(
            "Executable ask (¢)",
            min_value=1,
            max_value=99,
            value=45
        )

    with c:

        fee = st.number_input(
            "Estimated fee per contract (¢)",
            min_value=0.0,
            max_value=20.0,
            value=1.0,
            step=0.25
        )

    probability = st.slider(
        "Your estimated probability of winning (%)",
        min_value=1,
        max_value=99,
        value=55
    )

    contracts = int(
        stake / (ask / 100)
    )

    cost = contracts * ask / 100

    fees = contracts * fee / 100

    net_if_correct = (
        contracts * (1 - ask / 100)
        - fees
    )

    net_if_wrong = cost + fees

    expected_value = contracts * (
        (probability / 100) * (1 - ask / 100)
        - (1 - probability / 100) * (ask / 100)
        - fee / 100
    )

    x, y, z = st.columns(3)

    x.metric(
        "Contracts within cap",
        contracts
    )

    y.metric(
        "Net if correct",
        f"${net_if_correct:.2f}"
    )

    z.metric(
        "Net if wrong",
        f"-${net_if_wrong:.2f}"
    )

    st.metric(
        "Estimated expected value",
        f"${expected_value:.2f}",
        delta=(
            "Positive estimate"
            if expected_value > 0
            else "Negative estimate"
        )
    )

    st.caption(
        f"Estimated cost ${cost:.2f} plus fees ${fees:.2f}. "
        f"Break-even probability: {ask + fee:.1f}%. "
        "Your probability is an assumption, not derived from "
        "Polymarket activity."
    )


# --------------------------------------------------
# TAB 4: MANUAL APPROVAL CHECKLIST
# --------------------------------------------------

with check:

    st.subheader("Before manually approving a trade")

    st.markdown("""
    - [ ] Same underlying event and settlement source
    - [ ] Same deadline, timezone, threshold, and resolution wording
    - [ ] Polymarket trader position is recent and not exited
    - [ ] Kalshi executable ask rechecked immediately before trading
    - [ ] Actual fees and slippage included
    - [ ] Stake is within the configured cap
    - [ ] Full stake loss is affordable
    """)

    st.error(
        "This build is read-only. It does not authenticate "
        "to Kalshi or submit orders."
    )


# --------------------------------------------------
# FOOTER
# --------------------------------------------------

st.divider()

st.caption(
    "Public APIs can change or rate-limit requests. "
    "Prices shown are snapshots, not guaranteed executable quotes. "
    "This tool does not guarantee profitable trades."
)

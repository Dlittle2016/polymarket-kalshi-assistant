
import streamlit as st
import requests
import re
from difflib import SequenceMatcher

# ==================================================
# CONFIGURATION
# ==================================================

st.set_page_config(
    page_title="Polymarket → Kalshi Assistant",
    page_icon="📊",
    layout="wide"
)

st.title("Polymarket → Kalshi Trading Assistant")

st.caption(
    "v5 · Economic market research · Read-only · "
    "Manual approval · Simulated bankroll $55"
)

BASE = "https://api.elections.kalshi.com/trade-api/v2"
POLY = "https://data-api.polymarket.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
}


# ==================================================
# ECONOMIC MARKET CATEGORIES
# ==================================================

ECONOMIC_TOPICS = {

    "Federal Reserve": [
        "federal reserve",
        "fomc",
        "fed funds",
        "federal funds rate",
        "interest rate",
        "rate decision",
        "rate cut",
        "rate hike",
        "rate increase",
        "rate reduction",
        "monetary policy",
        "fed chair",
        "fed meeting"
    ],

    "Inflation": [
        "inflation",
        "consumer price index",
        "cpi",
        "core cpi",
        "personal consumption expenditures",
        "pce",
        "core pce",
        "producer price index",
        "ppi",
        "price index"
    ],

    "Employment": [
        "unemployment",
        "unemployment rate",
        "nonfarm payrolls",
        "non farm payrolls",
        "jobs report",
        "jobless claims",
        "initial claims",
        "employment",
        "labor market",
        "labor force",
        "payrolls",
        "job creation"
    ],

    "Economic Growth": [
        "gross domestic product",
        "gdp",
        "economic growth",
        "recession",
        "economic contraction",
        "economic expansion",
        "real gdp"
    ],

    "Consumer Economy": [
        "retail sales",
        "consumer spending",
        "consumer confidence",
        "consumer sentiment",
        "personal income",
        "personal spending"
    ],

    "Housing": [
        "housing starts",
        "home sales",
        "existing home sales",
        "new home sales",
        "home prices",
        "house prices",
        "housing market",
        "building permits",
        "mortgage rates"
    ],

    "Treasury & Bonds": [
        "treasury yield",
        "treasury yields",
        "10 year yield",
        "10-year yield",
        "2 year yield",
        "2-year yield",
        "bond yield",
        "treasury bonds",
        "treasury rate"
    ],

    "Business & Manufacturing": [
        "manufacturing",
        "industrial production",
        "pmi",
        "ism",
        "business activity",
        "factory orders",
        "durable goods"
    ]
}


# ==================================================
# TEXT HELPERS
# ==================================================

def norm(value):

    value = str(value or "").lower()

    value = re.sub(
        r"[^a-z0-9 ]",
        " ",
        value
    )

    return " ".join(value.split())


def phrase_matches(text, phrase):

    text = " " + norm(text) + " "
    phrase = " " + norm(phrase) + " "

    return phrase in text


def score(a, b):

    aa = norm(a)
    bb = norm(b)

    if not aa or not bb:
        return 0.0

    sequence = SequenceMatcher(
        None,
        aa,
        bb
    ).ratio()

    x = set(aa.split())
    y = set(bb.split())

    jaccard = len(x & y) / max(1, len(x | y))

    return round(max(sequence, jaccard), 3)


# ==================================================
# MARKET DATA
# ==================================================

@st.cache_data(ttl=45, show_spinner=False)
def fetch_markets(max_pages=10):

    markets = []
    cursor = None
    seen_cursors = set()
    event_count = 0

    for _ in range(max_pages):

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

            for market in event.get("markets", []):

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


# ==================================================
# MARKET SEARCH
# ==================================================

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
    ]

    return " ".join(
        str(field or "")
        for field in fields
    )


def find_topics(text):

    matched = []

    for topic, phrases in ECONOMIC_TOPICS.items():

        for phrase in phrases:

            if phrase_matches(text, phrase):

                matched.append(topic)
                break

    return matched


def find_keyword_concepts(keyword):

    query = norm(keyword)

    # Direct category selection takes priority.
    if query in [norm(x) for x in ECONOMIC_TOPICS]:

        for topic in ECONOMIC_TOPICS:

            if norm(topic) == query:
                return ECONOMIC_TOPICS[topic]

    aliases = {

        "fed": "Federal Reserve",
        "fomc": "Federal Reserve",
        "rates": "Federal Reserve",
        "interest rates": "Federal Reserve",

        "cpi": "Inflation",
        "ppi": "Inflation",
        "pce": "Inflation",

        "jobs": "Employment",
        "jobs report": "Employment",
        "payrolls": "Employment",

        "gdp": "Economic Growth",
        "recession": "Economic Growth",

        "bonds": "Treasury & Bonds",
        "treasuries": "Treasury & Bonds",

        "housing": "Housing"
    }

    if query in aliases:

        return ECONOMIC_TOPICS[aliases[query]]

    return [query] if query else []


# ==================================================
# PRICE FORMATTING
# ==================================================

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

    dollar_field = field + "_dollars"

    if market.get(dollar_field) is not None:

        return price(
            market.get(dollar_field),
            dollars=True
        )

    return price(market.get(field))


# ==================================================
# SIDEBAR
# ==================================================

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
        help="Number of event pages to retrieve. Each page requests up to 200 events."
    )

    st.caption(
        "No Kalshi account connection. "
        "No automatic orders."
    )


# ==================================================
# TABS
# ==================================================

trader, matcher, calc, check = st.tabs([
    "Trader activity",
    "Economic market matcher",
    "Payoff calculator",
    "Approval checklist"
])


# ==================================================
# TAB 1: POLYMARKET TRADER ACTIVITY
# ==================================================

with trader:

    st.subheader("Look up a Polymarket wallet")

    wallet = st.text_input(
        "Public wallet address",
        placeholder="0x..."
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
                    headers=HEADERS,
                    timeout=20
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


# ==================================================
# TAB 2: ECONOMIC MARKET MATCHER
# ==================================================

with matcher:

    st.subheader("Search major economic markets")

    st.write(
        "Find markets covering monetary policy, inflation, "
        "employment, GDP, consumer activity, housing, and bonds."
    )

    topic_options = [
        "All major economic markets"
    ] + list(ECONOMIC_TOPICS.keys())

    selected_topic = st.selectbox(
        "Economic category",
        topic_options
    )

    keyword = st.text_input(
        "Optional keyword",
        placeholder="Fed, CPI, unemployment, GDP, inflation..."
    )

    reference = st.text_input(
        "Polymarket market title (optional)",
        placeholder="Paste a market title to improve matching"
    )

    search_button = st.button(
        "Search economic markets",
        type="primary"
    )

    if search_button:

        try:

            with st.spinner(
                "Retrieving Kalshi economic events and markets..."
            ):

                markets, event_count = fetch_markets(pages)

            matches = []

            if selected_topic == "All major economic markets":

                allowed_topics = list(ECONOMIC_TOPICS.keys())

            else:

                allowed_topics = [selected_topic]

            # A keyword can narrow an all-market search.
            keyword_concepts = find_keyword_concepts(keyword)

            if keyword.strip():

                keyword_topics = find_topics(keyword)

                # If the keyword clearly identifies a topic,
                # narrow the search to that topic.
                if selected_topic == "All major economic markets" and keyword_topics:

                    allowed_topics = keyword_topics

            for market in markets:

                searchable = market_search_text(market)

                matched_topics = find_topics(searchable)

                matched_topics = [
                    topic
                    for topic in matched_topics
                    if topic in allowed_topics
                ]

                if not matched_topics:
                    continue

                # Optional keyword must also match the market.
                if keyword.strip():

                    keyword_match = any(
                        phrase_matches(searchable, term)
                        for term in keyword_concepts
                    )

                    if not keyword_match:
                        continue

                # Optional Polymarket title similarity.
                reference_score = 0.0

                if reference.strip():

                    comparison = (
                        market.get("title", "")
                        + " "
                        + market.get("subtitle", "")
                        + " "
                        + market.get("event_title", "")
                    )

                    reference_score = score(
                        reference,
                        comparison
                    )

                # Give upcoming, shorter-horizon market titles
                # a useful relevance score only when a reference exists.
                matches.append({
                    "market": market,
                    "topics": matched_topics,
                    "score": reference_score
                })

            # With no reference, prioritize markets matching
            # more than one relevant economic phrase/topic.
            matches.sort(
                key=lambda item: (
                    item["score"],
                    len(item["topics"])
                ),
                reverse=True
            )

            st.write(
                f"Retrieved **{event_count:,} events** "
                f"containing **{len(markets):,} markets** "
                f"across up to {pages} pages."
            )

            st.write(
                f"Found **{len(matches):,} economic market matches**."
            )

            if not matches:

                st.info(
                    "No matching economic markets were found "
                    "in the events retrieved. Try a different "
                    "category or keyword, or increase catalog depth."
                )

            else:

                # Category summary.
                topic_counts = {}

                for item in matches:

                    for topic in item["topics"]:

                        topic_counts[topic] = (
                            topic_counts.get(topic, 0) + 1
                        )

                st.markdown("#### Results by economic category")

                summary_columns = st.columns(3)

                for index, (topic, total) in enumerate(
                    sorted(
                        topic_counts.items(),
                        key=lambda x: x[1],
                        reverse=True
                    )
                ):

                    with summary_columns[index % 3]:

                        st.metric(
                            topic,
                            total
                        )

                st.divider()

                st.markdown("#### Matching markets")

                for index, item in enumerate(
                    matches[:50],
                    start=1
                ):

                    market = item["market"]

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

                        st.caption(
                            "Economic category: "
                            + ", ".join(item["topics"])
                        )

                        if market.get("subtitle"):

                            st.caption(
                                market["subtitle"]
                            )

                        st.caption(
                            f"Ticker: `{market.get('ticker', '—')}`"
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

                        if market.get("close_time"):

                            st.caption(
                                "Close: "
                                + market["close_time"]
                            )

                        if market.get("rules_primary"):

                            with st.expander(
                                "Resolution rules"
                            ):

                                st.write(
                                    market["rules_primary"]
                                )

                if len(matches) > 50:

                    st.info(
                        f"Showing the first 50 of "
                        f"{len(matches)} matches."
                    )

                st.warning(
                    "These are text matches, not verified "
                    "trading opportunities. Confirm exact event "
                    "wording, resolution source, deadline, timezone, "
                    "liquidity, order-book prices, fees, and settlement rules."
                )

                st.caption(
                    "Catalog coverage is limited to the event pages "
                    "retrieved. A market not shown may still exist "
                    "outside those pages."
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


# ==================================================
# TAB 3: PAYOFF CALCULATOR
# ==================================================

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
            "Selected side executable ask (¢)",
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
        "Your estimated probability of this side winning (%)",
        min_value=1,
        max_value=99,
        value=55
    )

    contracts = int(
        stake / (ask / 100 + fee / 100)
    )

    cost = contracts * ask / 100

    fees = contracts * fee / 100

    net_if_correct = (
        contracts * (1 - ask / 100) - fees
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
        f"Selected side: {side}. "
        f"Estimated cost: ${cost:.2f}. "
        f"Estimated fees: ${fees:.2f}. "
        f"Break-even probability: {ask + fee:.1f}%. "
        "Probability is your assumption, not a verified forecast."
    )


# ==================================================
# TAB 4: APPROVAL CHECKLIST
# ==================================================

with check:

    st.subheader("Before manually approving a trade")

    st.markdown("""
    - [ ] Same underlying event on both platforms
    - [ ] Same outcome and contract direction
    - [ ] Same threshold and measurement period
    - [ ] Same deadline and timezone
    - [ ] Same resolution source and settlement rules
    - [ ] Polymarket trader position is recent and not exited
    - [ ] Kalshi executable ask rechecked immediately before trading
    - [ ] Order-book liquidity is sufficient
    - [ ] Actual fees and slippage included
    - [ ] Stake is within the configured cap
    - [ ] Full stake loss is affordable
    """)

    st.error(
        "This application is read-only. It does not authenticate "
        "to Kalshi or submit orders."
    )


# ==================================================
# FOOTER
# ==================================================

st.divider()

st.caption(
    "Public APIs can change or rate-limit requests. "
    "Displayed prices are snapshots, not guaranteed executable quotes. "
    "This tool does not guarantee profitable trades."
)

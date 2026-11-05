import streamlit as st
import requests
from difflib import SequenceMatcher

st.set_page_config(page_title="Polymarket → Kalshi Assistant", layout="wide")
st.title("Polymarket → Kalshi Trading Assistant")
st.caption("Read-only research · Approval mode · Starting bankroll $55")

POLY="https://data-api.polymarket.com"
KALSHI="https://api.elections.kalshi.com/trade-api/v2"

def get(url, params):
    r=requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def sim(a,b):
    return SequenceMatcher(None, " ".join((a or "").lower().split()),
                           " ".join((b or "").lower().split())).ratio()

with st.sidebar:
    bankroll=st.number_input("Bankroll ($)", 1.0, 100000.0, 55.0)
    risk_pct=st.slider("Max stake (% bankroll)", 1,25,5)
    min_edge=st.slider("Minimum payout margin (¢)",0,30,5)
    st.metric("Stake cap", f"${bankroll*risk_pct/100:.2f}")
    st.warning("No orders are placed. You can lose the full stake.")

t1,t2,t3=st.tabs(["Trader activity","Market matcher","Approval checklist"])
with t1:
    wallet=st.text_input("Polymarket wallet address",placeholder="0x…")
    count=st.selectbox("Rows",[10,25,50],index=1)
    if st.button("Load recent trades"):
        try:
            d=get(f"{POLY}/trades",{"user":wallet.strip(),"limit":count})
            if isinstance(d,dict): d=d.get("data",[])
            st.dataframe(d,use_container_width=True)
        except Exception as e: st.error(f"Unable to load trades: {e}")

with t2:
    kw=st.text_input("Kalshi event keyword")
    poly_title=st.text_input("Polymarket market title (optional; improves matching)")
    limit=st.slider("Kalshi markets to scan",20,200,100,step=20)
    if st.button("Find candidate markets"):
        try:
            # Kalshi market listing is public; rank returned open markets locally.
            d=get(f"{KALSHI}/markets",{"status":"open","limit":limit})
            markets=d.get("markets",[]) if isinstance(d,dict) else []
            target=poly_title.strip() or kw.strip()
            ranked=sorted(markets,key=lambda m:sim(target,m.get("title","")),reverse=True)
            rows=[{"Similarity":round(sim(target,m.get("title","")),3),
                   "Title":m.get("title"),"Ticker":m.get("ticker"),
                   "YES ask (¢)":m.get("yes_ask"),"NO ask (¢)":m.get("no_ask"),
                   "Close":m.get("close_time"),
                   "Rules":m.get("rules_primary") or m.get("subtitle","")}
                  for m in ranked[:15]]
            st.dataframe(rows,use_container_width=True,hide_index=True)
            st.warning("Text similarity is only a shortlist. Confirm exact settlement rules, date, timezone, threshold, and source before considering a trade.")
        except Exception as e: st.error(f"Market request failed: {e}")

    st.markdown("#### Candidate payoff calculator")
    side=st.selectbox("Contract side",["YES","NO"])
    price=st.number_input("Current executable ask (¢)",1,99,45)
    signal=st.number_input("Polymarket signal price (¢)",1,99,50)
    fee=st.number_input("Estimated fee per contract (¢)",0.0,20.0,1.0,0.25)
    cap=bankroll*risk_pct/100
    n=int(cap/(price/100))
    net=n*(1-price/100-fee/100)
    st.metric("Approx. profit if contract wins",f"${net:.2f}")
    st.metric("Break-even probability",f"{price+fee:.1f}%")
    margin=100-price-fee
    if margin<min_edge: st.warning(f"Below configured threshold ({min_edge}¢).")
    else: st.info(f"Candidate margin {margin:.1f}¢ before probability calibration; not proof of positive expected value.")
    st.caption(f"Stake cap supports about {n} contracts, cost ${n*price/100:.2f}. Signal price entered: {signal}¢.")

with t3:
    st.markdown("""### Before approving any trade
- [ ] Same event and settlement source
- [ ] Same cutoff time, timezone, threshold, and rules
- [ ] Polymarket trade is recent; trader has not exited
- [ ] Kalshi executable quote rechecked
- [ ] Fees and slippage considered
- [ ] Stake is within the bankroll cap
- [ ] Full stake loss is affordable
""")
    st.error("This version is read-only: it does not authenticate to Kalshi or submit orders.")
st.divider()
st.caption("Uses public Polymarket Data API and Kalshi market-data API. Feeds can be delayed, rate-limited, or change.")

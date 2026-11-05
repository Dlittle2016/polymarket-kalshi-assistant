import streamlit as st
import requests, re
from difflib import SequenceMatcher

st.set_page_config(page_title='Polymarket → Kalshi Assistant', page_icon='📊', layout='wide')
st.title('Polymarket → Kalshi Trading Assistant')
st.caption('v3 · Read-only research · Approval mode · Simulated bankroll $55')
BASE='https://api.elections.kalshi.com/trade-api/v2'
POLY='https://data-api.polymarket.com'

@st.cache_data(ttl=45, show_spinner=False)
def fetch_markets(max_pages=10):
    rows=[]; cursor=None; seen=set()
    for _ in range(max_pages):
        params={'status':'open','limit':200}
        if cursor: params['cursor']=cursor
        r=requests.get(BASE+'/markets',params=params,timeout=25,headers={'User-Agent':'Mozilla/5.0'})
        r.raise_for_status(); payload=r.json()
        rows.extend(payload.get('markets',[]))
        cursor=payload.get('cursor')
        if not cursor or cursor in seen: break
        seen.add(cursor)
    return rows

def norm(s): return re.sub(r'[^a-z0-9 ]',' ',' '.join((s or '').lower().split()))
def tokens(s): return set(norm(s).split())
def score(a,b):
    aa,bb=norm(a),norm(b)
    if not aa or not bb:return 0.0
    seq=SequenceMatcher(None,aa,bb).ratio()
    x,y=tokens(aa),tokens(bb)
    jac=len(x&y)/max(1,len(x|y))
    return round(max(seq,jac),3)
def price(v):
    if v is None:return '—'
    try:return f'{float(v):.0f}¢'
    except:return str(v)

# Search concepts are expanded deliberately; no substring matching against tickers.
def search_terms(raw):
    q=norm(raw)
    aliases={
        'fed':['federal reserve','fomc','interest rate','fed funds','rate decision'],
        'federal reserve':['federal reserve','fomc','interest rate','fed funds','rate decision'],
        'rates':['interest rate','fed funds','fomc','rate decision'],
    }
    if q in aliases: return aliases[q]
    return [q]

with st.sidebar:
    st.header('Bankroll & safeguards')
    bankroll=st.number_input('Simulated bankroll ($)',min_value=1.0,max_value=100000.0,value=55.0,step=1.0)
    risk=st.slider('Maximum stake (% bankroll)',1,25,5)
    stake=bankroll*risk/100
    st.metric('Per-trade stake cap',f'${stake:.2f}')
    pages=st.select_slider('Market catalog depth',options=[2,5,10,20],value=10,help='More pages finds more markets but takes longer.')
    st.caption('No account connection and no orders are placed.')

trader,matcher,calc,check=st.tabs(['Trader activity','Market matcher','Payoff calculator','Approval checklist'])
with trader:
    st.subheader('Look up a Polymarket wallet')
    wallet=st.text_input('Public wallet address',placeholder='0x…')
    count=st.selectbox('Recent trades',[10,25,50],index=1)
    if st.button('Load wallet trades'):
        if not wallet.strip(): st.warning('Enter a wallet address.')
        else:
            try:
                r=requests.get(POLY+'/trades',params={'user':wallet.strip(),'limit':count},timeout=20);r.raise_for_status();d=r.json()
                if isinstance(d,dict):d=d.get('data',[])
                if d: st.dataframe(d,use_container_width=True,hide_index=True)
                else:st.info('No recent trades returned for that wallet.')
            except Exception as e:st.error(f'Polymarket request failed: {e}')
with matcher:
    st.subheader('Search open Kalshi markets')
    keyword=st.text_input('Keyword',placeholder='Fed, Federal Reserve, inflation, or interest rates')
    reference=st.text_input('Polymarket market title (optional; improves matching)')
    if st.button('Search open markets',type='primary'):
        if not keyword.strip() and not reference.strip():st.warning('Enter a keyword or market title.')
        else:
            try:
                with st.spinner('Retrieving open Kalshi markets…'):
                    markets=fetch_markets(pages)
                raw_query=reference.strip() or keyword.strip()
                concepts=search_terms(keyword.strip() or reference.strip())
                matches=[]
                for m in markets:
                    title=m.get('title','') or ''; sub=m.get('subtitle','') or ''
                    searchable=norm(title+' '+sub)
                    # Match complete words/phrases only. Tickers are intentionally excluded.
                    if not any(norm(term) in searchable for term in concepts): continue
                    s=score(raw_query,title+' '+sub)
                    matches.append((s,m))
                matches.sort(key=lambda x:x[0],reverse=True)
                st.write(f'Fetched **{len(markets):,}** open markets across up to {pages} pages. Found **{len(matches):,}** relevant text matches.')
                if not matches:
                    st.info('No relevant matches in the pages retrieved. Try “Federal Reserve”, “FOMC”, “interest rate”, or increase Market catalog depth.')
                else:
                    for idx,(s,m) in enumerate(matches[:40],1):
                        with st.container(border=True):
                            left,right=st.columns([5,1])
                            with left:
                                st.markdown(f'**{idx}. {m.get("title") or "Untitled market"}**')
                                if m.get('subtitle'): st.caption(m.get('subtitle'))
                                st.caption(f'Ticker: `{m.get("ticker", "—")}`  ·  Similarity screen: {s:.0%}')
                            with right:
                                st.metric('YES ask',price(m.get('yes_ask')))
                                st.metric('NO ask',price(m.get('no_ask')))
                            if m.get('close_time'): st.caption(f'Close: {m.get("close_time")}')
                            rules=m.get('rules_primary') or ''
                            if rules:
                                with st.expander('Resolution rules'): st.write(rules)
                    st.warning('These are text matches, not verified equivalent contracts. Confirm exact event wording, resolution source, cutoff, timezone, and settlement rules before considering a trade.')
            except requests.HTTPError as e:st.error(f'Kalshi API HTTP error: {e}')
            except Exception as e:st.error(f'Market search failed: {type(e).__name__}: {e}')
with calc:
    st.subheader('Manual trade estimate')
    a,b,c=st.columns(3)
    with a:side=st.selectbox('Contract side',['YES','NO'])
    with b:ask=st.number_input('Executable ask (¢)',1,99,45)
    with c:fee=st.number_input('Estimated fee per contract (¢)',0.0,20.0,1.0,0.25)
    probability=st.slider('Your estimated probability of winning (%)',1,99,55)
    n=int(stake/(ask/100));cost=n*ask/100;fees=n*fee/100
    win=n*(1-ask/100)-fees;loss=cost+fees
    ev=n*((probability/100)*(1-ask/100)-(1-probability/100)*(ask/100)-fee/100)
    x,y,z=st.columns(3)
    x.metric('Contracts within cap',n);y.metric('Net if correct',f'${win:.2f}');z.metric('Net if wrong',f'-${loss:.2f}')
    st.metric('Estimated expected value',f'${ev:.2f}',delta='Positive estimate' if ev>0 else 'Negative estimate')
    st.caption(f'Estimated cost ${cost:.2f} plus fees ${fees:.2f}. Break-even probability: {ask+fee:.1f}%. Your probability is an assumption, not derived from Polymarket activity.')
with check:
    st.subheader('Before manually approving a trade')
    st.markdown('- [ ] Same underlying event and settlement source\n- [ ] Same deadline, timezone, threshold, and resolution wording\n- [ ] Polymarket trader position is recent and not exited\n- [ ] Kalshi executable ask rechecked immediately before trading\n- [ ] Actual fees and slippage included\n- [ ] Stake is within the configured cap\n- [ ] Full stake loss is affordable')
    st.error('This build is read-only. It does not authenticate to Kalshi or submit orders.')
st.divider();st.caption('Public APIs can change or rate-limit requests. Prices shown are snapshots, not guaranteed executable quotes.')

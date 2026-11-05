import streamlit as st
import requests, re
from difflib import SequenceMatcher

st.set_page_config(page_title='Polymarket → Kalshi Assistant', page_icon='📊', layout='wide')
st.title('Polymarket → Kalshi Trading Assistant')
st.caption('v2 · Read-only research · Approval mode · Simulated bankroll $55')
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
def score(a,b):
    aa,bb=norm(a),norm(b)
    if not aa or not bb:return 0.0
    seq=SequenceMatcher(None,aa,bb).ratio()
    x,y=set(aa.split()),set(bb.split())
    jac=len(x&y)/max(1,len(x|y))
    return round(max(seq,jac),3)
def price(v):
    if v is None:return '—'
    try:return f'{float(v):.0f}¢'
    except:return str(v)

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
    keyword=st.text_input('Keyword',placeholder='Federal Reserve')
    reference=st.text_input('Polymarket market title (optional; better matching)')
    if st.button('Search open markets',type='primary'):
        if not keyword.strip() and not reference.strip():st.warning('Enter a keyword or market title.')
        else:
            try:
                with st.spinner('Retrieving open Kalshi markets…'):
                    markets=fetch_markets(pages)
                query=reference.strip() or keyword.strip()
                terms=[t for t in norm(keyword or reference).split() if len(t)>2]
                matches=[]
                for m in markets:
                    title=m.get('title',''); sub=m.get('subtitle',''); ticker=m.get('ticker','')
                    hay=norm(title+' '+sub+' '+ticker)
                    if terms and not any(t in hay for t in terms):continue
                    s=score(query,title+' '+sub)
                    matches.append((s,m))
                matches.sort(key=lambda x:x[0],reverse=True)
                st.write(f'Fetched **{len(markets):,}** open markets across up to {pages} pages. Found **{len(matches):,}** keyword matches.')
                if not matches:st.info('No matches in the retrieved pages. Try broader terms such as “Fed”, “rates”, “inflation”, or “interest”.')
                else:
                    out=[]
                    for s,m in matches[:50]:
                        out.append({'Similarity (screening only)':s,'Market':m.get('title'),'Subtitle':m.get('subtitle'),'Ticker':m.get('ticker'),'YES ask':price(m.get('yes_ask')),'NO ask':price(m.get('no_ask')),'Close time':m.get('close_time'),'Rules':m.get('rules_primary','')})
                    st.dataframe(out,use_container_width=True,hide_index=True)
                    st.warning('Similarity is not proof of equivalent contracts. Open the market and verify the exact resolution source, wording, cutoff, timezone, and settlement rules.')
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


# -*- coding: utf-8 -*-
import os, json, hashlib, sqlite3, time, datetime as dt, itertools
import pandas as pd
import streamlit as st

st.set_page_config(page_title='Lucy Bakery Menu Recommendation Service', layout='wide')

st.markdown('''
<style>
@font-face {
  font-family: 'Elice DX Neolli';
  src: url('https://cdn.jsdelivr.net/gh/projectnoonnu/noonfonts_2312_01@1.1/EliceDXNeolli-Regular.woff2') format('woff2');
  font-weight: normal; font-style: normal;
}
:root { --bg:#F6EAD3; --bg2:#FFF5E6; --text:#2A2A2A; --primary:#C36E2D; }
html, body, [data-testid="stAppViewContainer"] {
  background: var(--bg); color: var(--text);
  font-family: 'Elice DX Neolli','Noto Sans KR',sans-serif;
}
[data-testid="stHeader"] { background: transparent; }
.stButton>button { background: var(--primary) !important; color:#fff !important; border:0; border-radius:10px; padding:.6rem 1rem; }
.stTabs [data-baseweb="tab"] { background: var(--bg2); border-radius:10px 10px 0 0; padding:.6rem 0; font-weight:600; }
</style>
''', unsafe_allow_html=True)

@st.cache_data
def load_menu(path: str):
    df = pd.read_csv(path)
    req = {"category","name","price","sweetness","tags"}
    missing = req - set(df.columns)
    if missing: st.error(f"menu.csv 컬럼 누락: {missing}"); st.stop()
    df["tags_list"] = df["tags"].fillna("").apply(lambda s: [t.strip() for t in s.split(",") if t.strip()])
    return df

MENU = load_menu('menu.csv')
BAKERY_CATS = {"빵","샌드위치","샐러드","디저트"}
DRINK_CATS = {"커피","라떼","에이드","스무디","티"}
SIMPLE_TAGS = ["#달콤한","#짭짤한","#고소한","#바삭한","#촉촉한","#든든한","#가벼운","#초코","#과일"]

# ===== DB layer =====
DB_PATH = 'lucy.db'

def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db(); cur = conn.cursor()
    cur.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS users(
      user_id INTEGER PRIMARY KEY AUTOINCREMENT,
      phone_hash TEXT UNIQUE,
      consent_at TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      last_seen_at TEXT
    );
    CREATE TABLE IF NOT EXISTS visits(
      visit_id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      budget INTEGER,
      sweetness INTEGER,
      tags TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS orders(
      order_id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      items_json TEXT,
      total_price INTEGER,
      order_code TEXT UNIQUE,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS coupons(
      coupon_id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      code TEXT UNIQUE,
      kind TEXT,
      status TEXT,
      issued_at TEXT DEFAULT CURRENT_TIMESTAMP,
      expires_at TEXT,
      meta_json TEXT
    );
    ''')
    conn.commit(); conn.close()

def phone_to_hash(phone: str, salt: str='lucy_salt_v1') -> str:
    return hashlib.sha256((salt + phone).encode('utf-8')).hexdigest()

def upsert_user(phone: str):
    ph = phone_to_hash(phone)
    conn = db(); cur = conn.cursor()
    cur.execute('SELECT user_id FROM users WHERE phone_hash=?', (ph,))
    row = cur.fetchone()
    now = dt.datetime.utcnow().isoformat()
    if row:
        uid = row['user_id']
        cur.execute('UPDATE users SET last_seen_at=? WHERE user_id=?', (now, uid))
    else:
        cur.execute('INSERT INTO users(phone_hash, consent_at, last_seen_at) VALUES(?,?,?)', (ph, now, now))
        uid = cur.lastrowid
    conn.commit(); conn.close()
    return uid

def log_visit(user_id: int, budget: int, sweetness: int, tags_list: list):
    conn = db(); cur = conn.cursor()
    cur.execute('INSERT INTO visits(user_id, budget, sweetness, tags) VALUES(?,?,?,?)',
                (user_id, budget, sweetness, ",".join(tags_list)))
    conn.commit(); conn.close()

def gen_order_code():
    date = dt.datetime.now().strftime('%Y%m%d')
    uniq = str(int(time.time()))[-4:]
    return f'LUCY-{date}-{uniq}'

def place_order(user_id: int, items, total_price: int):
    order_code = gen_order_code()
    conn = db(); cur = conn.cursor()
    cur.execute('INSERT INTO orders(user_id, items_json, total_price, order_code) VALUES(?,?,?,?)',
                (user_id, json.dumps(items, ensure_ascii=False), total_price, order_code))
    conn.commit(); conn.close()
    return order_code

def has_active_launch_coupon(user_id: int) -> bool:
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT 1 FROM coupons WHERE user_id=? AND kind='launch_cookie' AND status IN ('active','used')", (user_id,))
    ok = cur.fetchone() is not None
    conn.close()
    return ok

def gen_coupon_code(prefix='LCK'):
    base = hashlib.sha1(str(time.time()).encode()).hexdigest()[:8].upper()
    return f'{prefix}-{base[:4]}-{base[4:]}'

def issue_launch_cookie_coupon(user_id: int, days_valid: int=14):
    if has_active_launch_coupon(user_id):
        return None, None
    code = gen_coupon_code()
    expires = (dt.datetime.utcnow() + dt.timedelta(days=days_valid)).date().isoformat()
    meta = {"desc": "앱 론칭 기념 쿠키 1개 무료", "limit": "매장 내 사용, 1회"}
    conn = db(); cur = conn.cursor()
    cur.execute('''
      INSERT INTO coupons(user_id, code, kind, status, expires_at, meta_json)
      VALUES(?,?,?,?,?,?)
    ''', (user_id, code, 'launch_cookie', 'active', expires, json.dumps(meta, ensure_ascii=False)))
    conn.commit(); conn.close()
    return code, expires

def fetch_last_order(user_id: int):
    conn = db(); cur = conn.cursor()
    cur.execute('SELECT items_json, created_at FROM orders WHERE user_id=? ORDER BY order_id DESC LIMIT 1', (user_id,))
    row = cur.fetchone(); conn.close()
    if not row: return None
    return json.loads(row['items_json']), row['created_at']

init_db()

# ===== Recommender =====
def score_item(row, chosen_tags, target_sweetness):
    item_tags = set(row["tags_list"])
    tag_match = len(item_tags & set(chosen_tags))
    diff = abs(int(row["sweetness"]) - int(target_sweetness))
    sweet_score = max(0, 3 - diff)
    bonus = 2 if "#인기" in item_tags else 0
    return tag_match*3 + sweet_score + bonus

def ranked_items(df, chosen_tags, sweet):
    if df.empty: return df.assign(_score=[])
    sc = df.apply(lambda r: score_item(r, chosen_tags, sweet), axis=1)
    return df.assign(_score=sc).sort_values(["_score","price"], ascending=[False, True]).reset_index(drop=True)

def recommend_combos(df, chosen_tags, sweet, budget, topk=3):
    cand = ranked_items(df, chosen_tags, sweet).head(12)
    combos, idxs = [], list(cand.index)
    for r in range(1, 4):
        for ids in itertools.combinations(idxs, r):
            items = cand.loc[list(ids)]; total = int(items["price"].sum())
            if total <= budget:
                score = float(items["_score"].sum())
                combos.append((items, total, score, r))
    if not combos: return []
    combos.sort(key=lambda x: (-x[2], x[1], -x[3]))
    out, seen = [], set()
    for items, total, score, r in combos:
        sig = tuple(sorted(items["name"].tolist()))
        if sig in seen: continue
        seen.add(sig); out.append((items, total, score, r))
        if len(out) == topk: break
    return out

def show_combo(idx, items, total, budget):
    with st.container():
        st.markdown(f"### 세트 {idx} · 합계 **₩{total:,}** / 예산 ₩{int(budget):,}")
        cols = st.columns(min(4, len(items)))
        for i, (_, r) in enumerate(items.iterrows()):
            with cols[i % len(cols)]:
                st.markdown(f"- **{r['name']}**")
                st.caption(f"{r['category']} · ₩{int(r['price']):,}")
                st.text(', '.join(r['tags_list']) if r['tags_list'] else '-')

# ===== Consent/Login (sidebar) =====
if 'authed_user_id' not in st.session_state:
    st.session_state.authed_user_id = None

with st.sidebar:
    st.markdown("### 고객 정보 (선택)")
    st.caption("동의 고객만 맞춤 추천/주문/쿠폰이 활성화됩니다.")
    consent = st.checkbox("개인정보(전화번호) 수집·이용에 동의합니다.")
    phone = st.text_input("전화번호('-' 없이)", max_chars=11, placeholder="01012345678", disabled=not consent)
    otp = st.text_input("인증코드(임시: 000000)", max_chars=6, disabled=not (consent and phone))
    if st.button("인증하기", disabled=not (consent and phone and otp=='000000')):
        uid = upsert_user(phone)
        st.session_state.authed_user_id = uid
        st.success("인증 완료! 맞춤 추천/쿠폰이 활성화됩니다.")

# ===== UI =====
st.title("Lucy Bakery Menu Recommendation Service")
tabs = st.tabs(["베이커리 조합 추천", "음료 추천", "메뉴판 보기"])

with tabs[0]:
    st.subheader("예산 안에서 가능한 조합 3세트 (1~3개 자동)")
    c1, c2 = st.columns([1,3])
    with c1:
        budget = st.number_input("총 예산(₩)", 0, 200000, 20000, step=1000)
    with c2:
        st.caption("예산에 따라 세트 구성 수량이 1~3개로 자동 조정됩니다.")
    st.markdown("---")
    sweet = st.slider("당도 (0~5)", 0, 5, 2)
    if 'soft_prev' not in st.session_state: st.session_state.soft_prev = []
    def enforce_max3():
        cur = st.session_state.soft
        if len(cur) > 3:
            st.session_state.soft = st.session_state.soft_prev
            st.toast("태그는 최대 3개까지 선택할 수 있어요.", icon="⚠️")
        else:
            st.session_state.soft_prev = cur
    soft = st.multiselect("취향 태그(최대 3개)", SIMPLE_TAGS, key='soft', on_change=enforce_max3)
    st.caption(f"선택: {len(soft)}/3")

    uid = st.session_state.authed_user_id
    if uid:
        last = fetch_last_order(uid)
        if last:
            items, when = last
            names = [i["name"] for i in items]
            st.info(f"지난 방문({when.split('T')[0]})에는 **{', '.join(names)}** 드셨어요. 이번엔 비슷한 취향 메뉴를 더 추천드릴게요!")

    if st.button("조합 3세트 추천받기 🍞"):
        bakery_df = MENU[MENU["category"].isin(BAKERY_CATS)].copy()
        if bakery_df["price"].min() > budget:
            st.warning("예산이 너무 낮아요. 최소 한 개의 품목 가격보다 높게 설정해주세요.")
        else:
            results = recommend_combos(bakery_df, soft, sweet, int(budget), topk=3)
            if not results:
                st.warning("조건에 맞는 조합을 만들 수 없어요. 예산이나 태그를 조정해보세요.")
            else:
                if uid: log_visit(uid, int(budget), int(sweet), soft)
                for i, (items, total, score, r) in enumerate(results, start=1):
                    show_combo(i, items, total, budget)
                    cols = st.columns([1,1,6])
                    with cols[0]:
                        disabled = (uid is None)
                        if st.button(f"세트 {i} 주문하기", key=f"order_{i}", disabled=disabled):
                            item_list = [{"name": row["name"], "category": row["category"], "price": int(row["price"])} for _, row in items.iterrows()]
                            oc = place_order(uid, item_list, int(total))
                            code, exp = issue_launch_cookie_coupon(uid)
                            st.success(f"주문 완료! 주문번호: **{oc}**")
                            if code:
                                st.info(f"🎁 쿠폰 발급: **{code}** (쿠키 1개 무료, 유효기간 ~ {exp})")
                            else:
                                st.caption("이미 론칭 기념 쿠폰이 발급된 고객이에요.")

with tabs[1]:
    st.subheader("음료 추천 (카테고리 + 당도)")
    cat = st.selectbox("음료 카테고리", ["커피","라떼","에이드","스무디","티"])
    sweet_d = st.slider("음료 당도 (0~5)", 0, 5, 3, key="drink_sweet")
    if st.button("음료 추천받기 ☕️"):
        drink_df = MENU[(MENU["category"] == cat)].copy()
        ranked = ranked_items(drink_df, [], sweet_d)
        st.markdown(f"**{cat} TOP3**")
        for _, r in ranked.head(3).iterrows():
            st.markdown(f"- **{r['name']}** · ₩{int(r['price']):,}")

with tabs[2]:
    st.subheader("메뉴판 보기")
    imgs = [p for p in ["menu_board_1.png","menu_board_2.png"] if os.path.exists(p)]
    if imgs: st.image(imgs, use_container_width=True, caption=[f"메뉴판 {i+1}" for i in range(len(imgs))])
    else: st.info("menu_board_1.png, menu_board_2.png 파일을 앱과 같은 폴더에 넣으면 자동 표시됩니다.")

st.divider()
st.caption("© 2025 Lucy Bakery – Budget Combo Recommender")

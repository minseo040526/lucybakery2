
# -*- coding: utf-8 -*-
import time, itertools
import datetime as dt
import pandas as pd
import streamlit as st

DEMO_MODE = True  # 발표용: 개인정보/로그인/DB/쿠폰 제거

st.set_page_config(page_title='Lucy Bakery Menu Recommendation Service (Demo)', layout='wide')

st.markdown(\"\"\"
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
\"\"\", unsafe_allow_html=True)

@st.cache_data
def load_menu(path: str):
    df = pd.read_csv(path)
    req = {\"category\",\"name\",\"price\",\"sweetness\",\"tags\"}
    missing = req - set(df.columns)
    if missing:
        st.error(f\"menu.csv 컬럼 누락: {missing}\")
        st.stop()
    df[\"tags_list\"] = df[\"tags\"].fillna(\"\").apply(lambda s: [t.strip() for t in s.split(\",\") if t.strip()])
    return df

MENU = load_menu(\"menu.csv\")

BAKERY_CATS = {\"빵\",\"샌드위치\",\"샐러드\",\"디저트\"}
SIMPLE_TAGS = [\"#달콤한\",\"#짭짤한\",\"#고소한\",\"#바삭한\",\"#촉촉한\",\"#든든한\",\"#가벼운\",\"#초코\",\"#과일\"]

def gen_order_code():
    return f\"LUCY-{dt.datetime.now().strftime('%Y%m%d')}-{str(int(time.time()))[-4:]}\"

def score_item(row, chosen_tags, target_sweetness):
    item_tags = set(row[\"tags_list\"])
    tag_match = len(item_tags & set(chosen_tags))
    diff = abs(int(row[\"sweetness\"]) - int(target_sweetness))
    sweet_score = max(0, 3 - diff)
    bonus = 2 if \"#인기\" in item_tags else 0
    return tag_match*3 + sweet_score + bonus

def ranked_items(df, chosen_tags, sweet):
    if df.empty: return df.assign(_score=[])
    sc = df.apply(lambda r: score_item(r, chosen_tags, sweet), axis=1)
    return df.assign(_score=sc).sort_values([\"_score\",\"price\"], ascending=[False, True]).reset_index(drop=True)

def recommend_combos(df, chosen_tags, sweet, budget, topk=3):
    cand = ranked_items(df, chosen_tags, sweet).head(12)
    combos, idxs = [], list(cand.index)
    for r in range(1, 4):
        for ids in itertools.combinations(idxs, r):
            items = cand.loc[list(ids)]; total = int(items[\"price\"].sum())
            if total <= budget:
                score = float(items[\"_score\"].sum())
                combos.append((items, total, score, r))
    if not combos: return []
    combos.sort(key=lambda x: (-x[2], x[1], -x[3]))
    out, seen = [], set()
    for items, total, score, r in combos:
        sig = tuple(sorted(items[\"name\"].tolist()))
        if sig in seen: continue
        seen.add(sig); out.append((items, total, score, r))
        if len(out) == topk: break
    return out

def show_combo(idx, items, total, budget):
    with st.container():
        st.markdown(f\"### 세트 {idx} · 합계 **₩{total:,}** / 예산 ₩{int(budget):,}\")
        cols = st.columns(min(4, len(items)))
        for i, (_, r) in enumerate(items.iterrows()):
            with cols[i % len(cols)]:
                st.markdown(f\"- **{r['name']}**\")
                st.caption(f\"{r['category']} · ₩{int(r['price']):,}\")
                tags = ', '.join(r['tags_list']) if r['tags_list'] else '-'
                st.text(tags)

st.title(\"Lucy Bakery Menu Recommendation Service (Demo)\")

tabs = st.tabs([\"베이커리 조합 추천\", \"음료 추천\", \"메뉴판 보기\"])

with tabs[0]:
    st.subheader(\"예산 안에서 가능한 조합 3세트 (1~3개 자동)\")
    c1, c2 = st.columns([1,3])
    with c1:
        budget = st.number_input(\"총 예산(₩)\", 0, 200000, 20000, step=1000)
    with c2:
        st.caption(\"예산에 따라 세트 구성 수량이 1~3개로 자동 조정됩니다.\")
    st.markdown(\"---\")
    sweet = st.slider(\"당도 (0~5)\", 0, 5, 2)
    if 'soft_prev' not in st.session_state: st.session_state.soft_prev = []
    def enforce_max3():
        cur = st.session_state.soft
        if len(cur) > 3:
            st.session_state.soft = st.session_state.soft_prev
            st.toast(\"태그는 최대 3개까지 선택할 수 있어요.\", icon=\"⚠️\")
        else:
            st.session_state.soft_prev = cur
    soft = st.multiselect(\"취향 태그(최대 3개)\", SIMPLE_TAGS, key='soft', on_change=enforce_max3)
    st.caption(f\"선택: {len(soft)}/3\")

    if st.button(\"조합 3세트 추천받기 🍞\"):
        bakery_df = MENU[MENU[\"category\"].isin(BAKERY_CATS)].copy()
        if bakery_df[\"price\"].min() > budget:
            st.warning(\"예산이 너무 낮아요. 최소 한 개의 품목 가격보다 높게 설정해주세요.\")
        else:
            results = recommend_combos(bakery_df, soft, sweet, int(budget), topk=3)
            if not results:
                st.warning(\"조건에 맞는 조합을 만들 수 없어요. 예산이나 태그를 조정해보세요.\")
            else:
                for i, (items, total, score, r) in enumerate(results, start=1):
                    show_combo(i, items, total, budget)
                    with st.form(key=f'order_form_{i}', clear_on_submit=False):
                        submit = st.form_submit_button(f\"세트 {i} 주문하기 (데모)\")
                        if submit:
                            oc = gen_order_code()
                            st.success(f\"주문 완료! (데모) 주문번호: **{oc}**\")
                            st.caption(\"※ 발표 버전: 개인정보/DB/쿠폰 기능은 다음 발표에서 제공 예정입니다.\")

with tabs[1]:
    st.subheader(\"음료 추천 (카테고리 + 당도)\")
    cat = st.selectbox(\"음료 카테고리\", [\"커피\",\"라떼\",\"에이드\",\"스무디\",\"티\"])
    sweet_d = st.slider(\"음료 당도 (0~5)\", 0, 5, 3, key=\"drink_sweet\")
    if st.button(\"음료 추천받기 ☕️\"):
        drink_df = MENU[(MENU[\"category\"] == cat)].copy()
        ranked = ranked_items(drink_df, [], sweet_d)
        st.markdown(f\"**{cat} TOP3**\")
        for _, r in ranked.head(3).iterrows():
            st.markdown(f\"- **{r['name']}** · ₩{int(r['price']):,}\")

with tabs[2]:
    st.subheader(\"메뉴판 보기\")
    import os
    imgs = [p for p in [\"menu_board_1.png\",\"menu_board_2.png\"] if os.path.exists(p)]
    if imgs:
        st.image(imgs, use_container_width=True, caption=[f\"메뉴판 {i+1}\" for i in range(len(imgs))])
    else:
        st.info(\"menu_board_1.png, menu_board_2.png 파일을 앱과 같은 폴더에 넣으면 자동 표시됩니다.\")

st.divider()
st.caption(\"© 2025 Lucy Bakery – Demo Version\")

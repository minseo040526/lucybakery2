import streamlit as st
import pandas as pd
import random
import re

# --- 데이터 로드 및 전처리 ---
@st.cache_data
def load_data(file_path):
    """메뉴 데이터 로드 및 전처리"""
    try:
        df = pd.read_csv(file_path)
        # 태그를 리스트 형태로 변환 (예: "#달콤한,#부드러운" -> ['달콤한', '부드러운'])
        df['tags_list'] = df['tags'].apply(lambda x: [re.sub(r'#', '', tag).strip() for tag in x.split(',')])
        return df
    except FileNotFoundError:
        st.error(f"⚠️ 에러: {file_path} 파일을 찾을 수 없습니다. 파일을 확인해주세요.")
        return pd.DataFrame()

menu_df = load_data('menu (1).csv')

# 사용 가능한 모든 태그 추출 (중복 제거)
all_tags = sorted(list(set(tag for sublist in menu_df['tags_list'].dropna() for tag in sublist)))

# 사용자 DB (간단한 딕셔너리로 구현, 실제 서비스에서는 데이터베이스 사용 필요)
# {전화번호: {'coupons': int, 'visits': int}}
user_db = {}
# 초기 쿠폰함 설정
if 'user_db' not in st.session_state:
    st.session_state['user_db'] = user_db
if 'phone_number' not in st.session_state:
    st.session_state['phone_number'] = None
if 'page' not in st.session_state:
    st.session_state['page'] = 'home'

# --- 페이지 이동 함수 ---
def set_page(page_name):
    """페이지 이동을 위한 세션 상태 업데이트"""
    st.session_state['page'] = page_name

# --- 컴포넌트 함수 ---
def show_coupon_status():
    """현재 사용자의 쿠폰 상태 표시"""
    phone = st.session_state['phone_number']
    if phone and phone in st.session_state['user_db']:
        coupons = st.session_state['user_db'][phone]['coupons']
        st.sidebar.markdown(f"**🎫 쿠폰함**")
        st.sidebar.info(f"사용 가능한 쿠폰: **{coupons}개**")

def use_coupon_toggle():
    """쿠폰 사용 여부 체크박스 및 적용 로직"""
    if st.session_state['phone_number'] and st.session_state['user_db'][st.session_state['phone_number']]['coupons'] > 0:
        st.session_state['use_coupon'] = st.checkbox(
            '🎫 쿠폰 1개 사용 (총 주문 금액 1,000원 할인)',
            value=st.session_state.get('use_coupon', False)
        )
    else:
        st.session_state['use_coupon'] = False
        st.markdown("<p style='color:gray;'>사용 가능한 쿠폰이 없습니다.</p>", unsafe_allow_html=True)

# --- 메뉴 추천 로직 ---
def recommend_menus(df, budget, selected_tags, recommendation_count=3):
    """예산 및 태그를 고려한 메뉴 조합 추천"""

    # 1. 태그 필터링 (선택된 태그를 하나라도 포함하는 메뉴)
    if selected_tags:
        filtered_df = df[df['tags_list'].apply(lambda x: any(tag in selected_tags for tag in x))]
    else:
        filtered_df = df

    # 2. 메뉴 카테고리 분리 (음료/베이커리/기타)
    drink_df = filtered_df[filtered_df['category'].isin(['커피', '음료', '티'])]
    bakery_df = filtered_df[filtered_df['category'].isin(['빵', '디저트'])]
    
    # 예시 CSV에는 '음료' 카테고리가 없어서 '커피', '티'로 대체. 실제 데이터에 맞게 수정 필요.
    # CSV 내용 확인: '샌드위치', '샐러드', '디저트', '빵' -> 음료/커피 카테고리는 가상의 분류가 필요함.
    # 임시로 '빵'과 '디저트'를 베이커리로, '샌드위치'와 '샐러드'를 식사/기타로 간주.
    # **CSV에 '음료' 카테고리를 추가하는 것이 가장 정확합니다.**
    
    # 3. 메뉴 조합 추천 (간단한 휴리스틱)
    recommendations = []
    
    # 최소한의 메뉴 조합을 시도 (예: 1 베이커리/디저트 + 1 기타/식사)
    main_menu_df = filtered_df[filtered_df['category'].isin(['샌드위치', '샐러드'])]
    
    if main_menu_df.empty or bakery_df.empty:
        # 단품으로 예산 내에서 추천
        single_items = filtered_df[filtered_df['price'] <= budget].sort_values(by='price', ascending=False)
        for _, row in single_items.head(recommendation_count).iterrows():
            recommendations.append(f"{row['name']} ({row['price']}원)")
        
        # 조합이 어렵다면 단품 위주로 추천하고 종료
        if recommendations:
             st.warning("⚠️ 선택하신 조건으로는 다양한 조합이 어렵습니다. 예산 내의 단품 메뉴를 추천합니다.")
        return recommendations
    
    # 메인 + 베이커리 조합 추천 시도
    attempts = 0
    while len(recommendations) < recommendation_count and attempts < 100:
        attempts += 1
        
        # 무작위로 메인 메뉴와 베이커리 메뉴 선택
        main_item = main_menu_df.sample(1).iloc[0]
        bakery_item = bakery_df.sample(1).iloc[0]
        
        total_price = main_item['price'] + bakery_item['price']
        
        if total_price <= budget:
            combo = (
                f"**{main_item['name']}** + **{bakery_item['name']}** "
                f"(총 {total_price}원)"
            )
            # 중복 방지
            if combo not in [rec.split('(')[0].strip() for rec in recommendations]:
                recommendations.append(combo)

    # 조합이 부족할 경우, 가장 비싼 단품 메뉴 추가
    if len(recommendations) < recommendation_count:
        single_items = filtered_df[filtered_df['price'] <= budget].sort_values(by='price', ascending=False)
        for _, row in single_items.head(recommendation_count - len(recommendations)).iterrows():
            combo = f"**{row['name']}** (단품, {row['price']}원)"
            if combo not in [rec.split('(')[0].strip() for rec in recommendations]:
                recommendations.append(combo)
            
    return recommendations


# --- 페이지: 홈 (전화번호 입력) ---
def home_page():
    st.title("☕ AI 메뉴 추천 키오스크")
    
    # 전화번호 입력 섹션
    st.subheader("👋 환영합니다! 전화번호를 입력해주세요.")
    
    phone_input = st.text_input(
        "📱 휴대폰 번호 (예: 01012345678)", 
        max_chars=11, 
        key='phone_input_key'
    )
    
    # 입력 확인 및 사용자 등록/조회
    if st.button("시작하기"):
        if re.match(r'^\d{10,11}$', phone_input):
            st.session_state['phone_number'] = phone_input
            
            # DB 조회 또는 신규 등록
            if phone_input not in st.session_state['user_db']:
                st.session_state['user_db'][phone_input] = {'coupons': 0, 'visits': 1}
                st.success(f"🎉 신규 고객님으로 등록되었습니다!")
            else:
                st.session_state['user_db'][phone_input]['visits'] += 1
                st.info(f"✨ {phone_input} 고객님, 다시 오셨네요! 방문 횟수: {st.session_state['user_db'][phone_input]['visits']}회")
            
            set_page('recommend')
            st.rerun()
        else:
            st.error("유효하지 않은 전화번호 형식입니다. '-' 없이 10~11자리 숫자를 입력해주세요.")

# --- 페이지: 추천 설정 ---
def recommend_page():
    st.title("🤖 AI 맞춤 메뉴 추천")
    
    # 사이드바에 사용자 상태 표시
    show_coupon_status()
    
    st.subheader("1. 예산 설정 및 쿠폰 사용")
    
    budget = st.slider(
        "💰 최대 예산 설정 (원)",
        min_value=5000, 
        max_value=30000, 
        step=1000, 
        value=15000
    )
    
    # 쿠폰 사용 토글
    use_coupon_toggle()
    
    # 쿠폰 사용 시 예산 할인 적용 (단순 금액 할인으로 가정)
    final_budget = budget
    if st.session_state.get('use_coupon'):
        coupon_discount = 1000 # 쿠폰 할인 금액 설정
        final_budget = budget + coupon_discount # 예산에 할인을 더해서 더 많은 메뉴를 고를 수 있게 함 (실제 결제는 할인됨)
        st.info(f"쿠폰 사용으로 인해 **{coupon_discount}원** 할인 적용! 추천은 최대 {final_budget}원 기준으로 진행됩니다.")
        
    st.subheader("2. 선호 해시태그 선택 (최대 3개)")
    
    # 멀티셀렉트 박스로 최대 3개까지 선택 제한
    selected_tags = st.multiselect(
        "🏷️ 원하는 메뉴 스타일을 선택하세요:",
        options=all_tags,
        max_selections=3,
        default=st.session_state.get('selected_tags', [])
    )
    st.session_state['selected_tags'] = selected_tags

    # 추천 버튼
    if st.button("메뉴 추천 받기", type="primary"):
        st.session_state['recommendations'] = recommend_menus(menu_df, final_budget, selected_tags, recommendation_count=3)
        st.session_state['recommended'] = True
        st.rerun()

    # 추천 결과 표시
    if st.session_state.get('recommended'):
        st.markdown("---")
        st.subheader("✨ 추천 결과")
        
        if st.session_state['recommendations']:
            for i, rec in enumerate(st.session_state['recommendations']):
                st.success(f"**세트 {i+1}**: {rec}")
            
            # 주문 완료 버튼
            st.markdown("---")
            if st.button("🛒 주문 완료 및 쿠폰 발급"):
                set_page('order_complete')
                st.rerun()
        else:
            st.error("😭 선택하신 조건으로 추천 가능한 메뉴 조합이 없습니다. 예산 또는 해시태그를 조정해주세요.")

# --- 페이지: 주문 완료 ---
def order_complete_page():
    st.title("✅ 주문 완료")
    st.balloons()
    
    phone = st.session_state['phone_number']
    
    # 1. 쿠폰 사용 처리
    if st.session_state.get('use_coupon') and phone in st.session_state['user_db']:
        st.session_state['user_db'][phone]['coupons'] -= 1
        st.warning("🎫 쿠폰 1개가 사용되었습니다.")
        st.session_state['use_coupon'] = False # 사용 상태 초기화
    
    # 2. 쿠폰 발급 (재방문 시 쿠폰함에 저장)
    if phone in st.session_state['user_db']:
        st.session_state['user_db'][phone]['coupons'] += 1
        st.success("🎁 주문 감사 쿠폰 1개가 발급되어 쿠폰함에 저장되었습니다!")
        st.info(f"현재 사용 가능 쿠폰: **{st.session_state['user_db'][phone]['coupons']}개**")
    
    st.markdown("---")
    if st.button("🏠 처음으로 돌아가기"):
        # 상태 초기화
        st.session_state['phone_number'] = None
        st.session_state['recommended'] = False
        st.session_state['recommendations'] = []
        st.session_state['use_coupon'] = False
        set_page('home')
        st.rerun()

# --- 메인 앱 로직 ---
def main():
    st.set_page_config(page_title="AI 메뉴 추천", layout="centered")

    # 페이지 라우팅
    if st.session_state['page'] == 'home':
        home_page()
    elif st.session_state['page'] == 'recommend':
        recommend_page()
    elif st.session_state['page'] == 'order_complete':
        order_complete_page()

if __name__ == "__main__":
    main()


import streamlit as st
import pandas as pd
import sqlite3
import datetime
import requests
import random
from pathlib import Path

# --- 1. 데이터베이스 설정 (SQLite) ---
DB_FILE = "morning_ai.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 사용자 테이블
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (
                     user_id
                     TEXT
                     PRIMARY
                     KEY,
                     password
                     TEXT
                 )''')
    # 피드백 테이블
    c.execute('''CREATE TABLE IF NOT EXISTS feedback
                 (
                     user_id
                     TEXT,
                     menu_name
                     TEXT,
                     feedback
                     TEXT,
                     date
                     TEXT
                 )''')
    # 테스트 계정 생성 (admin/1234)
    c.execute("INSERT OR IGNORE INTO users VALUES ('admin', '1234')")
    conn.commit()
    conn.close()


def save_feedback_db(user_id, menu_name, feedback_type):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO feedback VALUES (?, ?, ?, ?)",
              (user_id, menu_name, feedback_type, datetime.date.today().isoformat()))
    conn.commit()
    conn.close()


init_db()


# --- 2. 날씨 정보 가져오기 ---
def get_weather():
    lat, lon = 37.5665, 126.9780  # 서울
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
    try:
        response = requests.get(url).json()
        current = response['current_weather']
        temp = current['temperature']
        code = current['weathercode']
        if code in [0]:
            condition = "맑음 ☀️"
        elif code in [1, 2, 3]:
            condition = "구름 조금 ⛅"
        elif code in [51, 53, 55, 61, 63, 65]:
            condition = "비 ☔"
        else:
            condition = "흐림 ☁️"
        return temp, condition
    except:
        return 20.0, "정보 없음 🌫️"


# --- 3. 맞춤형 SQL 추천 로직 ---
def get_personalized_recommendation(user_id, current_weather, context, menu_df):
    conn = sqlite3.connect(DB_FILE)

    # 1. 메뉴 데이터를 DB 임시 테이블로 업로드 (검색 효율화)
    menu_df.to_sql("menu_table", conn, if_exists="replace", index=False)

    # 2. 싫어요 메뉴 리스트 추출
    disliked_menus = pd.read_sql(
        f"SELECT menu_name FROM feedback WHERE user_id='{user_id}' AND feedback='dislike'", conn
    )['menu_name'].tolist()
    dislike_filter = f"WHERE name NOT IN ({str(disliked_menus)[1:-1]})" if disliked_menus else ""

    # 3. 상황별 조리시간 필터링
    time_limit = 15 if context == "출근" else 100
    time_filter = f"AND time <= {time_limit}" if dislike_filter else f"WHERE time <= {time_limit}"

    # 4. SQL 가중치 쿼리
    # - 좋아요 누른 태그 가중치 +2점
    # - 날씨 일치 보너스 +5점
    query = f"""
        SELECT m.*, 
               (COALESCE(p.weight, 0) * 2) + 
               (CASE WHEN m.weather_match LIKE '%{current_weather[:1]}%' THEN 5 ELSE 0 END) as score
        FROM menu_table m
        LEFT JOIN (
            SELECT m.tag, COUNT(f.feedback) as weight
            FROM feedback f
            JOIN menu_table m ON f.menu_name = m.name
            WHERE f.user_id='{user_id}' AND f.feedback='like'
            GROUP BY m.tag
        ) p ON m.tag = p.tag
        {dislike_filter}
        {time_filter}
        ORDER BY score DESC
        LIMIT 10
    """

    candidates = pd.read_sql(query, conn)
    conn.close()

    if not candidates.empty:
        return candidates.sample(1).iloc[0]  # 상위권 중 랜덤 하나 제안
    return menu_df.sample(1).iloc[0]


# --- 4. 세션 초기화 및 로직 함수 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'view' not in st.session_state:
    st.session_state.view = "main"


def login(uid, pw):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql(f"SELECT * FROM users WHERE user_id='{uid}' AND password='{pw}'", conn)
    conn.close()
    if not df.empty:
        st.session_state.logged_in = True
        st.session_state.user_id = uid
        st.session_state.view = "main"
        return True
    return False


# --- 5. 페이지 구성 ---

# [로그인 페이지]
if st.session_state.view == "login":
    st.title("🔐 맞춤형 추천을 시작합니다")
    st.write("피드백을 남기거나 본인 취향을 학습시키려면 로그인해주세요.")
    input_id = st.text_input("아이디 (기본: admin)")
    input_pw = st.text_input("비밀번호 (기본: 1234)", type="password")
    if st.button("로그인"):
        if login(input_id, input_pw):
            st.rerun()
        else:
            st.error("정보가 올바르지 않습니다.")
    if st.button("돌아가기"):
        st.session_state.view = "main"
        st.rerun()

# [메인 페이지]
elif st.session_state.view == "main":
    st.title("🍳 Morning AI: 내일 아침 메뉴 추천")

    try:
        menu_df = pd.read_csv("morning_menu.csv")
    except:
        st.error("menu_menu.csv 파일이 필요합니다.");
        st.stop()

    # 사이드바 설정
    with st.sidebar:
        if st.session_state.logged_in:
            st.success(f"✅ {st.session_state.user_id}님 커스텀 모드")
            if st.button("로그아웃"):
                st.session_state.logged_in = False;
                st.rerun()
        else:
            st.info("비로그인 (랜덤 추천 모드)")
            if st.button("로그인/가입"):
                st.session_state.view = "login";
                st.rerun()

        st.divider()
        context = st.radio("내일의 상황", ["출근", "휴일"])
        temp, condition = get_weather()
        st.metric(label="내일 예상 날씨", value=condition, delta=f"{temp} °C")

    # 추천 실행
    if st.session_state.logged_in:
        recommended_item = get_personalized_recommendation(st.session_state.user_id, condition, context, menu_df)
    else:
        recommended_item = menu_df.sample(1).iloc[0]

    st.container(border=True).markdown(f"""
        ### 🌙 AI의 내일 아침 제안
        **날씨** ({condition})와 {context} **상황을 고려한 결과입니다.**
        ### 🍱 **{recommended_item['name']}**
        **카테고리**: {recommended_item['tag']} | **소요시간**: {recommended_item['time']}분
    """)

    st.write("---")
    st.write("💡 이 메뉴가 마음에 드시나요?")
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("👍 좋아요"):
            if st.session_state.logged_in:
                save_feedback_db(st.session_state.user_id, recommended_item['name'], "like")
                st.balloons();
                st.success("취향에 반영되었습니다!")
            else:
                st.session_state.view = "login";
                st.rerun()
    with col2:
        if st.button("👎 별로예요"):
            if st.session_state.logged_in:
                save_feedback_db(st.session_state.user_id, recommended_item['name'], "dislike")
                st.rerun()
            else:
                st.session_state.view = "login";
                st.rerun()
    with col3:
        if st.button("🔄 다른 메뉴 보기"):
            if st.session_state.logged_in:
                st.rerun()
            else:
                st.session_state.view = "login";
                st.rerun()
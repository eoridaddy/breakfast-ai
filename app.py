import streamlit as st
import pandas as pd
import sqlite3
import datetime
import requests
import random
from pathlib import Path
import os


# --- 스타일 설정 (글자 크기 최적화 및 레이아웃 제어) ---
def inject_custom_css():
    st.markdown("""
        <style>
        /* 메뉴 이름: 화면 크기에 맞춰 폰트 크기 자동 조절 (clamp) */
        .menu-title {
            font-size: clamp(1.2rem, 4vw, 1.8rem) !important;
            font-weight: 800 !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            margin-bottom: 5px;
        }
        /* 카드 내부 텍스트 스타일 */
        .sub-text {
            font-size: 0.95rem !important;
            color: #666;
        }
        /* 이미지 둥근 모서리 적용 */
        .stImage > img {
            border-radius: 15px !important;
            object-fit: cover;
            max-height: 400px;
        }
        </style>
    """, unsafe_allow_html=True)


# --- 1. 데이터베이스 설정 ---
DB_FILE = "morning_ai.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (
                     user_id
                     TEXT
                     PRIMARY
                     KEY,
                     password
                     TEXT
                 )''')
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
    lat, lon = 37.5665, 126.9780
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
    try:
        response = requests.get(url).json()
        current = response['current_weather']
        temp = current['temperature']
        code = current['weathercode']
        if code == 0:
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

# --- 이미지 경로 찾기 함수 추가 ---
def get_local_image(menu_name):
    # images 폴더 경로 설정
    img_dir = "images"
    # 지원할 확장자 목록
    extensions = [".jpg", ".jpeg", ".png", ".webp"]

    for ext in extensions:
        img_path = os.path.join(img_dir, f"{menu_name}{ext}")
        if os.path.exists(img_path):
            return img_path

    # 이미지가 없을 경우 보여줄 기본 이미지 (또는 None)
    return None

# --- 3. 맞춤형 SQL 추천 로직 ---
def get_personalized_recommendation(user_id, current_weather, context, menu_df):
    conn = sqlite3.connect(DB_FILE)
    menu_df.to_sql("menu_table", conn, if_exists="replace", index=False)

    disliked_menus = pd.read_sql(
        f"SELECT menu_name FROM feedback WHERE user_id='{user_id}' AND feedback='dislike'", conn
    )['menu_name'].tolist()
    dislike_filter = f"WHERE name NOT IN ({str(disliked_menus)[1:-1]})" if disliked_menus else ""

    time_limit = 15 if context == "출근" else 100
    time_filter = f"AND time <= {time_limit}" if dislike_filter else f"WHERE time <= {time_limit}"

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
        {dislike_filter} {time_filter}
        ORDER BY score DESC LIMIT 10
    """
    candidates = pd.read_sql(query, conn)
    conn.close()
    return candidates.sample(1).iloc[0] if not candidates.empty else menu_df.sample(1).iloc[0]


# --- 4. 세션 초기화 ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_id' not in st.session_state: st.session_state.user_id = None
if 'view' not in st.session_state: st.session_state.view = "main"


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
inject_custom_css()

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

elif st.session_state.view == "main":
    st.title("🍳 Morning AI")

    try:
        menu_df = pd.read_csv("morning_menu.csv")
    except:
        st.error("CSV 파일이 없습니다.");
        st.stop()

    with st.sidebar:
        if st.session_state.logged_in:
            st.success(f"👤 {st.session_state.user_id}님")
            if st.button("로그아웃"): st.session_state.logged_in = False; st.rerun()
        else:
            if st.button("로그인/가입"): st.session_state.view = "login"; st.rerun()
        st.divider()
        context = st.radio("상황", ["출근", "휴일"])
        temp, condition = get_weather()
        st.metric("내일 날씨", condition, f"{temp} °C")

    # 추천 로직 실행
    if st.session_state.logged_in:
        recommended_item = get_personalized_recommendation(st.session_state.user_id, condition, context, menu_df)
    else:
        recommended_item = menu_df.sample(1).iloc[0]

    # --- 메인 추천 카드 (이미지 포함) ---
    st.write("### 🌙 AI가 추천하는 내일 아침")

    # Unsplash를 이용한 음식 사진 자동 매칭
    # --- 로컬 이미지 불러오기 적용 ---
    img_path = get_local_image(recommended_item['name'])

    container = st.container(border=True)
    if img_path:
        container.image(img_path, use_column_width=True)
    else:
        # 이미지가 없을 경우 안내 문구 또는 플레이스홀더
        container.info(f"'{recommended_item['name']}' 이미지를 images 폴더에 추가해주세요.")

    container.markdown(f"<p class='menu-title'>{recommended_item['name']}</p>", unsafe_allow_html=True)
    container.markdown(f"<p class='sub-text'>🏷️ {recommended_item['tag']} | ⏱️ {recommended_item['time']}분 소요</p>",
                       unsafe_allow_html=True)

    st.write("💡 이 메뉴는 어떠신가요?")
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("👍 좋아요"):
            if st.session_state.logged_in:
                save_feedback_db(st.session_state.user_id, recommended_item['name'], "like")
                st.toast("취향 저격! 데이터에 반영했습니다.");
                st.balloons()
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
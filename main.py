import streamlit as st
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # 파이썬 기본 내장 모듈이라 별도 설치가 필요 없어요.
import pandas as pd

# ──────────────────────────────────────────────
# 기본 설정
# ──────────────────────────────────────────────
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

KOBIS_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"


def get_yesterday_kst_date():
    """
    한국 시간(KST) 기준 '어제' 날짜를 date 객체로 반환합니다.
    달력에서 고를 수 있는 가장 늦은 날짜(max_value)로 사용하기 위함입니다.
    배포 서버가 한국 시간이 아니어도 항상 한국 기준 '어제'가 나오도록
    zoneinfo로 한국 시간대를 직접 지정합니다.
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.date()


@st.cache_data(ttl=3600)  # 3600초 = 1시간 동안 같은 날짜 요청 결과를 기억(캐시)합니다.
def fetch_box_office(target_dt: str):
    """
    KOBIS 일별 박스오피스 API를 호출합니다.
    성공하면 영화 리스트(list[dict])를 반환하고,
    실패하면 (None, "에러 메시지") 형태로 이유를 함께 반환합니다.
    """
    api_key = st.secrets.get("KOBIS_KEY")
    if not api_key:
        return None, "secrets에 KOBIS_KEY가 설정되어 있지 않아요. Streamlit Cloud의 'Secrets' 설정을 확인해 주세요."

    params = {
        "key": api_key,
        "targetDt": target_dt,
    }

    try:
        response = requests.get(KOBIS_URL, params=params, timeout=10)
    except requests.exceptions.RequestException as e:
        return None, f"인터넷 연결 또는 KOBIS 서버 상태를 확인해 주세요. (오류: {e})"

    if response.status_code != 200:
        return None, f"KOBIS 서버가 정상 응답을 주지 않았어요. (상태 코드: {response.status_code})"

    try:
        data = response.json()
    except ValueError:
        return None, "KOBIS 응답을 해석할 수 없어요. 잠시 후 다시 시도해 주세요."

    # 인증키가 틀려도 상태코드는 200이고 대신 faultInfo가 옵니다.
    if "faultInfo" in data:
        fault = data["faultInfo"]
        message = fault.get("message", "알 수 없는 오류")
        return None, f"KOBIS API 오류가 발생했어요: {message}. 인증키(KOBIS_KEY)가 올바른지 확인해 주세요."

    try:
        movie_list = data["boxOfficeResult"]["dailyBoxOfficeList"]
    except (KeyError, TypeError):
        return None, "응답 구조가 예상과 달라요. KOBIS API 문서가 변경되었는지 확인해 주세요."

    if not movie_list:
        # 목록이 비어 있는 경우는 '아직 집계 전'일 가능성이 커서, 다른 오류들과
        # 구분되는 별도의 표시("EMPTY")를 돌려줍니다. 화면 쪽에서 이 표시를 보고
        # 전용 안내 문구를 보여줘요.
        return None, "EMPTY"

    return movie_list, None


def to_int(value: str) -> int:
    """API에서 문자열로 오는 숫자를 정수로 안전하게 변환합니다."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ──────────────────────────────────────────────
# 화면 그리기
# ──────────────────────────────────────────────
st.title("🎬 날짜별 박스오피스")

yesterday_kst_date = get_yesterday_kst_date()

# 달력에서 날짜를 고를 수 있게 합니다. 오늘 건 아직 집계 전이라
# 고를 수 있는 가장 늦은 날짜는 어제(max_value)까지로 제한합니다.
selected_date = st.date_input(
    "조회할 날짜를 선택하세요",
    value=yesterday_kst_date,
    max_value=yesterday_kst_date,
)

target_dt = selected_date.strftime("%Y%m%d")
display_date = selected_date.strftime("%Y-%m-%d")
st.caption(f"선택한 날짜: {display_date}")

movie_list, error_message = fetch_box_office(target_dt)

if error_message == "EMPTY":
    st.info("📭 그날은 아직 집계 전입니다.")
    st.stop()
elif error_message:
    st.error(f"⚠️ 데이터를 불러오지 못했어요.\n\n{error_message}")
    st.stop()

# ── 문자열로 온 숫자들을 정수로 변환한 표 데이터 만들기 ──
rows = []
for m in movie_list:
    audi_acc = to_int(m.get("audiAcc"))
    rank_inten = to_int(m.get("rankInten"))  # 전날 대비 순위 증감(양수: 상승, 음수: 하락)

    # rankInten 부호에 따라 화살표를 붙입니다. 색은 아래 스타일링 단계에서
    # _rank_inten 값을 보고 입힙니다(오른 영화: 빨강, 내린 영화: 파랑).
    if rank_inten > 0:
        rank_display = f"{to_int(m.get('rank'))} ▲"
    elif rank_inten < 0:
        rank_display = f"{to_int(m.get('rank'))} ▼"
    else:
        rank_display = f"{to_int(m.get('rank'))}"

    # 누적관객이 100만 명을 넘으면 영화명 옆에 트로피를 붙입니다.
    movie_name = m.get("movieNm", "")
    if audi_acc >= 1_000_000:
        movie_name = f"{movie_name} 🏆"

    rows.append({
        "정렬용순위": to_int(m.get("rank")),  # 화면에는 안 보이지만 정렬 기준으로 씁니다.
        "순위": rank_display,
        "영화명": movie_name,
        "개봉일": m.get("openDt", ""),
        "관객수": to_int(m.get("audiCnt")),
        "누적관객": audi_acc,
        "스크린수": to_int(m.get("scrnCnt")),
        "_rank_inten": rank_inten,  # 화면에는 안 보이지만 화살표 색을 정할 때 씁니다.
    })

df = pd.DataFrame(rows).sort_values("정렬용순위").drop(columns="정렬용순위").reset_index(drop=True)

# ── 1위 영화: 지표 카드 3장 ──
top_movie = df.iloc[0]
st.subheader(f"🥇 1위: {top_movie['영화명']}")

col1, col2, col3 = st.columns(3)
col1.metric("해당일 관객수", f"{top_movie['관객수']:,}명")
col2.metric("누적 관객수", f"{top_movie['누적관객']:,}명")
col3.metric("스크린수", f"{top_movie['스크린수']:,}개")

st.divider()

# ── 관객수 상위 5편: 막대그래프 ──
st.subheader("📊 관객수 상위 5편")
top5 = df.sort_values("관객수", ascending=False).head(5).set_index("영화명")
st.bar_chart(top5["관객수"])

st.divider()

# ── 전체 표 ──
st.subheader("📋 전체 순위표")


def color_rank_cell(row):
    """'순위' 칸에만 색을 입힙니다. 순위가 오른 영화는 빨강, 내린 영화는 파랑입니다."""
    styles = [""] * len(row)
    rank_col_pos = df.columns.get_loc("순위")
    if row["_rank_inten"] > 0:
        styles[rank_col_pos] = "color: red; font-weight: bold;"
    elif row["_rank_inten"] < 0:
        styles[rank_col_pos] = "color: blue; font-weight: bold;"
    return styles


styled_df = (
    df.style
    .format({"관객수": "{:,}", "누적관객": "{:,}", "스크린수": "{:,}"})
    .apply(color_rank_cell, axis=1)
    .hide(axis="columns", subset=["_rank_inten"])  # 색칠용 숨은 칸은 화면에 표시하지 않습니다.
)

st.dataframe(
    styled_df,
    use_container_width=True,
    hide_index=True,
)

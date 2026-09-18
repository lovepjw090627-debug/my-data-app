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


def get_yesterday_kst() -> str:
    """
    한국 시간(KST) 기준으로 '어제' 날짜를 yyyymmdd 형식으로 계산합니다.
    배포 서버가 한국 시간이 아니어도 항상 한국 기준 '어제'가 나오도록
    zoneinfo로 한국 시간대를 직접 지정합니다.
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


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
        return None, "해당 날짜의 박스오피스 데이터가 비어 있어요. 날짜가 너무 이르거나(아직 집계 전) 통계가 없는 날일 수 있어요."

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
st.title("🎬 어제의 박스오피스")

target_dt = get_yesterday_kst()
display_date = f"{target_dt[:4]}-{target_dt[4:6]}-{target_dt[6:]}"
st.caption(f"기준 날짜(한국 시간 기준 어제): {display_date}")

movie_list, error_message = fetch_box_office(target_dt)

if error_message:
    st.error(f"⚠️ 데이터를 불러오지 못했어요.\n\n{error_message}")
    st.stop()

# ── 문자열로 온 숫자들을 정수로 변환한 표 데이터 만들기 ──
rows = []
for m in movie_list:
    rows.append({
        "순위": to_int(m.get("rank")),
        "영화명": m.get("movieNm", ""),
        "개봉일": m.get("openDt", ""),
        "관객수": to_int(m.get("audiCnt")),
        "누적관객": to_int(m.get("audiAcc")),
        "스크린수": to_int(m.get("scrnCnt")),
    })

df = pd.DataFrame(rows).sort_values("순위").reset_index(drop=True)

# ── 1위 영화: 지표 카드 3장 ──
top_movie = df.iloc[0]
st.subheader(f"🥇 1위: {top_movie['영화명']}")

col1, col2, col3 = st.columns(3)
col1.metric("어제 관객수", f"{top_movie['관객수']:,}명")
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
st.dataframe(
    df.style.format({"관객수": "{:,}", "누적관객": "{:,}", "스크린수": "{:,}"}),
    use_container_width=True,
    hide_index=True,
)

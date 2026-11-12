"""Market dashboard for Stock Analyzer — read-only selected-stock pulse.

Coverage: explicitly curated Korean stock basket, never all KRX listings.
Naver public quotes can be delayed; request time is not execution timestamp.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from access_gate import require_login
from app_navigation import render_navigation
from data_sources import SEED

st.set_page_config(page_title="시장 대시보드 · Stock Analyzer",
                   page_icon="📊", layout="wide")
require_login(st)
render_navigation(st)

# Deliberately small, disclosed sample basket: not market-wide rankings.
SECTORS = {
    "반도체": ("005930", "000660", "042700"),
    "2차전지": ("373220", "006400", "247540", "086520", "051910"),
    "전력기기": ("267260", "298040", "034020"),
    "방산": ("012450", "047810"),
    "조선": ("009540", "010140"),
    "자동차": ("005380", "000270", "012330"),
    "인터넷": ("035420", "035720"),
    "바이오": ("207940", "068270", "196170"),
    "금융": ("105560", "055550", "086790"),
    "미디어·엔터": ("035900", "035760"),
    "게임": ("263750",),
    "지주·복합": ("028260",),
}
BASKET = {
    code: {"업종":sector, "종목명":SEED[code][0], "시장":SEED[code][1]}
    for sector, codes in SECTORS.items()
    for code in codes
    if code in SEED
}

st.markdown("""
<style>
.stock-market-hero{background:linear-gradient(110deg,#dff1e9,#f7fcfa);
 border:1px solid #cae5d9;border-left:5px solid #008878;border-radius:13px;
 padding:18px 24px;margin:3px 0 15px}
.stock-market-hero h2{margin:0 0 5px!important;color:#155448!important;
 font-size:27px!important;font-weight:800}
.stock-market-hero p{margin:0;color:#58776b;font-size:13px}
.stock-dashboard-hint{border:1px solid #c3e2d3;border-radius:9px;
 background:#ebf7f0;padding:11px 15px;color:#235b48;font-size:14px;
 font-weight:650;margin:12px 0}
</style>
""", unsafe_allow_html=True)


def _now_kst():
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST")


def _num(value):
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return float("nan")


def _read_naver(codes):
    """Get one or more SERVICE_ITEM quotes, never silently fabricate values."""
    try:
        response = requests.get(
            "https://polling.finance.naver.com/api/realtime",
            params={"query": "SERVICE_ITEM:" + ",".join(codes)},
            headers={"User-Agent": "Mozilla/5.0",
                     "Referer": "https://finance.naver.com/",
                     "Accept": "application/json, text/plain, */*"},
            timeout=(3, 7),
        )
        response.raise_for_status()
        received = {}
        for area in response.json().get("result", {}).get("areas", []):
            for item in area.get("datas", []):
                if isinstance(item, dict):
                    code = str(item.get("cd", "")).strip().zfill(6)
                    if code in codes:
                        received[code] = item
        return received
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return {}


@st.cache_data(ttl=120, show_spinner=False)
def _market_quotes():
    codes = list(BASKET)
    details = {}
    groups = [codes[i:i + 6] for i in range(0, len(codes), 6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_read_naver, part) for part in groups]
        for future in as_completed(futures):
            details.update(future.result())

    # Bounded recovery when the provider ignores part of a bulk request.
    missing = [code for code in codes if code not in details]
    if missing:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_read_naver, [code]) for code in missing[:16]]
            for future in as_completed(futures):
                details.update(future.result())

    rows = []
    for code, info in BASKET.items():
        q = details.get(code)
        if q is None:
            continue
        price = _num(q.get("nv"))
        change = _num(q.get("cr"))
        if pd.isna(price) or pd.isna(change) or price <= 0 or abs(change) > 100:
            continue
        sign = str(q.get("rf", ""))
        if sign in ("4", "5"):
            change = -abs(change)
        elif sign in ("1", "2"):
            change = abs(change)
        rows.append({
            "종목명": info["종목명"], "종목코드": code,
            "시장": info["시장"], "업종": info["업종"],
            "현재가(원)": int(round(price)),
            "등락률(%)": round(change, 2),
        })
    return pd.DataFrame(rows), _now_kst()


def _tile_color(value):
    value = float(value)
    if value > 0:
        return "#056744" if value >= 3 else "#11805b" if value >= 1 else "#259976"
    if value < 0:
        return "#a12b40" if value <= -3 else "#be3b50" if value <= -1 else "#ce6070"
    return "#738787"


def _go_analyze(code):
    # The Analyze page reads this session value as its initial sidebar query.
    st.session_state["query"] = str(code)
    st.switch_page("app.py")


def _render_ranked(frame, title, positive=True):
    st.markdown("#### " + title)
    ordered = frame.sort_values("등락률(%)", ascending=not positive).head(6)
    if ordered.empty:
        st.caption("조건에 해당하는 종목이 없습니다.")
    for _, row in ordered.iterrows():
        name, code = str(row["종목명"]), str(row["종목코드"])
        change = float(row["등락률(%)"])
        first, second = st.columns([4.2, 1.1], vertical_alignment="center")
        first.markdown(
            f"**{escape(name)}** · {escape(code)} "
            f"　{'🟢' if change >= 0 else '🔴'} **{change:+.2f}%**"
        )
        if second.button("🔎 분석", key=f"rank_{'up' if positive else 'down'}_{code}",
                         use_container_width=True):
            _go_analyze(code)


st.markdown(
    '<div class="stock-market-hero"><h2>📊 STOCK MARKET PULSE</h2>'
    '<p>국내 주식 시장 흐름 → 관심 업종 탐색 → 개별 종목 상세 분석</p></div>',
    unsafe_allow_html=True,
)

c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
with c1:
    scope = st.radio("시장", ["전체", "KOSPI", "KOSDAQ"],
                     horizontal=True, key="stock_dashboard_market")
with c2:
    if st.button("🔄 최신 시세 새로고침", use_container_width=True,
                 key="stock_dashboard_refresh"):
        _market_quotes.clear()
        st.rerun()

with st.spinner("주요 종목의 최신 시세 조회 중..."):
    quotes, fetched_at = _market_quotes()

st.caption(
    f"조회 요청 완료: {fetched_at} · 네이버 금융 공개 시세(지연 가능) · "
    f"주요 종목 {len(BASKET)}개 중 {len(quotes)}개 시세 확인 · 2분 캐시"
)
st.caption(
    "이 화면은 주요 종목 표본을 비교하며 전종목 상승률 순위나 공식 업종지수가 아닙니다. "
    "조회 시각은 실제 체결시각이 아니고, 휴장·장 종료 시 마지막 제공 시세가 표시될 수 있습니다."
)
if quotes.empty:
    st.warning("시세 제공처에서 종목 가격을 확인하지 못했습니다. "
               "잠시 후 새로고침하거나 제공처 연결 상태를 확인하세요.")
    st.stop()

if scope != "전체":
    quotes = quotes.loc[quotes["시장"] == scope].copy()
if quotes.empty:
    st.warning("선택한 시장에서 조회된 종목이 없습니다.")
    st.stop()

count_up = int((quotes["등락률(%)"] > 0).sum())
count_down = int((quotes["등락률(%)"] < 0).sum())
sector = (quotes.groupby("업종", as_index=False)
          .agg(평균등락률=("등락률(%)", "mean"), 종목수=("종목코드", "nunique")))
sector["평균등락률"] = sector["평균등락률"].round(2)
sector = sector.sort_values("평균등락률", ascending=False).reset_index(drop=True)

m1, m2, m3, m4 = st.columns(4)
m1.metric("상승 종목", f"{count_up}개")
m2.metric("하락 종목", f"{count_down}개")
m3.metric("최강세 업종", str(sector.iloc[0]["업종"]),
          f'{float(sector.iloc[0]["평균등락률"]):+.2f}%')
m4.metric("시세 확인 종목", f"{len(quotes)}개")

st.subheader("🟩 업종별 주식 모멘텀 히트맵")
st.caption("업종에 속한 조회 성공 종목의 등락률 단순평균 · 녹색 상승 / 빨간색 하락 · "
           "타일 크기는 등락폭을 반영(최소 면적 보정) · 시가총액 가중 아님")

fig = go.Figure(go.Treemap(
    ids=["industry/" + x for x in sector["업종"]],
    labels=sector["업종"].tolist(),
    parents=[""] * len(sector),
    values=(sector["평균등락률"].abs() + .35).tolist(),
    text=[f"{name}<br>{pct:+.2f}%"
          for name, pct in zip(sector["업종"], sector["평균등락률"])],
    textinfo="text",
    textfont=dict(color="white", size=16),
    customdata=sector[["평균등락률", "종목수"]].to_numpy(),
    hovertemplate="%{label}<br>평균 등락률 %{customdata[0]:+.2f}%"
                  "<br>표본 종목 %{customdata[1]}개<extra></extra>",
    marker=dict(colors=[_tile_color(x) for x in sector["평균등락률"]],
                line=dict(color="#f4f8f7", width=3)),
    tiling=dict(packing="squarify", pad=3),
    sort=False,
    pathbar=dict(visible=False),
))
fig.update_layout(margin=dict(l=0, r=0, t=1, b=0), height=405,
                  paper_bgcolor="rgba(0,0,0,0)")
# Plotly treemap zoom is not relied on for selection; an explicit sector picker
# below works reliably on desktop and mobile.
st.plotly_chart(fig, use_container_width=True,
                config={"displayModeBar": False})

st.markdown('<div class="stock-dashboard-hint">🔎 관심 업종을 선택해 '
            '종목별 등락률을 비교하거나, 아래 종목의 <b>분석</b> 버튼으로 '
            '기존 Analyze 화면에 바로 이동하세요.</div>',
            unsafe_allow_html=True)
chosen_sector = st.selectbox(
    "업종 선택 · 관련 종목 확인", sector["업종"].tolist(),
    key="stock_dashboard_sector"
)
members = quotes.loc[quotes["업종"] == chosen_sector].sort_values(
    "등락률(%)", ascending=False
)
st.dataframe(
    members[["종목명", "종목코드", "시장", "현재가(원)", "등락률(%)"]],
    hide_index=True, use_container_width=True, height=min(350, 37 * len(members) + 45),
    column_config={
        "현재가(원)": st.column_config.NumberColumn(format="%d"),
        "등락률(%)": st.column_config.NumberColumn(format="%+.2f")
    },
)
selected_code = st.selectbox(
    "상세 분석할 종목", members["종목코드"].tolist(),
    format_func=lambda code: f"{BASKET[code]['종목명']} ({code})",
    key="stock_dashboard_analyze_code"
)
if st.button("🔎 선택 종목 Analyze 상세분석", type="primary",
             use_container_width=True):
    _go_analyze(selected_code)

st.divider()
left, right = st.columns(2)
with left:
    _render_ranked(quotes.loc[quotes["등락률(%)"] > 0], "📈 강세 종목 TOP 6", True)
with right:
    _render_ranked(quotes.loc[quotes["등락률(%)"] < 0], "📉 약세 종목 TOP 6", False)

with st.expander("📋 전체 모니터링 종목 보기", expanded=False):
    st.dataframe(
        quotes.sort_values("등락률(%)", ascending=False),
        hide_index=True, use_container_width=True, height=430,
        column_config={
            "현재가(원)": st.column_config.NumberColumn(format="%d"),
            "등락률(%)": st.column_config.NumberColumn(format="%+.2f")
        },
    )
st.caption("CREATED BY K.H.AHN · 시장 대시보드는 투자 참고용이며, "
           "개별 종목 분석과 매매 판단은 별도로 검토해야 합니다.")

"""Standalone, password-protected Streamlit page: investor-flow reversal."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from access_gate import require_login
from flow_reversal import assess_reversal, load_candidates, load_stock_history

st.set_page_config(page_title="수급 전환 검색 · Stock Analyzer", page_icon="🔄",
                   layout="wide")
require_login(st)

from krx_auth import configure_streamlit_krx
KRX_LOGIN_READY = configure_streamlit_krx(st)


@st.cache_data(ttl=7200, show_spinner=False)
def cached_candidates(day, markets, each_investor):
    return load_candidates(day, markets, each_investor)


@st.cache_data(ttl=7200, show_spinner=False)
def cached_history(code, day):
    return load_stock_history(code, day)


def default_session_date():
    local = datetime.now(ZoneInfo("Asia/Seoul"))
    # KRX final investor classifications can be delayed. Before evening,
    # default to yesterday; user can explicitly select any past date.
    day = local.date() if local.hour >= 19 else local.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


st.title("🔄 수급 전환 종목 검색")
if not KRX_LOGIN_READY:
    st.warning("KRX 회원 로그인 미설정: Streamlit Secrets에 KRX_ID / KRX_PW가 필요합니다.")
st.caption("Stock Analyzer · 개인 매수 우세 → 개인 대량 순매도 + 외국인·기관 순매수 전환")
st.info(
    "이 검색은 **KRX 외국인·기관 순매수 순위에 잡힌 후보군만** 심층 분석합니다. "
    "전 상장종목의 누락 없는 탐색은 아니며, 장중 실시간 신호도 아닙니다. "
    "실제 KRX 확정 데이터의 기준일이 일치할 때만 결과를 표시합니다."
)

c1, c2, c3 = st.columns([1.1, 1.3, 1])
with c1:
    target = st.date_input("검색 기준 거래일", value=default_session_date(),
                           max_value=datetime.now(ZoneInfo("Asia/Seoul")).date())
with c2:
    markets = st.multiselect("시장", ["KOSPI", "KOSDAQ"],
                             default=["KOSPI", "KOSDAQ"])
with c3:
    lookback = st.selectbox("개인 순매수 판정 기간", [10, 20], index=0,
                            format_func=lambda x: f"직전 {x}거래일")

f1, f2, f3, f4 = st.columns(4)
with f1:
    max_candidates = st.selectbox("심층 조회할 최대 후보", [10, 20, 40, 60, 80], index=1)
with f2:
    sell_multiple = st.selectbox("개인 순매도 이례성", [1.5, 2.0, 3.0], index=1,
                                 format_func=lambda v: f"평소 순매매 규모의 {v:g}배 이상")
with f3:
    sell_share = st.selectbox("당일 개인 순매도량 / 거래량", [0.03, 0.05, 0.10],
                              index=1, format_func=lambda v: f"{v:.0%} 이상")
with f4:
    min_turnover_eok = st.selectbox("최소 거래대금 근사치", [10, 30, 50, 100],
                                    index=2, format_func=lambda n: f"{n}억원 이상")

st.caption(
    "기본 검색식: 직전 기간 개인 순매수일 60% 이상·개인 순매수 누적 양수 → "
    "기준일 개인 순매도 + 외국인·기관 합산 순매수 양수. "
    "개인 순매도량은 직전 기간 개인 일별 순매매 절댓값의 중앙값과 비교합니다. "
    "거래대금은 종가×거래량 근사치이며, 공식 거래대금이 아닙니다."
)

if st.button("🔎 수급 전환 검색 실행", type="primary", use_container_width=True):
    if not markets:
        st.warning("최소 한 개 시장을 선택하세요.")
    else:
        with st.spinner("외국인·기관 순매수 상위 후보 목록 확인 중"):
            candidates, notices, feeds = cached_candidates(
                str(target), tuple(markets), max(10, max_candidates // 2))
        if feeds == 0:
            st.session_state["reversal_run"] = {
                "rows": [], "notices": notices, "candidates": 0,
                "attempted": 0, "failed": 0, "target": str(target),
                "error": "KRX 수급 순위 응답을 받지 못했습니다. KRX 조회 권한·접속 상태를 확인하세요.",
            }
        else:
            count = min(len(candidates), max_candidates)
            selected = candidates[:count]
            progress = st.progress(0, text="후보종목 검증 시작")
            rows = []
            failed = 0
            for i, item in enumerate(selected, start=1):
                try:
                    quantities, amounts, prices = cached_history(item["code"], str(target))
                    result = assess_reversal(
                        quantities, amounts, prices, target,
                        lookback=lookback,
                        min_sell_multiple=sell_multiple,
                        min_sell_share=sell_share,
                        min_turnover=min_turnover_eok * 100_000_000,
                    )
                    if result is not None:
                        rows.append({"code": item["code"], "name": item["name"],
                                     "market": item["market"], **result})
                except Exception:
                    failed += 1
                progress.progress(i / count, text=f"후보 {i}/{count}종목 확인") if count else None
            progress.empty()
            st.session_state["reversal_run"] = {
                "rows": sorted(rows, key=lambda x: (
                    x["strength"], abs(x["personal_net_krw"])), reverse=True),
                "notices": notices, "candidates": len(candidates),
                "attempted": count, "failed": failed, "target": str(target),
                "error": "",
                "config": (lookback, sell_multiple, sell_share, min_turnover_eok),
            }

run = st.session_state.get("reversal_run")
if run:
    st.divider()
    st.subheader(f"검색 결과 · 기준일 {run['target']}")
    if run.get("error"):
        st.error(run["error"])
    a, b, c, d = st.columns(4)
    a.metric("순위 기반 후보군", f"{run['candidates']}종목")
    b.metric("심층 조회", f"{run['attempted']}종목")
    c.metric("전환 조건 충족", f"{len(run['rows'])}종목")
    d.metric("조회 예외", f"{run['failed']}종목")
    if run.get("notices"):
        with st.expander("공급처/시장별 조회 상태", expanded=bool(run.get("error"))):
            for note in run["notices"]:
                st.caption("• " + note)
    if run["failed"]:
        st.warning("조회 실패 종목은 수급 전환 미발생으로 해석할 수 없습니다. 검색을 재실행해 확인하세요.")

    if run["rows"]:
        rows = pd.DataFrame(run["rows"])
        listing = pd.DataFrame({
            "종목명": rows["name"],
            "종목코드": rows["code"],
            "시장": rows["market"],
            "판정": rows["strength_label"],
            "전환강도": rows["strength"],
            "개인 매수일수": rows["personal_buy_days"].astype(str) + "/" + rows["prior_days"].astype(str),
            "개인 순매도(주)": rows["personal_net_qty"],
            "외국인 순매수(주)": rows["foreign_net_qty"],
            "기관 순매수(주)": rows["institution_net_qty"],
            "개인 매도/거래량(%)": rows["personal_sell_share_pct"],
            "평소대비(배)": rows["personal_sell_multiple"],
            "거래량증가(배)": rows["volume_ratio"],
            "개인 순매도(억원)": (rows["personal_net_krw"] / 1e8).round(1),
            "외국인+기관 순매수(억원)": (
                (rows["foreign_net_krw"] + rows["institution_net_krw"]) / 1e8).round(1),
        })
        st.dataframe(listing, use_container_width=True, hide_index=True,
                     height=min(650, 45 + 35 * (len(listing) + 1)))
        st.caption("전환강도는 조건 충족 후보의 상대적 우선순위용 0~100 휴리스틱 지표이며 "
                   "상승 확률·추천 목표주가가 아닙니다.")
        csv = listing.to_csv(index=False).encode("utf-8-sig")
        st.download_button("검색 결과 CSV 저장", data=csv,
                           file_name="investor_flow_reversal_" + run["target"] + ".csv",
                           mime="text/csv")
        choices = {f"{row['name']} ({row['code']})": row for row in run["rows"]}
        chosen_label = st.selectbox("수급 추이 상세 확인", list(choices))
        chosen = choices[chosen_label]
        st.markdown(
            f"**{chosen['name']}** — 직전 {chosen['prior_days']}거래일 중 개인 순매수 "
            f"{chosen['personal_buy_days']}일 · 기준일 개인 {chosen['personal_net_qty']:,}주 "
            f"· 외국인 {chosen['foreign_net_qty']:+,}주 · 기관 {chosen['institution_net_qty']:+,}주"
        )
        try:
            vol, val, px = cached_history(chosen["code"], run["target"])
            chart = vol[["개인", "외국인합계", "기관합계"]].tail(22).copy()
            chart.index = pd.to_datetime(chart.index)
            chart = chart.loc[chart.index <= pd.Timestamp(run["target"])]
            figure = go.Figure()
            for name, color in (("개인", "#e87d31"), ("외국인합계", "#138c78"),
                                ("기관합계", "#6298c2")):
                figure.add_trace(go.Bar(
                    x=chart.index, y=chart[name], name=name,
                    marker_color=color))
            figure.update_layout(
                barmode="relative", template="plotly_white", height=390,
                title="일별 투자주체 순매수 수량 (양수=순매수, 음수=순매도)",
                xaxis_title="거래일", yaxis_title="순매수량(주)",
                margin=dict(l=10, r=10, t=45, b=10),
            )
            st.plotly_chart(figure, use_container_width=True)
        except Exception:
            st.caption("해당 종목의 상세 차트 데이터를 불러오지 못했습니다.")
        if st.button("이 종목을 Stock Analyzer에서 상세 분석"):
            st.session_state["query"] = chosen["code"]
            st.switch_page("app.py")
    elif not run.get("error"):
        st.warning(
            "현재 조회된 후보군에서 조건을 모두 만족하는 종목이 없습니다. "
            "해당일 신호가 없을 수도 있고 KRX 응답이나 순위 기반 후보 범위가 제한되었을 수도 있습니다. "
            "조회 상한 또는 이례성 기준을 조정해 다시 확인하세요."
        )

"""Stock Analyzer · market-wide personal-to-foreign/institutional flow radar."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from access_gate import require_login
from full_flow_scan import ScanDataError, run_full_scan
from flow_scan_delivery import already_notified, persist_scan, read_latest_scan
from flow_reversal import load_stock_history

st.set_page_config(page_title="전종목 수급 레이더 · Stock Analyzer", page_icon="📡",
                   layout="wide")
require_login(st)


def server_env():
    """Read only explicitly expected secrets; never render values to the client."""
    try:
        return {
            "SUPABASE_URL": str(st.secrets.get("SUPABASE_URL", "") or "").strip(),
            "SUPABASE_SERVICE_ROLE_KEY": str(
                st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "") or "").strip(),
        }
    except Exception:
        return {}


def default_trade_date():
    local = datetime.now(ZoneInfo("Asia/Seoul"))
    selected = local.date() if local.hour >= 19 else local.date() - timedelta(days=1)
    while selected.weekday() >= 5:
        selected -= timedelta(days=1)
    return selected


@st.cache_data(ttl=600, show_spinner=False)
def latest_saved():
    return read_latest_scan(env=server_env())


@st.cache_data(ttl=1800, show_spinner=False)
def stock_history(code, day):
    return load_stock_history(code, day)


st.title("📡 전종목 수급 전환 레이더")
st.caption("KOSPI · KOSDAQ | 개인 순매수 지속 → 개인 이례적 순매도 + 외국인·기관 합산 순매수")
st.info(
    "KRX 거래일별 전 종목 수급표와 가격 자료를 교차 검증합니다. "
    "KRX가 순위 상위종목만 돌려주거나 자료가 누락되면 **검색 결과 0건이 아니라 실패**로 표시합니다. "
    "장중 신호가 아닌 마감 기준(EOD) 검색이며, 수급 전환은 매수 추천이 아닙니다."
)

env = server_env()
report = st.session_state.get("marketwide_report")
if report is None:
    try:
        report = latest_saved()
    except RuntimeError as exc:
        st.warning(str(exc))
if report is None:
    st.caption(
        "아직 저장된 전종목 검색 결과가 없습니다. 아래에서 직접 검색하거나, "
        "GitHub Actions 일정 실행과 비공개 Supabase 저장 설정을 완료하세요."
    )

with st.expander("검색 조건 및 수동 실행", expanded=report is None):
    c1, c2, c3 = st.columns(3)
    with c1:
        selected_day = st.date_input(
            "검색 기준 거래일", value=default_trade_date(),
            max_value=datetime.now(ZoneInfo("Asia/Seoul")).date())
    with c2:
        markets = st.multiselect(
            "검색 대상 시장", ["KOSPI", "KOSDAQ"],
            default=["KOSPI", "KOSDAQ"])
    with c3:
        lookback = st.selectbox(
            "개인 순매수 판단 기간", [10, 20],
            format_func=lambda x: f"직전 {x}거래일")
    d1, d2, d3 = st.columns(3)
    with d1:
        sell_multiple = st.selectbox(
            "개인 순매도 이례성(평소대비)", [1.5, 2.0, 3.0],
            index=1, format_func=lambda x: f"{x:g}배 이상")
    with d2:
        sell_share = st.selectbox(
            "개인 순매도량/일거래량", [0.03, 0.05, 0.1],
            index=1, format_func=lambda x: f"{x:.0%} 이상")
    with d3:
        turnover = st.selectbox(
            "최소 거래대금", [10, 30, 50, 100],
            index=2, format_func=lambda x: f"{x}억원 이상")
    st.caption(
        "기본 기준: 이전 기간 중 개인 순매수 거래일 60% 이상, 누적 개인 순매수 양수, "
        "당일 개인 순매도 및 외국인+기관 합계 순매수(주식 수량과 금액 모두 양수). "
        "직전 거래일 연속 흐름을 바탕으로 신규 전환과 연속 전환을 구분합니다."
    )
    if st.button("🔎 KOSPI·KOSDAQ 전종목 즉시 검색", type="primary",
                 use_container_width=True, disabled=not bool(markets)):
        p = st.progress(0, text="시장 자료 확인 시작")
        def _progress(done, total, label):
            p.progress(done / total, text=f"KRX 전 종목 확인 {done}/{total} · {label}")

        with st.status("KRX 전시장 과거 수급 및 가격 검증", expanded=True) as status:
            try:
                report = run_full_scan(
                    str(selected_day), markets=tuple(markets), lookback=lookback,
                    min_coverage=0.98, min_sell_multiple=sell_multiple,
                    min_personal_share=sell_share,
                    min_turnover=turnover * 100_000_000,
                    progress=_progress)
                st.session_state["marketwide_report"] = report
                try:
                    saved = persist_scan(
                        report, alert_sent=already_notified(report["asof"], env=env),
                        env=env)
                    if saved:
                        latest_saved.clear()
                except RuntimeError as exc:
                    st.warning("검색은 성공했으나 비공개 저장에 실패했습니다: " + str(exc))
                status.update(label="수급 전환 검색 완료", state="complete")
                st.success(
                    "수급자료 기준일 검증 완료 · 데이터 커버리지 "
                    + f"{report['coverage']['min_investor_coverage']:.1%}")
            except ScanDataError as exc:
                status.update(label="전종목 검증 중단", state="error")
                st.error("불완전한 데이터로 잘못된 신호를 만들지 않았습니다: " + str(exc))
            except Exception as exc:
                status.update(label="데이터 연결 오류", state="error")
                st.error("조회 실패: " + type(exc).__name__)
            finally:
                p.empty()

if report:
    st.divider()
    st.subheader("검색 결과 · " + report["asof"])
    freshness = (pd.Timestamp(datetime.now(ZoneInfo("Asia/Seoul")).date())
                 - pd.Timestamp(report["asof"])).days
    if freshness > 2:
        st.warning(
            f"기준일로부터 {freshness}일 경과한 저장 결과입니다. "
            "최근 거래일 데이터가 아니므로 현재 신호로 해석하지 마세요."
        )
    totals = report["totals"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("조회된 거래 종목", f"{totals['scanned_tickers']:,}개")
    m2.metric("신규 수급 전환", f"{totals['new_signals']:,}개")
    m3.metric("연속 수급 전환", f"{totals['continuations']:,}개")
    m4.metric(
        "최저 자료 커버리지",
        f"{report['coverage']['min_investor_coverage']:.1%}")

    with st.expander("데이터 검증 범위 및 기준", expanded=False):
        st.caption(
            "한국거래소 KRX 일별 종목 시세·투자자별 순매수 상위종목 페이지 기반 pykrx. "
            "일별 해당 시장에서 거래가 발생한 종목 대비 개인/외국인/기관 "
            "원천표가 포함하는 종목의 최소 비율을 검증합니다. "
            "전시장 100% 완전성·실시간성을 보장하지 않습니다."
        )
        checks = pd.DataFrame(report["coverage"]["per_day_market"])
        st.dataframe(checks, use_container_width=True, hide_index=True)

    if not report["results"]:
        st.info(
            "자료 검증은 통과했지만 이번 기준일의 선별 조건을 충족한 종목이 없습니다. "
            "조건을 변경해 재검색할 수 있습니다."
        )
    else:
        e1, e2 = st.columns([1, 2])
        with e1:
            kind = st.radio("수급 유형", ["전체", "신규 전환", "연속 전환"],
                            horizontal=True)
        with e2:
            sort_mode = st.selectbox("정렬", ["전환 강도", "개인 순매도대금",
                                          "거래량 증가"], index=0)
        items = list(report["results"])
        if kind == "신규 전환":
            items = [r for r in items if r["first_day"]]
        elif kind == "연속 전환":
            items = [r for r in items if not r["first_day"]]
        if sort_mode == "전환 강도":
            items.sort(key=lambda r: r["strength"], reverse=True)
        elif sort_mode == "개인 순매도대금":
            items.sort(key=lambda r: abs(r["personal_krw"]), reverse=True)
        else:
            items.sort(key=lambda r: r["volume_multiple"], reverse=True)

        if items:
            display = pd.DataFrame([{
                "시장": r["market"], "종목명": r["name"], "종목코드": r["code"],
                "수급 유형": r["transition"], "전환 강도": r["strength"],
                "개인 매수일": f"{r['personal_buy_days']}/{r['prior_days']}",
                "개인 순매도(억)": round(r["personal_krw"] / 1e8, 1),
                "외국인+기관 순매수(억)": round(
                    (r["foreign_krw"] + r["institution_krw"]) / 1e8, 1),
                "개인 순매도/거래량(%)": r["sell_share_pct"],
                "평소 대비(배)": r["sell_multiple"],
                "거래량(배)": r["volume_multiple"],
                "등락률(%)": r["price_change_pct"],
                "20일 평균가 대비(%)": r["ma20_gap_pct"],
            } for r in items])
            st.dataframe(display, hide_index=True, use_container_width=True,
                         height=min(670, 44 + 35 * (len(display) + 1)))
            st.download_button(
                "검색 결과 CSV 다운로드",
                data=display.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"stock_flow_reversal_{report['asof']}.csv",
                mime="text/csv")
            options = {
                f"{r['name']} · {r['code']} · {r['transition']}": r
                for r in items
            }
            choice = st.selectbox("종목별 수급 세부 확인", options=list(options))
            selected = options[choice]
            st.markdown(
                f"**{selected['name']} ({selected['code']})** — "
                f"개인 {selected['personal_qty']:+,}주, "
                f"외국인 {selected['foreign_qty']:+,}주, "
                f"기관 {selected['institution_qty']:+,}주."
            )
            st.caption(
                f"거래량 평소대비 {selected['volume_multiple']}배 · "
                f"개인 순매도 규모 {selected['sell_multiple']}배 · "
                f"거래대금 출처 {selected['turnover_source']}"
            )
            try:
                volume, values, prices = stock_history(
                    selected["code"], report["asof"])
                if volume is not None and not volume.empty:
                    chart = volume[["개인", "외국인합계", "기관합계"]].copy()
                    chart.index = pd.to_datetime(chart.index)
                    chart = chart.loc[chart.index <= pd.Timestamp(report["asof"])].tail(22)
                    figure = go.Figure()
                    for investor, color in (
                        ("개인", "#e87d31"), ("외국인합계", "#138c78"),
                        ("기관합계", "#709ac1")
                    ):
                        figure.add_bar(
                            x=chart.index, y=chart[investor],
                            name=investor, marker_color=color)
                    figure.update_layout(
                        template="plotly_white", barmode="relative",
                        title="최근 투자주체별 순매수량(주)",
                        xaxis_title="거래일", yaxis_title="순매수(주)",
                        height=360)
                    st.plotly_chart(figure, use_container_width=True)
                else:
                    st.caption("개별 수급 차트를 불러오지 못했습니다.")
            except Exception:
                st.caption("개별 수급 상세 데이터가 현재 제공되지 않습니다.")
            if st.button("선택 종목을 Stock Analyzer로 상세 분석"):
                st.session_state["query"] = selected["code"]
                st.switch_page("app.py")
        else:
            st.info("선택한 수급 유형에는 해당 종목이 없습니다.")

st.caption(
    "개인 매도 물량을 외국인·기관이 '직접 매수했다'는 체결 상대방 추적 자료는 아닙니다. "
    "동일 거래일 투자자 집단의 순매매 방향이 반대로 나타난 현상을 포착한 것입니다. "
    "100점 전환강도는 검색 결과 우선순위용 점수이지 상승 확률이 아닙니다."
)

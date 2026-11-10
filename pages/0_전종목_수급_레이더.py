"""Stock Analyzer · market-wide personal-to-foreign/institutional flow radar."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from access_gate import require_login
from approved_email_gate import require_approved_email
from app_navigation import render_navigation
from full_flow_scan import ScanDataError, run_full_scan
from flow_scan_delivery import already_notified, persist_scan, read_latest_scan
from flow_reversal import load_stock_history
from data_sources import get_kis_access_token
from kis_investor_source import KisInvestorError, fetch_kis_investor_history

st.set_page_config(page_title="전종목 수급 레이더 · Stock Analyzer", page_icon="📡",
                   layout="wide")
require_approved_email(st, "stock-analyzer", "Stock Analyzer")
require_login(st)
render_navigation(st)

from krx_auth import configure_streamlit_krx
KRX_LOGIN_READY = configure_streamlit_krx(st)


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


st.title("📡 수급 전환 레이더")
st.caption("KOSPI · KOSDAQ | 시장 전체에서 확인 가능한 종목만 판정 · 개인 대량 순매도 + 외국인·기관 합산 순매수")
if not KRX_LOGIN_READY:
    st.warning(
        "KRX 회원 로그인 설정이 없습니다. 전종목 실제 조회는 인증정보 등록 전까지 실행할 수 없습니다. "
        "Streamlit Cloud Secrets에 KRX_ID / KRX_PW를 등록하세요."
    )

st.info(
    "KRX 투자자별 순매수 **순위형 원천자료는 일부 종목을 누락할 수 있습니다.** "
    "일별 포함 비율이 90% 미만이라는 이유만으로 전체 검색을 중단하지 않습니다. "
    "직전 10/20거래일과 기준일의 개인·외국인·기관 수량·금액이 "
    "**모두 확인된 종목만** 판정하며, 미확인 종목은 0으로 채우지 않습니다. "
    "검색 결과는 전종목 완전탐색이 아니며 마감 기준(EOD)입니다."
)

env = server_env()
has_supabase = bool(env.get("SUPABASE_URL") and env.get("SUPABASE_SERVICE_ROLE_KEY"))
if not has_supabase:
    st.caption(
        "Supabase 결과 저장: 미설정(선택 기능). 수급 데이터 검색 자체와는 별개이며, "
        "DB를 연결하지 않아도 수동 검색 결과는 화면에서 확인할 수 있습니다."
    )
else:
    st.caption("Supabase 결과 저장: 연결정보 등록됨 · 테이블 존재 여부는 별도 확인 필요")

with st.expander("연결 설정 확인 · KRX / Supabase", expanded=not KRX_LOGIN_READY):
    st.write("KRX 회원 로그인 정보: " + ("등록됨 (실제 조회는 별도 확인)" if KRX_LOGIN_READY else "미등록"))
    st.write("Supabase URL/관리자 키: " + ("등록됨 (테이블은 확인 필요)" if has_supabase else "미등록"))
    st.markdown(
        "**Supabase 404 해결:** 연결된 Supabase 프로젝트의 SQL Editor에서 "
        "[flow_scan_runs 테이블 생성 SQL](https://github.com/faoshy0015-source/stock-analyzer/blob/main/sql/flow_scan_runs.sql)"
        "을 한 번 실행한 후 새로고침하세요. 다른 프로젝트에 실행하지 않도록 URL을 확인하세요."
    )
    st.caption(
        "KRX_ID/KRX_PW는 KRX 회원 계정 로그인용, "
        "SUPABASE_SERVICE_ROLE_KEY는 비공개 결과 저장용으로 역할이 다릅니다. "
        "키 값이나 비밀번호를 채팅·화면·GitHub 코드에 공유하지 마세요."
    )
report = st.session_state.get("marketwide_report")
if report is None:
    try:
        report = latest_saved()
    except RuntimeError as exc:
        st.warning(str(exc))
        if "HTTP 404" in str(exc):
            st.caption("위 오류는 자동 검색에 사용하는 KRX 연결 오류와 별개입니다. "
                       "Supabase 저장만 준비되지 않은 경우에도 수동 검색은 가능합니다.")
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
    if not KRX_LOGIN_READY:
        st.error(
            "KRX 로그인 정보가 없어 전종목 검색을 시작할 수 없습니다. "
            "Streamlit Cloud → App settings → Secrets에 KRX_ID와 KRX_PW를 등록하세요. "
            "Supabase 설정과는 별도입니다."
        )
    if st.button("🔎 KOSPI·KOSDAQ 수급 전환 검색 (미확인 종목 제외)", type="primary",
                 use_container_width=True,
                 disabled=not bool(markets) or not KRX_LOGIN_READY):
        p = st.progress(0, text="시장 자료 확인 시작")
        def _progress(done, total, label):
            p.progress(done / total, text=f"KRX 전 종목 확인 {done}/{total} · {label}")

        with st.status("KRX 전시장 과거 수급 및 가격 검증", expanded=True) as status:
            try:
                st.session_state.pop("marketwide_last_error", None)
                report = run_full_scan(
                    str(selected_day), markets=tuple(markets), lookback=lookback,
                    min_coverage=None, min_sell_multiple=sell_multiple,
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
                status.update(
                    label="확인 가능한 종목 검색 완료 · 일부 자료 미포함" if report.get("status") == "partial"
                          else "수급 전환 검색 완료",
                    state="complete")
                st.success(
                    f"수급 판정 가능한 종목 {report['totals']['eligible_tickers']:,}개 / "
                    f"기준일 거래 종목 {report['totals']['scanned_tickers']:,}개. "
                    "자료 누락 종목은 판정하지 않았습니다."
                )
            except ScanDataError as exc:
                status.update(label="전종목 검증 중단", state="error", expanded=True)
                st.session_state["marketwide_last_error"] = (
                    "KRX 데이터 검증 실패: " + str(exc)
                )
            except Exception as exc:
                status.update(label="데이터 연결 오류", state="error", expanded=True)
                st.session_state["marketwide_last_error"] = (
                    "KRX 데이터 처리 오류: " + type(exc).__name__
                    + " · 원천 데이터 연결 및 서버 로그를 확인하세요."
                )
            finally:
                p.empty()
    last_error = st.session_state.get("marketwide_last_error")
    if last_error:
        st.error(last_error)
        st.caption(
            "KRX 로그인 정보가 등록되어 있어도 인증 실패, KRX 서버 제한 또는 "
            "과거 투자자별 수급 자료 누락으로 중단될 수 있습니다. "
            "전종목 수급 결과를 임의로 0건으로 만들지 않습니다."
        )
        if "라이브러리 초기화 실패" in last_error:
            st.info(
                "현재는 시장별 수급 검증 이전에 pykrx 초기화에서 중단됩니다. "
                "아래 'KRX 연결 장애 시 대체 확인 · KIS 투자자별 일별 수급'에서 "
                "KRX와 독립된 공식 API 응답을 한 종목부터 확인할 수 있습니다."
            )

# KIS is a separate, authorized brokerage data source. This quick one-stock
# probe never calls pykrx and does not claim complete market-wide coverage.
with st.expander("KRX 연결 장애 시 대체 확인 · KIS 투자자별 일별 수급 (1종목)", expanded=False):
    st.caption(
        "한국투자증권 KIS 공식 API의 종목별 투자자매매동향(일별) 조회입니다. "
        "이 경로는 pykrx를 사용하지 않습니다. 기존 Streamlit KIS_APP_KEY, "
        "KIS_APP_SECRET을 서버에서만 읽으며, 계좌 주문은 실행하지 않습니다."
    )
    with st.form("kis_investor_probe"):
        kis_probe_code = st.text_input(
            "확인할 종목코드", value="005930", max_chars=6,
            help="삼성전자 005930 등 국내 6자리 종목코드")
        probe_submit = st.form_submit_button(
            "KIS 종목별 수급 연결 확인", use_container_width=True)
    if probe_submit:
        try:
            kis_probe_key = str(st.secrets.get("KIS_APP_KEY", "") or "").strip()
            kis_probe_secret = str(st.secrets.get("KIS_APP_SECRET", "") or "").strip()
            if not kis_probe_key or not kis_probe_secret:
                raise KisInvestorError(
                    "Streamlit Secrets의 KIS_APP_KEY·KIS_APP_SECRET 설정이 필요합니다."
                )
            with st.spinner("KIS 일별 투자주체별 수급 응답 확인 중"):
                kis_probe_token = get_kis_access_token(
                    kis_probe_key, kis_probe_secret)
                if not kis_probe_token:
                    raise KisInvestorError(
                        "KIS 접근 토큰을 발급하지 못했습니다. KIS API 인증·권한을 확인하세요."
                    )
                result_kis = fetch_kis_investor_history(
                    kis_probe_code, selected_day,
                    kis_probe_key, kis_probe_secret, kis_probe_token)
            st.session_state["kis_investor_probe"] = {
                "code": kis_probe_code, "asof": str(selected_day),
                "data": result_kis, "error": None}
        except KisInvestorError as exc:
            st.session_state["kis_investor_probe"] = {
                "code": kis_probe_code, "asof": str(selected_day),
                "data": pd.DataFrame(), "error": str(exc)}
        except Exception as exc:
            st.session_state["kis_investor_probe"] = {
                "code": kis_probe_code, "asof": str(selected_day),
                "data": pd.DataFrame(),
                "error": "예상하지 못한 연결 오류: " + type(exc).__name__}
    kis_probe = st.session_state.get("kis_investor_probe")
    if kis_probe:
        if kis_probe["error"]:
            st.warning(kis_probe["error"])
        else:
            kis_df = kis_probe["data"]
            latest = kis_df.index[-1].date().isoformat()
            st.success(
                f"KIS 별도 데이터 경로 응답 확인 · "
                f"종목 {kis_probe['code']} · {len(kis_df)}거래일 · 최신 {latest}"
            )
            if latest != kis_probe["asof"]:
                st.warning(
                    f"요청 기준일 {kis_probe['asof']}과 실제 수급 최신일 {latest}이 "
                    "다릅니다. 오래된 자료를 당일 수급 신호로 해석하지 마세요."
                )
            view = kis_df.reset_index().rename(columns={
                "index": "거래일"})
            if "거래일" not in view.columns:
                view = view.rename(columns={view.columns[0]: "거래일"})
            st.dataframe(view, hide_index=True, use_container_width=True)
            st.caption(
                "KIS 응답의 개인·외국인·기관 **일별 순매수 수량(주)**만 표시합니다. "
                "순매수 거래대금이나 전종목 커버리지는 확인하지 않았습니다. "
                "수급 전환 종목 스크리닝 및 대외 배포에 쓰려면 데이터 범위와 이용 권한을 "
                "추가로 검증해야 합니다."
            )

if report:
    st.divider()
    st.subheader("수급자료 확인 결과 · " + report["asof"])
    if report.get("status") == "partial":
        st.warning(
            "전시장 가격 종목 중 일부는 투자자별 자료가 누락됐습니다. "
            "**아래 결과는 자료를 모두 확인한 종목에 한정됩니다.** "
            "미확인 종목에도 수급 전환이 있었을 수 있습니다."
        )
    freshness = (pd.Timestamp(datetime.now(ZoneInfo("Asia/Seoul")).date())
                 - pd.Timestamp(report["asof"])).days
    if freshness > 2:
        st.warning(
            f"기준일로부터 {freshness}일 경과한 저장 결과입니다. "
            "최근 거래일 데이터가 아니므로 현재 신호로 해석하지 마세요."
        )
    totals = report["totals"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("기준일 시세 확인 종목", f"{totals['scanned_tickers']:,}개")
    m2.metric("필수 수급자료 완비 종목", f"{totals.get('eligible_tickers', 0):,}개")
    m3.metric("신규 수급 전환", f"{totals['new_signals']:,}개")
    m4.metric("연속 수급 전환", f"{totals['continuations']:,}개")
    if "eligible_ratio" in totals:
        st.caption(
            f"직전 {report['settings'].get('lookback', 10)}거래일+기준일의 동일 날짜 "
            f"수급·주가 확인 완료: {totals['eligible_ratio']:.1%} "
            f"({totals.get('eligible_tickers', 0):,}/{totals['scanned_tickers']:,}종목). "
            f"자료 미완비 제외: {totals.get('excluded_incomplete_tickers', 0):,}종목. "
            f"전체 일별 수급표 최소 커버리지: "
            f"{report['coverage']['min_investor_coverage']:.1%}."
        )
        if totals['eligible_ratio'] < 0.98:
            st.warning(
                "일부 거래 종목의 과거 수급 자료가 누락돼 검색 대상에서 제외했습니다. "
                "표시된 0건이나 검색 종목 수를 전체 시장의 확정적인 결과로 해석하면 안 됩니다."
            )

    with st.expander("데이터 검증 범위 및 기준", expanded=False):
        st.caption(
            "KRX 가격/거래량 기준일과 투자자별 순매수상위종목 자료를 교차 확인합니다. "
            "종목별 당일 및 직전 선택 기간 중 하루라도 수급 수량·금액이 "
            "누락되면 신호 계산에서 제외합니다. "
            "일별 포함 비율은 정보 공개용이며 임의의 90% 일자 기준으로 전체 검색을 중단하지 않습니다. "
            "전종목 100% 완전성·실시간성은 보장하지 않습니다."
        )
        checks = pd.DataFrame(report["coverage"]["per_day_market"])
        st.dataframe(checks, use_container_width=True, hide_index=True)

    if not report["results"]:
        st.info(
            "자료가 완비된 종목 중 이번 기준일의 선별 조건을 충족한 종목이 없습니다. "
            "미확인 종목에 대해서는 신호 발생 여부를 판단할 수 없습니다."
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

"""Market dashboard for Stock Analyzer — read-only selected-stock pulse.

Coverage: explicitly curated Korean stock basket, never all KRX listings.
Naver public quotes can be delayed; request time is not execution timestamp.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from html import escape
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
import re
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from access_gate import require_login
from app_navigation import render_navigation
from data_sources import SEED
from trading_sidebar import public_market_quote

st.set_page_config(page_title="시장 대시보드 · Stock Analyzer",
                   page_icon="📊", layout="wide")
require_login(st)
from market_calendar import render_market_calendar
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
.stock-market-brief{border:1px solid #c7e0d4;border-left:5px solid #e87d31;
 background:linear-gradient(110deg,#fffefa 0%,#eef8f2 100%);border-radius:10px;
 padding:12px 16px;margin:18px 0 17px;box-shadow:0 2px 8px rgba(21,84,72,.045)}
.stock-market-brief-title{font-size:15px;font-weight:850;color:#175447;margin-bottom:5px}
.stock-market-brief-title small{font-size:11px;font-weight:500;color:#698077;margin-left:8px}
.stock-market-brief-line{font-size:14px;color:#294b40;line-height:1.7;margin:4px 0}
.stock-market-brief-source{font-size:11px;color:#65796f;margin-top:8px}
.stock-market-newslinks{font-size:11px;color:#57776a;line-height:1.6;margin-top:5px}
.stock-market-newslinks a{color:#087965;text-decoration:underline;text-underline-offset:2px}
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



@st.cache_data(ttl=180, show_spinner=False)
def _today_market_news():
    """Fresh dated Korean market headlines. Unavailable news stays unavailable."""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    queries = (
        "코스피 외국인 when:1d",
        "코스피 엔비디아 when:1d",
        "코스피 차익실현 장중 when:1d",
        "국내 증시 미국 금리 유가 when:1d",
    )

    def read_feed(query):
        try:
            response = requests.get(
                "https://news.google.com/rss/search",
                params={"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"},
                headers={"User-Agent": "Mozilla/5.0 (compatible; StockMarketPulse/1.0)"},
                timeout=(3, 7),
            )
            response.raise_for_status()
            root = ET.fromstring(response.content[:500000])
            items = []
            for item in root.findall(".//channel/item")[:20]:
                title = (item.findtext("title") or "").strip()
                url = (item.findtext("link") or "").strip()
                src_tag = item.find("source")
                source = (src_tag.text or "").strip() if src_tag is not None else ""
                try:
                    published = parsedate_to_datetime(item.findtext("pubDate") or "")
                    published = published.astimezone(ZoneInfo("Asia/Seoul"))
                except (TypeError, ValueError, OverflowError):
                    continue
                if (not title or not url.startswith("https://")
                        or published < now - timedelta(hours=30)
                        or published > now + timedelta(minutes=10)):
                    continue
                items.append({"title": title, "source": source,
                              "url": url, "published": published})
            return items
        except (requests.RequestException, ET.ParseError, ValueError, TypeError):
            return []

    found = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(read_feed, query) for query in queries]
        for future in as_completed(futures):
            try:
                found.extend(future.result())
            except Exception:
                pass
    dedup = {}
    for item in found:
        # The same syndicated headline can appear across RSS queries.
        key = re.sub(r"\s+", "", item["title"]).lower()
        if key not in dedup or item["published"] > dedup[key]["published"]:
            dedup[key] = item
    return sorted(dedup.values(), key=lambda row: row["published"], reverse=True)


def _narrative_market_brief(frame, grouped, market_scope, headlines):
    """Three prose lines. Never attribute a motive to foreign trading without evidence."""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    todays = [row for row in headlines if row["published"].date() == now.date()]
    relevant = [row for row in todays
                if any(word in row["title"] for word in (
                    "코스피", "코스닥", "국내 증시", "국내증시", "주식시장", "한국 증시"))]
    if not relevant:
        relevant = todays

    def news_for(*terms):
        return [row for row in relevant
                if any(term in row["title"] for term in terms)]

    nvidia = news_for("엔비디아", "젠슨 황")
    rates = news_for("미국 국채", "미 국채", "국채금리", "美금리", "미국 금리")
    prices = news_for("물가", "PPI", "국제유가", "유가 상승")
    profit = news_for("차익실현", "차익 매물", "차익 매도")
    reversal = news_for("상승폭 반납", "상승분 반납", "반등 실패", "하락 전환",
                        "상승폭 축소", "오전 반등")

    evidence = []
    if nvidia:
        risk_news = any(any(term in row["title"] for term in (
            "불확실", "사임", "해임", "퇴임", "리스크", "급락", "논란")) for row in nvidia)
        evidence.append("엔비디아 관련 불확실성" if risk_news else "엔비디아 관련 이슈")
    if rates:
        risk_rates = any(any(term in row["title"] for term in (
            "상승", "급등", "경계", "부담", "고금리")) for row in rates)
        evidence.append("미국 금리 부담" if risk_rates else "미국 금리 움직임")
    if prices and len(evidence) < 2:
        evidence.append("미국 물가·유가 변수")
    if evidence:
        if len(evidence) == 1:
            first = f"오늘 보도에서는 {evidence[0]}이 국내 증시 변동성의 주요 요인으로 거론됩니다."
        else:
            first = (f"{evidence[0]}과 {evidence[1]}이 겹치면서 "
                     "국내 증시의 반등 지속 여부에 대한 경계가 이어지고 있습니다.")
    elif relevant:
        first = ("당일 시장 보도에서 뚜렷하게 교차 확인되는 단일 악재는 없으며, "
                 "지수와 주요 업종의 방향이 일치하는지 확인할 필요가 있습니다.")
    else:
        first = "오늘의 시장 뉴스를 확인하지 못해 지수 변동의 직접적인 원인을 단정하기 어렵습니다."

    # Trading-side claims require a same-day, post-opening news headline.
    # Exclude premarket forecasts, questions and yesterday's flow.
    flow_news = []
    for item in relevant:
        title = item["title"]
        if item["published"].hour < 9 or (now - item["published"]) > timedelta(hours=5):
            continue
        if any(term in title for term in ("전망", "예상", "우려", "가능성", "관건",
                                         "주시", "주목", "전날", "어제", "?", "？")):
            continue
        if not re.search(r"(외국인|외인)", title):
            continue
        if re.search(r"(외국인|외인).{0,10}(순매도|매도세|매도 우위|팔자)", title):
            flow_news.append(("sell", item))
        elif re.search(r"(외국인|외인).{0,10}(순매수|매수세|매수 우위|사자)", title):
            flow_news.append(("buy", item))
    flow_news.sort(key=lambda obj: obj[1]["published"], reverse=True)
    selected = [row for row in nvidia[:1] + rates[:1] + prices[:1]]
    if flow_news:
        signal, story = flow_news[0]
        selected.insert(0, story)
        if signal == "sell":
            if reversal and profit:
                second = ("오전 반등 뒤 상승폭을 반납하는 흐름 속에 외국인 매도 우위와 "
                          "차익실현 매물이 거론되면서 시장의 반등 탄력이 약해지고 있습니다.")
                selected.append(reversal[0])
                selected.append(profit[0])
            elif reversal:
                second = ("오전 반등 뒤 상승폭이 줄어든 가운데, 장중 보도에서 확인된 "
                          "외국인 매도 우위가 지수에 부담을 주는 모습입니다.")
                selected.append(reversal[0])
            elif profit:
                second = ("장중 외국인 매도와 차익실현 매물이 함께 거론되며 "
                          "반등 탄력을 제약하는 모습입니다.")
                selected.append(profit[0])
            else:
                second = "장중 보도에서 외국인 매도 우위가 포착돼 수급 부담이 부각되고 있습니다."
        else:
            second = ("장중 보도에서는 외국인 매수 우위가 확인돼 수급 측면의 방어력이 나타나지만, "
                      "이 흐름의 지속 여부는 지켜봐야 합니다.")
    elif profit:
        selected.append(profit[0])
        second = ("반등 과정에서 차익실현 매물에 대한 경계가 제기되지만, "
                  "외국인의 당일 순매매나 구체적인 매매 목적은 별도로 확인해야 합니다.")
    elif relevant:
        selected.append(relevant[0])
        second = ("외국인 수급과 반도체 대형주의 움직임이 반등의 지속성을 좌우할 변수로 꼽힙니다. "
                  "다만 외국인 매매 방향의 최신 확인치는 확보되지 않았습니다.")
    else:
        second = ("외국인·기관의 장중 순매매는 이 화면에서 직접 집계하지 않으므로 "
                  "매도 주체나 차익실현 여부를 추정하지 않습니다.")

    up = int((frame["등락률(%)"] > 0).sum())
    down = int((frame["등락률(%)"] < 0).sum())
    leader = grouped.iloc[0]
    laggard = grouped.iloc[-1]
    spread = "상승보다 하락 종목이 많고" if down > up else (
        "하락보다 상승 종목이 많고" if up > down else "상승과 하락 종목 수가 비슷하고")
    sample_name = "주요 종목 표본" if market_scope == "전체" else f"주요 {market_scope} 표본"
    third = (f"{sample_name}에서는 {spread}, {leader['업종']} 업종이 상대적으로 강한 반면 "
             f"{laggard['업종']} 업종은 약해 업종 간 흐름이 차별화되고 있습니다.")

    unique_links = []
    seen = set()
    for item in selected + relevant:
        if len(unique_links) >= 3:
            break
        if item["url"] in seen or item["published"].date() != now.date():
            continue
        seen.add(item["url"])
        unique_links.append(item)
    return (first, second, third), unique_links


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
        public_market_quote.clear()
        _today_market_news.clear()
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

# Narrative synthesizes fresh dated headlines with verified selected-stock prices.
# Foreign net trading and motivations are not inferred from selected-stock prices.
headlines = _today_market_news()
brief, brief_sources = _narrative_market_brief(quotes, sector, scope, headlines)
news_links = ' · '.join(
    '<a href="' + escape(item["url"], quote=True) + '" target="_blank" rel="noopener noreferrer">'
    + escape(item["source"] or "관련 기사") + '</a>'
    for item in brief_sources
)
st.markdown(
    '<div class="stock-market-brief">'
    '<div class="stock-market-brief-title">📰 국내 증시 시황 코멘트'
    '<small>새로고침 시 최신 뉴스 반영</small></div>'
    + ''.join('<div class="stock-market-brief-line">' + escape(line) + '</div>'
              for line in brief)
    + ('<div class="stock-market-newslinks">관련 기사: ' + news_links + '</div>'
       if news_links else '')
    + '<div class="stock-market-brief-source">'
    '당일 보도 제목과 네이버 금융 주요 종목 표본을 바탕으로 한 자동 해석 · '
    '실시간 투자주체별 순매매 직접 집계 아님 · 뉴스/시세 지연 가능 · 매매 목적 추정 금지'
    '</div></div>',
    unsafe_allow_html=True,
)

st.subheader("🟩 업종별 주식 모멘텀 히트맵")
st.caption(
    "조회된 주요 종목의 업종별 등락률 단순평균 · 녹색 상승 / 빨간색 하락 · "
    "타일 면적은 등락폭 반영(최소 면적 보정) · 공식 업종지수 아님"
)

selection_key = "stock_dashboard_clicked_sector"
selection_version_key = "stock_dashboard_heatmap_version"
sector_names = set(sector["업종"].astype(str))
selected_sector = st.session_state.get(selection_key)
if selected_sector not in sector_names:
    selected_sector = None
    st.session_state.pop(selection_key, None)

if selected_sector is None:
    st.markdown(
        '<div class="stock-dashboard-hint">'
        '👇 <b>업종 네모칸을 클릭하세요!</b> '
        '클릭한 업종의 <b>종목 등락률 TOP 5</b>를 보여드립니다.'
        '</div>',
        unsafe_allow_html=True,
    )
    # Plotly's default treemap click only zooms one large tile.
    # Instead, use Streamlit's hierarchical chart click event to render
    # a separately controlled rank view. Never rely on Plotly's zoom state.
    fig = go.Figure(go.Treemap(
        ids=["industry/" + str(name) for name in sector["업종"]],
        labels=sector["업종"].tolist(),
        parents=[""] * len(sector),
        values=(sector["평균등락률"].abs() + .35).tolist(),
        text=[f"{name} ▶<br>{float(pct):+.2f}%"
              for name, pct in zip(sector["업종"], sector["평균등락률"])],
        textinfo="text",
        textfont=dict(color="white", size=16),
        customdata=sector[["평균등락률", "종목수"]].to_numpy(),
        hovertemplate="%{label}<br>평균 등락률 %{customdata[0]:+.2f}%"
                      "<br>확인된 종목 %{customdata[1]}개"
                      "<br>클릭: 종목 등락률 TOP 5<extra></extra>",
        marker=dict(colors=[_tile_color(x) for x in sector["평균등락률"]],
                    line=dict(color="#f4f8f7", width=3)),
        tiling=dict(packing="squarify", pad=3),
        pathbar=dict(visible=False),
        maxdepth=1,
        sort=False,
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=1, b=0), height=405,
        paper_bgcolor="rgba(0,0,0,0)",
    )
    selection = st.plotly_chart(
        fig, use_container_width=True,
        config={"displayModeBar": False},
        key=f"stock_sector_heatmap_{scope}_{st.session_state.get(selection_version_key, 0)}",
        on_select="rerun",
        selection_mode="points",
    )
    try:
        points = selection["selection"]["points"]
    except (TypeError, KeyError, AttributeError):
        points = []
    if points:
        hit = points[0]
        hit_id = str(hit.get("id") or "")
        hit_label = str(hit.get("label") or "")
        clicked_sector = (hit_id[len("industry/"):]
                          if hit_id.startswith("industry/") else hit_label)
        if clicked_sector in sector_names:
            st.session_state[selection_key] = clicked_sector
            st.session_state["stock_dashboard_sector"] = clicked_sector
            st.rerun()
else:
    title, back = st.columns([4, 1], vertical_alignment="center")
    with title:
        avg = float(sector.loc[
            sector["업종"] == selected_sector, "평균등락률"
        ].iloc[0])
        st.markdown(f"#### 🔎 {escape(selected_sector)} · 종목 등락률 TOP 5")
        st.caption(f"업종 표본 평균 {avg:+.2f}% · 조회된 종목 중 등락률 높은 순")
    with back:
        if st.button("← 전체 업종으로", use_container_width=True,
                     key="stock_heatmap_back"):
            st.session_state.pop(selection_key, None)
            st.session_state[selection_version_key] = (
                st.session_state.get(selection_version_key, 0) + 1
            )
            st.rerun()

    leaders = (quotes.loc[quotes["업종"] == selected_sector]
               .sort_values("등락률(%)", ascending=False).head(5))
    if leaders.empty:
        st.warning("선택 업종에서 확인된 종목 시세가 없습니다.")
    else:
        # Streamlit buttons provide a reliable direct route to Analyze.
        # Display a maximum of three cards per row for mobile readability.
        for offset in range(0, len(leaders), 3):
            group = leaders.iloc[offset:offset + 3]
            columns = st.columns(3, gap="small")
            for i, (_, item) in enumerate(group.iterrows(), start=offset + 1):
                name = str(item["종목명"])
                code = str(item["종목코드"])
                price = int(item["현재가(원)"])
                pct = float(item["등락률(%)"])
                color = _tile_color(pct)
                with columns[(i - 1) % 3]:
                    st.markdown(
                        '<div style="background:' + color + ';color:white;'
                        'padding:13px;border-radius:9px;height:143px;'
                        'display:flex;flex-direction:column;justify-content:space-between;'
                        'box-sizing:border-box;">'
                        '<div style="font-size:12px;opacity:.90;">'
                        + str(i) + '위 · ' + escape(code) + '</div>'
                        '<div style="font-size:17px;font-weight:750;line-height:1.3;">'
                        + escape(name) + '</div>'
                        '<div style="font-size:20px;font-weight:800;">'
                        + f"{pct:+.2f}%" + '</div></div>',
                        unsafe_allow_html=True,
                    )
                    st.caption(f"현재가 {price:,}원 · 지연 시세 가능")
                    if st.button(
                        "🔎 Analyze 상세 분석",
                        key=f"stock_sector_analyze_{code}",
                        use_container_width=True,
                    ):
                        _go_analyze(code)
        st.caption(
            "상위 종목은 30개 주요 종목 표본에서 해당 업종으로 분류된 "
            "조회 성공 종목만 비교한 결과입니다. 전종목 순위가 아닙니다."
        )

st.markdown('<div class="stock-dashboard-hint">🔎 관심 업종을 선택해 '
            '종목별 등락률을 비교하거나, 아래 종목의 <b>분석</b> 버튼으로 '
            '기존 Analyze 화면에 바로 이동하세요.</div>',
            unsafe_allow_html=True)
chosen_sector = st.selectbox(
    "업종 선택 · 관련 종목 확인", sector["업종"].tolist(),
    key="stock_dashboard_sector"
)
if st.button(
    "📊 선택 업종의 종목 TOP 5 카드 보기",
    key="stock_dashboard_sector_open",
    use_container_width=True,
):
    st.session_state[selection_key] = chosen_sector
    st.rerun()

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
# Market-wide calendar is independent of the selected stock's analysis view.
render_market_calendar(
    selected_code=str(selected_code),
    selected_name=str(BASKET.get(selected_code, {}).get("종목명", "")),
)

st.caption("CREATED BY K.H.AHN · 시장 대시보드는 투자 참고용이며, "
           "개별 종목 분석과 매매 판단은 별도로 검토해야 합니다.")

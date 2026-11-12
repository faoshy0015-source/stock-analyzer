"""Korean and US macro/earnings calendar migrated from HanaV Trading.

Sources: Nasdaq public earnings/economic calendars, Bullstory public calendar
and Google News RSS. Forecast or news-derived dates are estimates, never
officially confirmed earnings announcements unless corroborated independently.
This module makes network calls only when the dashboard renders the calendar.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

@st.cache_data(ttl=600, show_spinner=False)
def hanav_google_news(query, limit=8):
    """Google News RSS 최신 기사. OpenAI API를 사용하지 않는다."""
    from urllib.parse import quote_plus
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(str(query))
        + "&hl=ko&gl=KR&ceid=KR:ko"
    )
    headers={"User-Agent":"Mozilla/5.0"}
    r=requests.get(url,headers=headers,timeout=12)
    r.raise_for_status()
    root=ET.fromstring(r.content)
    out=[]
    for item in root.findall(".//item")[:int(limit)]:
        title=html.unescape((item.findtext("title") or "").strip())
        link=(item.findtext("link") or "").strip()
        pub=(item.findtext("pubDate") or "").strip()
        source_el=item.find("source")
        source=(source_el.text or "").strip() if source_el is not None else ""
        if title:
            out.append({"title":title,"link":link,"pubDate":pub,"source":source})
    return out

# 시장 일정 캘린더 · Nasdaq 공개 캘린더 (API KEY 불필요)
# - 기업 실적: /api/calendar/earnings
# - 주요 매크로: /api/calendar/economicevents
# ==================================================
_HANAV_KST = timezone(timedelta(hours=9))
_NASDAQ_CAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nasdaq.com/market-activity/",
    "Origin": "https://www.nasdaq.com",
}

def hanav_nasdaq_calendar(kind, date_iso):
    kind = str(kind).strip().lower()
    if kind not in {"earnings", "economicevents"}:
        return []
    url = f"https://api.nasdaq.com/api/calendar/{kind}?date={date_iso}"
    r = requests.get(url, headers=_NASDAQ_CAL_HEADERS, timeout=10)
    r.raise_for_status()
    payload = r.json() or {}
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return []
    rows = data.get("rows") or []
    return rows if isinstance(rows, list) else []


def _hanav_marketcap_num(v):
    try:
        s = re.sub(r"[^0-9.\-]", "", str(v or ""))
        return float(s) if s else 0.0
    except Exception:
        return 0.0


def _hanav_earnings_time_label(v):
    s = str(v or "").strip().lower()
    if "pre" in s:
        return "장전"
    if "after" in s or "post" in s:
        return "장후"
    return "미정"


def _hanav_day_label(date_iso):
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
        ko = ["월", "화", "수", "목", "금", "토", "일"][d.weekday()]
        return f"{d.month}/{d.day}({ko})"
    except Exception:
        return str(date_iso)


def _hanav_macro_importance(v):
    s = str(v or "").strip().lower()
    try:
        n = int(float(s))
        if n >= 3:
            return "★★★", 3
        if n == 2:
            return "★★", 2
        if n == 1:
            return "★", 1
    except Exception:
        pass
    if "high" in s:
        return "★★★", 3
    if "medium" in s or "moderate" in s:
        return "★★", 2
    if "low" in s:
        return "★", 1
    return "", 0


def _hanav_major_macro(row):
    country = str(row.get("country", "") or "").upper().replace("_", " ").strip()
    if country and not (
        "UNITED STATES" in country
        or country in {"US", "USA", "U.S.", "UNITED STATES OF AMERICA"}
    ):
        return False

    name = str(row.get("eventName", "") or row.get("event", "") or "").strip()
    if not name:
        return False

    _, level = _hanav_macro_importance(row.get("importance", ""))
    major_keywords = [
        "cpi", "consumer price", "pce", "personal consumption", "ppi", "producer price",
        "nonfarm", "payroll", "employment", "unemployment", "jobless", "jolts",
        "fomc", "federal reserve", "fed chair", "fed interest", "interest rate",
        "gdp", "retail sales", "ism", "pmi", "durable goods", "consumer confidence",
        "michigan", "industrial production", "housing starts", "existing home", "new home",
        "trade balance", "beige book",
    ]
    low = name.lower()
    return level >= 2 or any(k in low for k in major_keywords)


@st.cache_data(ttl=1800, show_spinner=False)
def hanav_calendar_window(start_iso, days):
    start = datetime.strptime(start_iso, "%Y-%m-%d").date()
    date_isos = [(start + timedelta(days=i)).isoformat() for i in range(int(days))]

    earnings_by_date = {}
    macro_by_date = {}
    errors = []

    jobs = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for ds in date_isos:
            jobs.append(("earnings", ds, ex.submit(hanav_nasdaq_calendar, "earnings", ds)))
            jobs.append(("economicevents", ds, ex.submit(hanav_nasdaq_calendar, "economicevents", ds)))
        for kind, ds, fut in jobs:
            try:
                rows = fut.result()
                if kind == "earnings":
                    earnings_by_date[ds] = rows
                else:
                    macro_by_date[ds] = rows
            except Exception as e:
                errors.append(f"{ds} {kind}: {e}")
                if kind == "earnings":
                    earnings_by_date[ds] = []
                else:
                    macro_by_date[ds] = []

    earnings_rows = []
    for ds in date_isos:
        day_rows = list(earnings_by_date.get(ds, []))
        day_rows.sort(key=lambda x: _hanav_marketcap_num(x.get("marketCap")), reverse=True)
        # 종목 수가 많은 날에도 화면을 과도하게 차지하지 않도록 시총 상위 8개만 표시
        for row in day_rows[:8]:
            earnings_rows.append({
                "날짜": _hanav_day_label(ds),
                "시각": _hanav_earnings_time_label(row.get("time")),
                "티커": str(row.get("symbol", "") or ""),
                "기업": str(row.get("name", "") or ""),
                "EPS 예상": str(row.get("epsForecast", "") or "-"),
                "시가총액": str(row.get("marketCap", "") or "-"),
            })

    macro_rows = []
    for ds in date_isos:
        for row in macro_by_date.get(ds, []):
            if not _hanav_major_macro(row):
                continue
            imp, level = _hanav_macro_importance(row.get("importance", ""))
            macro_rows.append({
                "날짜": _hanav_day_label(ds),
                "미국 현지": str(row.get("time", "") or "-"),
                "중요도": imp or "주요",
                "지표": str(row.get("eventName", "") or row.get("event", "") or ""),
                "예상": str(row.get("consensus", "") or row.get("forecast", "") or "-"),
                "이전": str(row.get("previous", "") or "-"),
                "실제": str(row.get("actual", "") or "-"),
                "_level": level,
                "_date_iso": ds,
            })

    macro_rows.sort(key=lambda x: (x.get("_date_iso", ""), -x.get("_level", 0), x.get("미국 현지", "")))
    for row in macro_rows:
        row.pop("_level", None)
        row.pop("_date_iso", None)

    return earnings_rows, macro_rows, errors


# ==================================================
# 국내 주요 일정 · Bullstory 공개 캘린더 (API KEY 불필요)
# - 국내 기업 실적: KIND 등 공식 공시 기반 + 과거 발표주기 예상기간
# - 국내 매크로: 한국은행·통계청 등 공식 발표일정 취합
# - 예상기간은 확정 일정이 아니므로 UI에 '예상'으로 명확히 구분
# ==================================================
_BULLSTORY_CAL_URL = "https://bullstory.io/calendar"
_BULLSTORY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://bullstory.io/",
}

# 국내 시장에 미치는 영향이 큰 대표 종목 우선순위.
# 현재 선택 종목은 별도로 최우선 포함한다.
_HANAV_KR_MAJOR_EARNINGS = [
    ("005930", "삼성전자"), ("000660", "SK하이닉스"),
    ("373220", "LG에너지솔루션"), ("006400", "삼성SDI"),
    ("005380", "현대차"), ("000270", "기아"), ("012330", "현대모비스"),
    ("035420", "네이버"), ("035720", "카카오"),
    ("105560", "KB금융"), ("055550", "신한지주"), ("086790", "하나금융지주"),
    ("329180", "HD현대중공업"), ("042660", "한화오션"), ("010140", "삼성중공업"),
    ("012450", "한화에어로스페이스"), ("079550", "LIG넥스원"), ("064350", "현대로템"),
    ("267260", "HD현대일렉트릭"), ("298040", "효성중공업"),
    ("277810", "레인보우로보틱스"), ("454910", "두산로보틱스"),
    ("003490", "대한항공"), ("051910", "LG화학"), ("066570", "LG전자"),
    ("000810", "삼성화재"), ("032830", "삼성생명"), ("016360", "삼성증권"),
    ("028260", "삼성물산"), ("034020", "두산에너빌리티"),
]

# 화면 표기는 짧게, 검색은 여러 별칭으로 허용한다.
_HANAV_KR_MACRO = [
    ("한국은행 기준금리", ["한국은행 기준금리", "기준금리"], "★★★"),
    ("소비자물가", ["소비자물가"], "★★★"),
    ("GDP", ["GDP", "실질 국내총생산", "국내총생산"], "★★★"),
    ("고용동향", ["고용동향", "고용"], "★★"),
    ("경상수지", ["경상수지", "국제수지"], "★★"),
    ("산업활동동향", ["산업활동동향", "산업활동"], "★★"),
    ("생산자물가", ["생산자물가"], "★★"),
    ("수출입물가", ["수출입물가"], "★★"),
    ("소비자심리지수", ["소비자심리지수", "소비심리"], "★★"),
    ("기업경기실사지수", ["기업경기실사지수", "기업경기"], "★"),
    ("통화량", ["통화량"], "★"),
    ("은행 예금·대출 금리", ["은행 예금과 대출 금리", "예금과 대출 금리"], "★"),
]


def _hanav_html_to_text(raw):
    raw = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", str(raw or ""))
    raw = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


@st.cache_data(ttl=1800, show_spinner=False)
def hanav_korea_calendar_source():
    r = requests.get(_BULLSTORY_CAL_URL, headers=_BULLSTORY_HEADERS, timeout=12)
    r.raise_for_status()
    return _hanav_html_to_text(r.text)


def _hanav_ko_date(y, m, d):
    try:
        return datetime(int(y), int(m), int(d)).date()
    except Exception:
        return None


def _hanav_range_label(a, b):
    if not a or not b:
        return "-"
    if a == b:
        return _hanav_day_label(a.isoformat())
    if a.year == b.year:
        return f"{a.month}/{a.day}~{b.month}/{b.day}"
    return f"{a.year}.{a.month}.{a.day}~{b.year}.{b.month}.{b.day}"


def _hanav_overlaps(a, b, start, end):
    return bool(a and b and a <= end and b >= start)


# 국내 주요 기업의 "잠정실적/실적 발표 예정" 뉴스 보완 레이어
# Bullstory는 정식 실적의 예상 기간 중심이라 삼성전자처럼 분기 초 잠정실적 발표가 빠질 수 있다.
# Google News RSS에서 최근 기사 제목을 확인해, 날짜가 명시된 발표 예정 기사와 당일 실제 발표 기사를 보완한다.
_HANAV_KR_EARN_NEWS_NAMES = [
    ("005930", "삼성전자"), ("000660", "SK하이닉스"),
    ("373220", "LG에너지솔루션"), ("006400", "삼성SDI"),
    ("005380", "현대차"), ("000270", "기아"),
    ("035420", "네이버"), ("035720", "카카오"),
    ("105560", "KB금융"), ("055550", "신한지주"), ("086790", "하나금융지주"),
    ("329180", "HD현대중공업"), ("042660", "한화오션"), ("010140", "삼성중공업"),
    ("012450", "한화에어로스페이스"), ("079550", "LIG넥스원"),
    ("267260", "HD현대일렉트릭"), ("298040", "효성중공업"),
    ("277810", "레인보우로보틱스"), ("454910", "두산로보틱스"),
    ("051910", "LG화학"), ("066570", "LG전자"),
]


def _hanav_parse_rss_pubdate(pub):
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(str(pub or ""))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_HANAV_KST)
    except Exception:
        return None


def _hanav_day_from_title(title, pub_day):
    """기사 제목에서 실적 이벤트 날짜를 추정한다. 명시적 날짜가 없으면 None."""
    t = re.sub(r"\s+", " ", str(title or "")).strip()
    if not t or not pub_day:
        return None

    # YYYY년 M월 D일
    m = re.search(r"(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일", t)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except Exception:
            pass

    # M월 D일
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", t)
    if m:
        try:
            y = pub_day.year
            cand = datetime(y, int(m.group(1)), int(m.group(2))).date()
            if (cand - pub_day).days < -180:
                cand = datetime(y + 1, int(m.group(1)), int(m.group(2))).date()
            elif (cand - pub_day).days > 180:
                cand = datetime(y - 1, int(m.group(1)), int(m.group(2))).date()
            return cand
        except Exception:
            pass

    if "오늘" in t or "금일" in t:
        return pub_day
    if "내일" in t:
        return pub_day + timedelta(days=1)

    # '8일 실적발표', '실적 발표하는 8일'처럼 일자만 명시된 제목
    patterns = [
        r"(\d{1,2})일[^,·]{0,18}(?:잠정\s*)?실적[^,·]{0,10}발표",
        r"(?:잠정\s*)?실적[^,·]{0,18}발표[^,·]{0,12}(\d{1,2})일",
        r"발표(?:하는|예정인|예정)?\s*(\d{1,2})일",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if not m:
            continue
        try:
            day = int(m.group(1))
            candidates = []
            for delta_m in (-1, 0, 1):
                yy, mm = pub_day.year, pub_day.month + delta_m
                if mm < 1:
                    yy -= 1
                    mm += 12
                if mm > 12:
                    yy += 1
                    mm -= 12
                try:
                    candidates.append(datetime(yy, mm, day).date())
                except Exception:
                    pass
            if candidates:
                return min(candidates, key=lambda d: abs((d - pub_day).days))
        except Exception:
            pass
    return None


def _hanav_news_event_kind(title, event_day, pub_day):
    t = str(title or "")
    if "잠정실적" in t or "잠정 실적" in t:
        if any(k in t for k in ["예정", "앞두", "오는", "오늘"]):
            return "잠정예정"
        return "잠정"
    if any(k in t for k in ["예정", "앞두", "오는"]):
        return "예정"
    if event_day and pub_day and event_day > pub_day:
        return "예정"
    return "발표"


@st.cache_data(ttl=900, show_spinner=False)
def hanav_korea_news_earnings_window(start_iso, days, selected_code="", selected_name=""):
    start = datetime.strptime(start_iso, "%Y-%m-%d").date()
    end = start + timedelta(days=max(int(days), 1) - 1)

    companies = list(_HANAV_KR_EARN_NEWS_NAMES)
    sn = str(selected_name or "").strip()
    sc = str(selected_code or "").strip()
    if sn and all(name != sn for _, name in companies):
        companies.insert(0, (sc, sn))

    code_by_name = {name: code for code, name in companies}
    names = [name for _, name in companies]
    # 검색어가 너무 길어지지 않도록 2개 묶음으로 나눠 RSS 요청
    batches = [names[i:i+11] for i in range(0, len(names), 11)]
    items = []
    errors = []

    # 현재 선택 종목은 별도 검색해 누락 가능성을 최소화한다.
    if sn:
        try:
            items.extend(hanav_google_news(
                f'"{sn}" (실적 OR 잠정실적 OR 영업이익) (발표 OR 예정) when:30d', 20
            ))
        except Exception as e:
            errors.append(f"선택종목 실적 뉴스: {e}")

    for batch in batches:
        or_part = " OR ".join(f'"{n}"' for n in batch)
        query = f'({or_part}) (실적 OR 잠정실적) (발표 OR 예정) when:30d'
        try:
            items.extend(hanav_google_news(query, 60))
        except Exception as e:
            errors.append(f"국내 실적 뉴스: {e}")

    out = []
    seen = set()
    for item in items:
        title = str(item.get("title") or "")
        pub_dt = _hanav_parse_rss_pubdate(item.get("pubDate"))
        if not pub_dt:
            continue
        pub_day = pub_dt.date()
        matched = None
        for name in names:
            if name and name.lower() in title.lower():
                matched = name
                break
        if not matched:
            continue
        if not any(k in title for k in ["실적", "영업이익", "매출", "어닝"]):
            continue

        event_day = _hanav_day_from_title(title, pub_day)
        if event_day is None:
            # 실제 발표 기사(발표/잠정실적)는 기사 발행일을 발표일로 본다.
            # 전망·예상 기사인데 날짜가 없는 경우는 일정으로 만들지 않는다.
            if ("발표" in title or "잠정실적" in title or "잠정 실적" in title) and not any(k in title for k in ["전망", "예상", "추정"]):
                event_day = pub_day
            else:
                continue
        if not (start <= event_day <= end):
            continue

        kind = _hanav_news_event_kind(title, event_day, pub_day)
        key = (matched, event_day.isoformat())
        if key in seen:
            continue
        seen.add(key)
        source = str(item.get("source") or "뉴스")
        out.append({
            "시장": "🇰🇷",
            "날짜/기간": _hanav_day_label(event_day.isoformat()),
            "구분": kind,
            "코드": code_by_name.get(matched, "-") or "-",
            "기업": matched,
            "참고": source[:24],
            "_date": event_day.isoformat(),
            "_priority": 0 if kind in {"잠정", "발표"} else 1,
        })

    out.sort(key=lambda x: (
        x.get("_date", ""),
        x.get("_priority", 9),
        names.index(x.get("기업")) if x.get("기업") in names else 999,
    ))
    for r in out:
        r.pop("_date", None)
        r.pop("_priority", None)
    return out[:12], errors


@st.cache_data(ttl=1800, show_spinner=False)
def hanav_korea_calendar_window(start_iso, days, selected_code="", selected_name=""):
    start = datetime.strptime(start_iso, "%Y-%m-%d").date()
    end = start + timedelta(days=max(int(days), 1) - 1)
    errors = []
    try:
        text = hanav_korea_calendar_source()
    except Exception as e:
        # 국내 뉴스 기반 실적 보완은 Bullstory 연결 실패와 무관하게 계속 작동하도록 한다.
        text = ""
        errors.append(f"국내 캘린더 원본: {e}")

    try:
        news_earn, news_errors = hanav_korea_news_earnings_window(
            start_iso, days, selected_code, selected_name
        )
        errors.extend(news_errors)
    except Exception as e:
        news_earn = []
        errors.append(f"국내 실적 뉴스 보완: {e}")

    # 현재 선택 종목을 가장 먼저 보고, 이후 주요 대형주/시장민감주를 확인한다.
    companies = []
    seen = set()
    if str(selected_name or "").strip():
        companies.append((str(selected_code or "").strip(), str(selected_name).strip()))
        seen.add(str(selected_name).strip().lower())
    for code, name in _HANAV_KR_MAJOR_EARNINGS:
        if name.lower() not in seen:
            companies.append((code, name))
            seen.add(name.lower())

    kr_earn = []
    for priority, (code, name) in enumerate(companies):
        # Bullstory 표기: "회사명 예상 기간 2026년 10월 3일부터 2026년 10월 17일 사이로 예상됩니다."
        pat = (
            rf"{re.escape(name)}\s*예상\s*기간\s*"
            rf"(20\d{{2}})년\s*(\d{{1,2}})월\s*(\d{{1,2}})일부터\s*"
            rf"(20\d{{2}})년\s*(\d{{1,2}})월\s*(\d{{1,2}})일\s*사이로\s*예상됩니다"
        )
        m = re.search(pat, text, flags=re.I)
        if not m:
            # 문구가 약간 달라질 경우를 위한 느슨한 패턴
            pat2 = (
                rf"{re.escape(name)}[^0-9]{{0,30}}"
                rf"(20\d{{2}})년\s*(\d{{1,2}})월\s*(\d{{1,2}})일부터\s*"
                rf"(20\d{{2}})년\s*(\d{{1,2}})월\s*(\d{{1,2}})일"
            )
            m = re.search(pat2, text, flags=re.I)
        if not m:
            continue
        a = _hanav_ko_date(m.group(1), m.group(2), m.group(3))
        b = _hanav_ko_date(m.group(4), m.group(5), m.group(6))
        if not _hanav_overlaps(a, b, start, end):
            continue
        kr_earn.append({
            "시장": "🇰🇷",
            "날짜/기간": _hanav_range_label(a, b),
            "구분": "정식예상",
            "코드": code or "-",
            "기업": name,
            "참고": "공개 일정 참고(예상)",
            "_sort": a.isoformat() if a else "9999-12-31",
            "_priority": priority,
        })

    # 뉴스에서 확인된 잠정실적/확정·예정 발표를 먼저 반영한다.
    # 같은 기업의 Bullstory 정식예상 기간이 겹치더라도 잠정실적과 정식실적은 다른 이벤트라 함께 둘 수 있다.
    kr_earn.sort(key=lambda x: (x.get("_sort", ""), x.get("_priority", 999)))
    for r in kr_earn:
        r.pop("_sort", None)
        r.pop("_priority", None)
    kr_earn = list(news_earn) + kr_earn

    # 완전 중복 제거 후 최대 12개 표시
    _dedup = []
    _seen_rows = set()
    for r in kr_earn:
        k = (r.get("기업"), r.get("날짜/기간"), r.get("구분"))
        if k in _seen_rows:
            continue
        _seen_rows.add(k)
        _dedup.append(r)
    kr_earn = _dedup[:12]

    # 한국 거시 일정은 이름 뒤에 붙는 YYYY년 M월 D일 HH:MM 패턴을 읽는다.
    kr_macro = []
    used = set()
    for display, aliases, stars in _HANAV_KR_MACRO:
        found = None
        for alias in aliases:
            p = (
                rf"{re.escape(alias)}\s*"
                rf"(20\d{{2}})년\s*(\d{{1,2}})월\s*(\d{{1,2}})일"
                rf"(?:\s*(\d{{1,2}}:\d{{2}}))?"
            )
            m = re.search(p, text, flags=re.I)
            if m:
                found = m
                break
        if not found:
            continue
        d = _hanav_ko_date(found.group(1), found.group(2), found.group(3))
        if not d or not (start <= d <= end):
            continue
        key = (display, d.isoformat())
        if key in used:
            continue
        used.add(key)
        kr_macro.append({
            "시장": "🇰🇷",
            "날짜": _hanav_day_label(d.isoformat()),
            "시각": f"{found.group(4)} KST" if found.group(4) else "KST",
            "중요도": stars,
            "지표": display,
            "예상": "-",
            "이전": "-",
            "실제": "-",
            "_date": d.isoformat(),
            "_level": len(stars),
        })

    kr_macro.sort(key=lambda x: (x.get("_date", ""), -x.get("_level", 0), x.get("시각", "")))
    for r in kr_macro:
        r.pop("_date", None)
        r.pop("_level", None)

    return kr_earn, kr_macro, errors


def render_market_calendar(selected_code="", selected_name=""):
    """Main-column calendar section at the bottom of Stock Analyzer dashboard."""
    st.divider()
    st.markdown(
        '<div style="background:linear-gradient(90deg,#185F6B,#458998);'
        'border-radius:8px;color:white;padding:13px 17px;'
        'font-size:20px;font-weight:800;margin:6px 0 15px;">'
        '📅 주요 일정 캘린더 · 한국 + 미국</div>',
        unsafe_allow_html=True,
    )
    d1, d2, d3 = st.columns([1.05, 0.75, 0.7], vertical_alignment="bottom")
    with d1:
        start_day = st.date_input(
            "기준일", value=datetime.now(_HANAV_KST).date(),
            key="analyzer_calendar_start", format="YYYY-MM-DD",
        )
    with d2:
        days = st.selectbox(
            "표시 기간", [3, 5, 7, 14], index=2,
            format_func=lambda x: f"향후 {x}일",
            key="analyzer_calendar_days",
        )
    with d3:
        if st.button(
            "🔄 일정 새로고침", use_container_width=True,
            key="analyzer_calendar_refresh",
        ):
            hanav_calendar_window.clear()
            hanav_korea_calendar_source.clear()
            hanav_google_news.clear()
            hanav_korea_news_earnings_window.clear()
            hanav_korea_calendar_window.clear()
            st.rerun()

    all_errors = []
    try:
        with st.spinner("미국 기업실적·경제지표 일정 조회 중..."):
            us_earn, us_macro, errors = hanav_calendar_window(
                start_day.isoformat(), int(days)
            )
        all_errors.extend(errors)
    except Exception as exc:
        us_earn, us_macro = [], []
        all_errors.append("미국 일정 조회 실패 (" + type(exc).__name__ + ")")

    try:
        with st.spinner("국내 기업실적·경제지표 일정 조회 중..."):
            kr_earn, kr_macro, errors = hanav_korea_calendar_window(
                start_day.isoformat(), int(days),
                str(selected_code or ""), str(selected_name or ""),
            )
        all_errors.extend(errors)
    except Exception as exc:
        kr_earn, kr_macro = [], []
        all_errors.append("국내 일정 조회 실패 (" + type(exc).__name__ + ")")

    combined_earn = list(kr_earn)
    for row in us_earn:
        eps_forecast = row.get("EPS 예상")
        combined_earn.append({
            "시장": "🇺🇸",
            "날짜/기간": row.get("날짜", "-"),
            "구분": row.get("시각", "미정"),
            "코드": row.get("티커", "-"),
            "기업": row.get("기업", "-"),
            "참고": ("EPS " + str(eps_forecast))
                       if eps_forecast not in (None, "", "-") else "-",
        })

    combined_macro = list(kr_macro)
    for row in us_macro:
        us_time = str(row.get("미국 현지") or "-")
        combined_macro.append({
            "시장": "🇺🇸",
            "날짜": row.get("날짜", "-"),
            "시각": us_time + " ET" if us_time != "-" else "시각 미확인",
            "중요도": row.get("중요도", "주요"),
            "지표": row.get("지표", "-"),
            "예상": row.get("예상", "-"),
            "이전": row.get("이전", "-"),
            "실제": row.get("실제", "-"),
        })

    left, right = st.columns([1.28, 1.0], gap="large")
    with left:
        st.markdown("**🏢 주요 기업 실적 발표**")
        st.caption("🇰🇷 국내 잠정·발표 예정 및 추정 기간 · 🇺🇸 미국 주요 기업 실적")
        if combined_earn:
            frame = pd.DataFrame(combined_earn)
            st.dataframe(
                frame, use_container_width=True, hide_index=True,
                height=min(430, 38 + 35 * min(len(frame), 11)),
                column_config={
                    "시장": st.column_config.TextColumn("시장", width="small"),
                    "날짜/기간": st.column_config.TextColumn("날짜/기간", width="medium"),
                    "구분": st.column_config.TextColumn("구분", width="small"),
                    "코드": st.column_config.TextColumn("코드", width="small"),
                    "기업": st.column_config.TextColumn("기업", width="large"),
                    "참고": st.column_config.TextColumn("참고", width="medium"),
                },
            )
        else:
            st.info("해당 기간의 실적 발표 일정을 확인하지 못했습니다.")

    with right:
        st.markdown("**🌐 주요 매크로 발표**")
        st.caption("🇰🇷 한국은행·통계청 지표 · 🇺🇸 CPI·PCE·고용·FOMC·GDP·ISM 등")
        if combined_macro:
            frame = pd.DataFrame(combined_macro)
            st.dataframe(
                frame, use_container_width=True, hide_index=True,
                height=min(430, 38 + 35 * min(len(frame), 11)),
                column_config={
                    "시장": st.column_config.TextColumn("시장", width="small"),
                    "날짜": st.column_config.TextColumn("날짜", width="small"),
                    "시각": st.column_config.TextColumn("시각", width="small"),
                    "중요도": st.column_config.TextColumn("중요도", width="small"),
                    "지표": st.column_config.TextColumn("지표", width="large"),
                    "예상": st.column_config.TextColumn("예상", width="small"),
                    "이전": st.column_config.TextColumn("이전", width="small"),
                    "실제": st.column_config.TextColumn("실제", width="small"),
                },
            )
        else:
            st.info("해당 기간의 주요 경제지표 일정을 확인하지 못했습니다.")

    st.caption(
        "출처: 미국 실적·경제지표 Nasdaq Calendar, 국내 공개 일정 Bullstory 및 "
        "최근 Google News RSS. 한국 지표는 KST, 미국 지표는 ET 표기이며 "
        "서머타임에 따라 시차가 달라집니다. 국내 정식실적 예상기간과 "
        "뉴스 기반 발표 날짜는 공식 확정 일정이 아닐 수 있습니다. "
        "실제 발표 전에는 기업 IR·공시 및 공식 통계 발표처에서 재확인하세요."
    )
    if all_errors:
        with st.expander("일정 데이터 연결 상태 · 일부 출처 미확인", expanded=False):
            st.caption("일부 일정 데이터가 수신되지 않았습니다. 조회되는 결과만 표시합니다.")
            for error in all_errors[:8]:
                st.text(str(error)[:220])


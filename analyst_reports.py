"""Broker research report discovery: metadata and public original links only.

No PDF content is downloaded or republished. If a source changes its HTML or
blocks automated access, callers receive an empty list and source navigation
links rather than fabricated reports.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

HANKYUNG_LEGACY = "https://consensus.hankyung.com/analysis/list"
HANKYUNG_PORTAL = "https://markets.hankyung.com/consensus"
NAVER_RESEARCH = "https://stock.naver.com/research/company"
NAVER_ITEM_RESEARCH = "https://stock.naver.com/domestic/stock/{code}/research"
NAVER_RESEARCH_API = "https://stock.naver.com/api/stockSecurity/researches/v2/company"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HanaVStockAnalyzer/1.1; report metadata)",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
}
FIELDS = ["date", "title", "broker", "analyst", "target_price", "url", "source"]


def _text(tag):
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)) if tag else ""


def _safe_original_url(href, base):
    """Keep only HTTP(S) publisher pages/PDFs. Never pass JS URLs into UI."""
    if not href or href.strip().lower().startswith(("javascript:", "#", "data:")):
        return ""
    url = urljoin(base, href.strip())
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    allowed = ("hankyung.com", "naver.com", "naver.net")
    if not any(host == domain or host.endswith("." + domain) for domain in allowed):
        return ""
    return url


def _matches_company(title, code, name):
    normalized = re.sub(r"\s+", "", str(title)).casefold()
    code = re.sub(r"\D", "", str(code))
    name = re.sub(r"\s+", "", str(name)).casefold()
    # A specific company code is preferred; avoid collisions with group names.
    if re.search(r"(?<!\d)" + re.escape(code) + r"(?!\d)", normalized):
        return True
    return len(name) >= 2 and normalized.startswith(name) and not re.search(r"\(\d{6}\)", normalized)


def _valid_date(raw):
    found = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", raw)
    if not found:
        return ""
    try:
        return date(*map(int, found.groups())).isoformat()
    except ValueError:
        return ""


def parse_legacy(html, code, name):
    """Classic Hankyung: date, classification, title, author, source, file."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 5:
            continue
        d = _valid_date(_text(cells[0]))
        kind = _text(cells[1])
        title = _text(cells[2])
        if not d or "기업" not in kind or not _matches_company(title, code, name):
            continue
        # The report title itself normally links directly to the broker PDF.
        link = ""
        for cell in [cells[2], *cells[5:]]:
            for a in cell.find_all("a", href=True):
                link = _safe_original_url(a.get("href"), HANKYUNG_LEGACY)
                if link:
                    break
            if link:
                break
        if not link:
            continue
        rows.append({
            "date": d, "title": title, "broker": _text(cells[4]),
            "analyst": _text(cells[3]), "target_price": "",
            "url": link, "source": "한경 컨센서스",
        })
    return rows


def parse_portal(html, code, name):
    """New Hankyung: title, target, analyst, broker, release date."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 5:
            continue
        title = _text(cells[0])
        when = _valid_date(_text(cells[4]))
        if not when or not _matches_company(title, code, name):
            continue
        link = ""
        for a in cells[0].find_all("a", href=True):
            link = _safe_original_url(a.get("href"), HANKYUNG_PORTAL)
            if link:
                break
        if not link:
            continue
        target = _text(cells[1])
        rows.append({
            "date": when, "title": title, "broker": _text(cells[3]),
            "analyst": _text(cells[2]), "target_price": target if target != "-" else "",
            "url": link, "source": "한경 컨센서스",
        })
    return rows



def _first_value(row, *keys):
    """Pick first populated field from Npay research metadata."""
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() not in ("", "None", "null"):
            return value
    return None


def _field_text(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        value = _first_value(value, "name", "brokerName", "label", "title", "value")
    if isinstance(value, (list, tuple)):
        return ", ".join(filter(None, (_field_text(v) for v in value)))
    return str(value).strip() if value is not None else ""


def _research_date(value):
    if isinstance(value, (int, float)) and value > 1_000_000_000:
        try:
            seconds = value / 1000 if value >= 1_000_000_000_000 else value
            return datetime.fromtimestamp(seconds).date().isoformat()
        except (ValueError, OverflowError, OSError):
            return ""
    raw = _field_text(value)
    if re.fullmatch(r"20\d{6}", raw):
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return _valid_date(raw)


def parse_naver_research(payload, code, name):
    """Parse metadata from Npay's public, undocumented stock research list.

    Only links created from IDs actually supplied by the provider are displayed.
    The provider can change its response format without notice.
    """
    if isinstance(payload, dict):
        items = payload.get("items")
        if not isinstance(items, list):
            envelope = payload.get("data") or payload.get("result") or {}
            items = envelope.get("items", []) if isinstance(envelope, dict) else []
    else:
        items = payload if isinstance(payload, list) else []
    rows = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        raw_nid = _first_value(entry, "nid", "researchId", "id")
        nid = str(raw_nid).strip() if raw_nid is not None else ""
        if not re.fullmatch(r"\d{1,18}", nid):
            continue
        title = _field_text(_first_value(entry,
            "title", "researchTitle", "researchName", "reportTitle", "subject", "name"))
        if not title:
            continue
        d = _research_date(_first_value(entry,
            "publishedAt", "publishDate", "publishedDate", "researchDate",
            "date", "dateTime", "reportDate", "writtenDate", "issueDate",
            "registerDate", "regDate", "createdAt", "createdDate",
            "publishAt", "issuedAt", "reportPubDate", "writeDate", "createDate"))
        if not d:
            continue
        # The Npay endpoint is already server-filtered by itemCodes. If the
        # response does contain a code, verify it before accepting the row.
        itemcode = _first_value(entry, "itemCode", "stockCode", "code")
        if itemcode and str(itemcode).strip().lstrip("A") != code:
            continue
        broker = _field_text(_first_value(entry,
            "brokerName", "broker", "securitiesFirm", "brokerageName",
            "sourceName", "officeName"))
        analyst = _field_text(_first_value(entry,
            "analystName", "analyst", "analysts", "researcherName", "writer", "author"))
        goal = _field_text(_first_value(entry,
            "goalPrice", "targetPrice", "targetStockPrice", "goalStockPrice"))
        try:
            if goal and float(goal.replace(",", "")) > 0:
                goal = f"{float(goal.replace(',', '')):,.0f}원"
            elif goal in ("0", "0.0", "-", "None"):
                goal = ""
        except ValueError:
            pass
        rows.append({
            "date": d, "title": title, "broker": broker,
            "analyst": analyst, "target_price": goal,
            "url": NAVER_ITEM_RESEARCH.format(code=code) + "/" + nid,
            "source": "Npay 증권",
        })
    return rows


def get_naver_reports(code, name):
    """One low-volume read-only request for a single company (max 20 rows)."""
    resp = requests.get(
        NAVER_RESEARCH_API,
        params={"itemCodes": code, "index": 0, "size": 20},
        headers={**HEADERS, "Accept": "application/json, text/plain, */*",
                 "Referer": NAVER_ITEM_RESEARCH.format(code=code)},
        timeout=(4, 10),
    )
    resp.raise_for_status()
    data = resp.json()
    return parse_naver_research(data, code, name)



def get_analyst_reports(code, name, limit=15):
    """Retrieve actual published report links, never fabricate report entries.

    Npay's public research list is checked by code first. The Hankyung
    consensus listing is a backup. These providers are third-party services
    and may restrict automated access; use their website links if unavailable.
    """
    if not re.fullmatch(r"\d{6}", str(code)):
        return pd.DataFrame(columns=FIELDS), "잘못된 종목코드"
    name = str(name).strip()
    all_rows = []
    status = []
    try:
        all_rows = get_naver_reports(code, name)
        if not all_rows:
            status.append("Npay 증권 응답에 해당 종목 리포트가 없습니다.")
    except requests.HTTPError as exc:
        code = getattr(exc.response, "status_code", None)
        status.append(f"Npay 증권 HTTP {code or '오류'} (제공처 접근·경로 확인 필요)")
    except (requests.RequestException, ValueError, TypeError) as exc:
        status.append(f"Npay 증권 조회 실패: {type(exc).__name__}")
    # Avoid multiple redundant requests when a code-filtered result succeeded.
    if not all_rows:
        for url, params, parser in [
            (HANKYUNG_LEGACY, {"search_type": "1", "search_text": name}, parse_legacy),
            (HANKYUNG_PORTAL, {"search_text": name}, parse_portal),
        ]:
            try:
                r = requests.get(url, params=params, headers=HEADERS, timeout=(4, 8))
                r.raise_for_status()
                r.encoding = r.apparent_encoding if not r.encoding else r.encoding
                all_rows.extend(parser(r.text, str(code), name))
            except (requests.RequestException, ValueError, TypeError) as exc:
                status.append(f"한경 조회 실패: {type(exc).__name__}")
    if not all_rows:
        return pd.DataFrame(columns=FIELDS), " / ".join(status) or "확인된 리포트 없음"
    cutoff = date.today() - timedelta(days=180)
    df = pd.DataFrame(all_rows, columns=FIELDS)
    df = df[df["date"].ge(cutoff.isoformat())].copy()
    df = df.drop_duplicates(["date", "title", "broker"]).sort_values("date", ascending=False)
    if df.empty:
        return df, "최근 6개월 이내 리포트 미확인"
    return df.head(max(1, min(int(limit), 30))).reset_index(drop=True), ""

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


def get_analyst_reports(code, name, limit=15):
    """Fetch selected company's published research metadata; never invent records.

    Input code is a six-digit Korean instrument code, name is its displayed name.
    Data can be empty if the provider blocks robots/changes filtering.
    """
    if not re.fullmatch(r"\d{6}", str(code)):
        return pd.DataFrame(columns=FIELDS), "잘못된 종목코드"
    name = str(name).strip()
    all_rows = []
    errors = []
    # Provider search parameters may vary over time. We validate each result
    # against the exact company code/name to avoid cross-company matches.
    sources = [
        (HANKYUNG_LEGACY, {"search_type": "1", "search_text": name},
         parse_legacy),
        (HANKYUNG_PORTAL, {"search_text": name}, parse_portal),
    ]
    for url, params, parser in sources:
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=(4, 8))
            r.raise_for_status()
            r.encoding = r.apparent_encoding if not r.encoding else r.encoding
            all_rows.extend(parser(r.text, str(code), name))
        except (requests.RequestException, ValueError) as exc:
            # Only disclose exception class; request URLs may carry user input.
            errors.append(type(exc).__name__)
    if not all_rows:
        return pd.DataFrame(columns=FIELDS), "리포트 제공처에서 종목별 목록을 수신하지 못했습니다."
    cutoff = date.today() - timedelta(days=180)
    df = pd.DataFrame(all_rows, columns=FIELDS)
    df = df[df["date"].ge(cutoff.isoformat())].copy()
    df = df.drop_duplicates(["date", "title", "broker"]).sort_values("date", ascending=False)
    return df.head(max(1, min(int(limit), 30))).reset_index(drop=True), "" if not df.empty else "최근 6개월 내 확인된 리포트가 없습니다."

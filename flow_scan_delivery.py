"""Private result storage and optional Telegram notifications for stock scans.

Only derived scan results are stored, and only in a private Supabase table
(accessed with server-side service role credentials). This module never puts
tokens into logs, URLs, public repository commits, or Streamlit responses.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
import re

import requests


def _supabase_credentials(env=None):
    e = os.environ if env is None else env
    url = (e.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (e.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        return None
    if not url.startswith("https://"):
        raise RuntimeError("Supabase URL은 https:// 주소여야 합니다")
    return url, key


def _headers(key):
    return {"apikey": key, "Authorization": "Bearer " + key,
            "Content-Type": "application/json"}


def read_latest_scan(env=None):
    creds = _supabase_credentials(env)
    if creds is None:
        return None
    url, key = creds
    response = requests.get(url + "/rest/v1/flow_scan_runs",
                            params={"select": "data", "order": "run_date.desc",
                                    "limit": "1"},
                            headers=_headers(key), timeout=15)
    if not response.ok:
        raise RuntimeError("Supabase 최신 스캔 조회 실패 (HTTP " +
                           str(response.status_code) + ")")
    records = response.json()
    return records[0]["data"] if records else None


def already_notified(day, env=None):
    creds = _supabase_credentials(env)
    if creds is None:
        return False
    url, key = creds
    response = requests.get(
        url + "/rest/v1/flow_scan_runs",
        params={"select": "alert_sent", "run_date": "eq." + str(day), "limit": "1"},
        headers=_headers(key), timeout=15)
    if not response.ok:
        raise RuntimeError("Supabase 알림 중복 확인 실패 (HTTP " +
                           str(response.status_code) + ")")
    rows = response.json()
    return bool(rows and rows[0]["alert_sent"])


def persist_scan(report, alert_sent=False, env=None):
    creds = _supabase_credentials(env)
    if creds is None:
        return False
    url, key = creds
    day = report["asof"]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("invalid scan asof")
    response = requests.post(
        url + "/rest/v1/flow_scan_runs",
        params={"on_conflict": "run_date"},
        json={"run_date": day, "data": report, "alert_sent": bool(alert_sent),
              "updated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat()},
        headers={**_headers(key),
                 "Prefer": "resolution=merge-duplicates,return=minimal"},
        timeout=25)
    if not response.ok:
        raise RuntimeError("Supabase 스캔 저장 실패 (HTTP " +
                           str(response.status_code) + ")")
    return True


def alert_text(report, max_rows=8):
    """Concise Telegram message, no misleading 'guaranteed' buying claims."""
    stats = report.get("totals", {})
    fresh = [x for x in report.get("results", [])
             if x.get("first_day") is True]
    continuation = [x for x in report.get("results", [])
                    if x.get("first_day") is False]
    title = (
        "🔄 수급 전환 마감 검색 · " + report["asof"] + "\n"
        + "KRX 코스피·코스닥 | 신규 " + str(len(fresh))
        + "개 · 연속 " + str(len(continuation)) + "개\n"
        + "전체 분석 대상 " + str(stats.get("scanned_tickers", 0)) + "개 종목\n"
    )
    if not fresh:
        return title + "신규 전환 조건 충족 종목 없음\n" + (
            "※ 집계 자료가 완전한 경우에만 발송한 결과입니다."
        )
    lines = []
    for index, item in enumerate(fresh[:max_rows], start=1):
        lines.append(
            f"{index}. {item['name']} ({item['code']}) · {item['market']}\n"
            f"   개인 {item['personal_qty']:+,}주, "
            f"외국인 {item['foreign_qty']:+,}주, "
            f"기관 {item['institution_qty']:+,}주\n"
            f"   순매도 평소대비 {item['sell_multiple']}배 · "
            f"전환강도 {item['strength']}/100"
        )
    if len(fresh) > max_rows:
        lines.append("외 " + str(len(fresh) - max_rows) + "종목")
    lines.append("※ 마감후 KRX 기준 / 매수 신호나 수익률 예측 아님")
    return title + "\n".join(lines)


def send_telegram(text, env=None):
    e = os.environ if env is None else env
    token = (e.get("TELEGRAM_BOT_TOKEN") or "").strip()
    recipient = (e.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not recipient:
        return False
    # Never include the Telegram access token in exceptions or logs.
    try:
        response = requests.post(
            "https://api.telegram.org/bot" + token + "/sendMessage",
            data={"chat_id": recipient, "text": text,
                  "disable_web_page_preview": "true"},
            timeout=20)
        if not response.ok or response.json().get("ok") is not True:
            raise RuntimeError("Telegram 메시지 전송 실패")
    except requests.RequestException:
        raise RuntimeError("Telegram 메시지 전송 네트워크 오류") from None
    except ValueError:
        raise RuntimeError("Telegram 메시지 응답 오류") from None
    return True

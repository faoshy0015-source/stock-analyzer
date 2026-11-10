"""Github Actions/manual CLI for KRX post-close full-market screening.

Do not publish investor-level source feeds or stock results in public artifacts.
Optionally store derived reports privately in Supabase and alert on Telegram.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import os
import sys
from zoneinfo import ZoneInfo

# Permit running from repo root via python scripts/run_flow_scan.py.
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from full_flow_scan import ScanDataError, run_full_scan
from krx_auth import krx_login_configured
from flow_scan_delivery import (
    alert_text, already_notified, persist_scan, send_telegram,
)


def _summary(report, message):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    totals = report.get("totals", {})
    body = (
        "## Stock Analyzer · 수급 전환 전시장 검색\n\n"
        f"- 기준 거래일: {report['asof']}\n"
        f"- 기준일 거래 종목: {totals.get('scanned_tickers', 0)}\n"
        f"- 기간 수급자료 완비 종목: {totals.get('eligible_tickers', 0)}\n"
        f"- 판정 가능 비율: {totals.get('eligible_ratio', 0):.1%}\n"
        f"- 신규 수급전환: {totals.get('new_signals', 0)}\n"
        f"- 연속 수급전환: {totals.get('continuations', 0)}\n"
        f"- 결과: {message}\n"
        "- 경고: 이 탐색은 KRX 원천 데이터의 종목 커버리지를 검증하며, "
        "투자 권유나 실시간 매매 신호가 아닙니다.\n"
    )
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="", help="YYYY-MM-DD; default current KST date")
    parser.add_argument("--notify", action="store_true", help="Send Telegram only on new hits")
    parser.add_argument("--lookback", type=int, choices=[10, 20], default=10)
    parser.add_argument("--markets", nargs="+", choices=["KOSPI", "KOSDAQ"],
                        default=["KOSPI", "KOSDAQ"])
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    asof = args.date.strip() or today.isoformat()
    if str(asof) > today.isoformat():
        parser.error("future date is not allowed")
    if not krx_login_configured():
        message = (
            "KRX 데이터 로그인 인증정보 미설정 (KRX_ID/KRX_PW). "
            "검색·알림을 실행하지 않았습니다. GitHub Actions Secrets에 등록하세요."
        )
        print("::warning::" + message)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
                out.write("## 전시장 검색 보류\\n\\n" + message + "\\n")
        # Scheduled runs are harmlessly skipped until credential setup;
        # explicit manual test runs fail visibly instead of claiming success.
        return 0 if os.environ.get("GITHUB_EVENT_NAME") == "schedule" else 3

    def progress(done, total, label):
        if done == 1 or done == total or done % 8 == 0:
            print(f"KRX 데이터 검증 {done}/{total}: {label}", flush=True)

    try:
        result = run_full_scan(asof, markets=tuple(args.markets), lookback=args.lookback,
                               min_coverage=None, progress=progress)
    except ScanDataError as exc:
        print("KRX data incomplete / scan aborted: " + str(exc), file=sys.stderr)
        return 2

    counts = result["totals"]
    print("자료 확인 완료" + (" (부분 범위)" if result["status"] == "partial" else "") +
          ": 기준일", result["asof"],
          "전체 거래 종목", counts["scanned_tickers"],
          "자료 완비 종목", counts["eligible_tickers"],
          "완비율", f"{counts['eligible_ratio']:.1%}",
          "신규 전환", counts["new_signals"],
          "연속 전환", counts["continuations"])

    alert_sent = False
    try:
        alert_sent = already_notified(result["asof"])
        stored = persist_scan(result, alert_sent=alert_sent)
        print("비공개 DB 저장:", "완료" if stored else "미설정(설정 후 이용 가능)")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        stored = False

    notified = False
    if args.notify and (
        counts["eligible_ratio"] < 0.90
        or result["coverage"]["min_investor_coverage"] < 0.90
    ):
        print(
            "자동 알림 보류: 기간별 투자자 수급표 포함 비율 또는 "
            "판정 가능 종목 비율이 90% 미만입니다. "
            "검색 결과 자체는 부분 범위로 저장될 수 있습니다."
        )
    elif args.notify and counts["new_signals"] and not alert_sent:
        try:
            notified = send_telegram(alert_text(result))
            print("Telegram 알림:", "발송됨" if notified else "미설정(토큰·채팅ID 필요)")
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
        if notified and stored:
            persist_scan(result, alert_sent=True)
    elif args.notify and not counts["new_signals"]:
        print("신규 수급 전환 종목 없음: 알림 생략")
    elif alert_sent:
        print("해당 일자 알림 중복 방지: 추가 발송 생략")

    delivery = ("DB 저장 " + ("완료" if stored else "미설정") +
                " / Telegram " + ("전송" if notified else "미전송"))
    _summary(result, delivery)
    return 0


if __name__ == "__main__":
    sys.exit(main())

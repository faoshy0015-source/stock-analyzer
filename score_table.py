"""Accessible, compact score-evidence table for narrow Streamlit columns.

Use escaped text throughout. Display all confidence strings without horizontal
scrolling; numerical columns have fixed narrow widths.
"""
from __future__ import annotations

from html import escape
from math import isfinite


def _number(value, digits=0):
    try:
        n=float(value)
        if not isfinite(n):
            return "—"
        return f"{n:.{digits}f}" if digits else f"{n:g}"
    except (ValueError, TypeError, OverflowError):
        return "—"


def render_score_table(rows):
    """Render complete, wrap-friendly scores including partial evidence labels."""
    trs=[]
    for item in rows or []:
        label=escape(str(item.get("category") or "—"))
        maximum=_number(item.get("weight"))
        covered=_number(item.get("covered_weight",0))
        score=item.get("score")
        has_score=False
        try:
            has_score=score is not None and isfinite(float(score))
        except (TypeError, ValueError, OverflowError):
            pass
        partial=has_score and covered!=maximum
        score_text=(f"{_number(score,1)}{'*' if partial else ''}"
                    if has_score else "미산출")
        trust=escape(str(item.get("confidence") or "미산출"))
        status="score-partial" if partial else ("score-missing" if not has_score else "score-full")
        trs.append(
            f'<tr><th scope="row">{label}</th>'
            f'<td class="score-number">{maximum}</td>'
            f'<td class="score-number">{covered}</td>'
            f'<td class="score-number {status}">{score_text}</td>'
            f'<td class="score-trust">{trust}</td></tr>'
        )
    body="".join(trs) if trs else '<tr><td colspan="5">평가 항목이 없습니다.</td></tr>'
    return (
        '<div class="score-table-wrap">'
        '<table class="score-compact-table">'
        '<colgroup><col style="width:24%"><col style="width:9%">'
        '<col style="width:10%"><col style="width:14%">'
        '<col style="width:43%"></colgroup>'
        '<thead><tr><th scope="col">영역</th><th scope="col">배점</th>'
        '<th scope="col">반영</th><th scope="col">점수</th>'
        '<th scope="col">신뢰도</th></tr></thead>'
        f'<tbody>{body}</tbody>'
        '</table></div>'
    )

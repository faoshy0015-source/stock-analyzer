"""Offline proposal SVG charts, conditional holder/buyer strategies, and real PNG."""
from io import BytesIO
from pathlib import Path

import pandas as pd
from PIL import Image

from trade_plan import price_context, conditional_trade_plan
from proposal_visuals import price_chart_svg, score_chart_svg, target_chart_svg, png_summary
from report import render_html, snapshot


def quotes(n=140):
    dates=pd.date_range("2026-04-01",periods=n,freq="B")
    return pd.DataFrame(
        {"Close":[100000+i*200 for i in range(n)],"Volume":[1000000]*n},
        index=dates,
    )


def scores():
    rows=[]
    for name,score,weight,used in (
        ("실적·성장성",70,25,25),
        ("밸류에이션",45,20,16),
        ("수급",30,15,15),
        ("재무건전성",90,20,15),
        ("주가 추세",60,10,10),
        ("뉴스 모멘텀",None,10,0),
    ):
        rows.append({
            "category":name,"weight":weight,"covered_weight":used,
            "score":score,"confidence":"부분 평가" if weight!=used else "보통",
            "notes":[f"{name} 근거 확인","원자료 점검 권고"],
        })
    return {"rows":rows,"total":57.0,"coverage":81,"label":"중립·관찰","partial":True}


def target():
    return {
        "average":155000,"upside_pct":15.0,"count":3,"min":145000,"max":160000,
        "price_asof":"2026-11-06","rows":[
            {"broker":"가상 A","date":"2026-11-02","target":145000,"title":"A","url":"https://example.com/a"},
            {"broker":"가상 B","date":"2026-10-31","target":160000,"title":"B","url":"https://example.com/b"},
            {"broker":"가상 C","date":"2026-10-28","target":160000,"title":"C","url":"https://example.com/c"},
        ]
    }


def test_price_chart_uses_real_observations_and_ma20_ma60():
    svg=price_chart_svg(quotes())
    assert "<svg" in svg and "</svg>" in svg
    assert 'role="img"' in svg
    assert "2026-" in svg
    assert svg.count("<path")>=3
    assert "#138c78" in svg and "#e87d31" in svg
    assert "<script" not in svg and "https://" not in svg


def test_empty_history_keeps_chart_unavailable_not_fabricated():
    svg=price_chart_svg(pd.DataFrame())
    assert "<svg" not in svg
    assert "자료가 부족합니다" in svg
    assert price_context(pd.DataFrame())["ma20"] is None


def test_score_chart_marks_partial_and_missing():
    svg=score_chart_svg(scores())
    assert "재무건전성" in svg
    assert "90.0*" in svg
    assert "뉴스 모멘텀" in svg and "미산출" in svg


def test_target_chart_uses_consensus_and_has_valid_empty_fallback():
    assert "155,000원" in target_chart_svg(135000,target())
    assert "135,000원" in target_chart_svg(135000,target())
    assert "<svg" not in target_chart_svg(None)
    assert "검증 가능한 목표가" in target_chart_svg(None)
    fallback=target_chart_svg(100000,{},{"target":120000})
    assert "Npay" in fallback and "별도 집계" in fallback


def test_trade_plan_separates_holder_and_new_buyer():
    p=conditional_trade_plan(scores(),quotes(),target())
    assert len(p["holder"])>=2
    assert len(p["new_buyer"])>=2
    assert "기존 보유자" in p["holder"][0]
    assert "신규 검토자" in p["new_buyer"][0]
    assert "보장" in " ".join(p["checkpoints"]+p["new_buyer"]+[
        p["disclaimer"]
    ])
    assert p["technical"]["ma20"] is not None


def test_no_data_strategy_does_not_invent_entry_level():
    low={"rows":[],"total":None,"coverage":0,"label":"판단 보류"}
    plan=conditional_trade_plan(low,pd.DataFrame())
    combined=" ".join(plan["holder"]+plan["new_buyer"]+plan["checkpoints"])
    assert "미확보" in combined or "부족" in combined
    assert "20·60거래일" in combined
    assert plan["technical"]["close"] is None


def test_html_proposal_standalone_svg_and_two_investor_views():
    report=render_html(
        {"name":"가상테스트종목","code":"123456"},scores(),
        "추세 및 수급을 점검합니다.",135000,"2026-11-06",
        {"price":"테스트 지연 종가","financial":"OpenDART"},
        target_summary=target(),prices=quotes(),
    )
    assert "<svg" in report and report.count("<svg")>=3
    assert "① 기존 보유자 관점" in report
    assert "② 신규 매수 검토자 관점" in report
    assert "핵심 모니터링 포인트" in report
    assert "155,000원" in report and "15.00%" in report
    assert "SVG" not in report or "svg" in report.lower()
    assert "plotly.js" not in report
    assert "@page" in report and "A4" in report
    assert "CREATED BY K.H.AHN" in report
    assert "외부 배포" not in report or "준법" in report
    assert "수익률 예측이나 보장이 아닙니다" in report


def test_html_escapes_external_names_and_untrusted_explanations():
    x=render_html({"name":"<script>alert('x')</script>","code":"000000"},
        scores(),"<img src=x onerror=alert(1)>",100000,"today",
        {"price":"<svg/onload=alert(1)>"})
    assert "<script>alert(" not in x and "<img src=x onerror=" not in x
    assert "&lt;script&gt;" in x
    assert "&lt;img " in x


def test_html_without_price_data_has_meaningful_empty_chart():
    html=render_html({"name":"테스트","code":"000000"},
        {"rows":[],"total":None,"coverage":0,"label":"판단 보류"},
        "평가 보류",None,"확인 불가",{},prices=pd.DataFrame())
    assert "자료가 부족합니다" in html
    assert "목표가 및 상승여력은 미산출" in html


def test_png_is_a_real_image_and_valid_size():
    data=png_summary({"name":"가상테스트종목","code":"123456"},scores(),
                     135000,"2026-11-06",prices=quotes(),
                     plan=conditional_trade_plan(scores(),quotes(),target()),
                     target_summary=target())
    assert data[:8]==b"\x89PNG\r\n\x1a\n"
    with Image.open(BytesIO(data)) as im:
        assert im.size==(1200,1700)
        assert im.format=="PNG"
        assert len(im.getcolors(10000000) or [])>30


def test_png_no_data_is_still_image_and_json_remains_separate():
    no_score={"rows":[],"total":None,"coverage":0,"label":"판단 보류"}
    png=png_summary({"name":"테스트","code":"000000"},no_score,None,
                    "기준일 미확인",prices=pd.DataFrame())
    assert png.startswith(b"\x89PNG")
    json_bytes=snapshot({"name":"테스트","code":"000000"},no_score,"기준일 미확인")
    assert json_bytes.startswith(b"{")
    assert png!=json_bytes


def test_app_exposes_four_distinct_download_buttons():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert "차트·전략 포함 인쇄용 HTML" in app
    assert "한 장 요약 이미지 PNG" in app
    assert "점수 기록 JSON (과거 비교용)" in app
    assert "📋 평가 근거 CSV" in app
    assert "prices=prices,trade_plan=trade_plan" in app

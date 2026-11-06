"""Standalone, printable HTML research snapshot."""
from html import escape
from datetime import datetime
import json
import math


def safe(x):
    return escape(str(x))


def fmt(v,unit='',digits=1):
    try:
        if v is None or not math.isfinite(float(v)):return '-'
        return f'{float(v):,.{digits}f}{unit}'
    except Exception:return '-'


def render_html(instrument, result, narrative, price, stamp, sources,
                target_summary=None, published_target=None, prices=None, trade_plan=None):
    """Generate an independent print-ready research proposal in a single HTML.

    All graphics are inline SVG and remain visible offline and in Save as PDF.
    Old callers without prices/strategy remain compatible.
    """
    from proposal_visuals import price_chart_svg, score_chart_svg, target_chart_svg
    from trade_plan import conditional_trade_plan

    target_summary=target_summary or {}
    published_target=published_target or {}
    plan=trade_plan if trade_plan is not None else conditional_trade_plan(
        result,prices,target_summary,published_target)
    coverage=result.get("coverage",0)
    score=result.get("total")
    rows=[]
    for item in result.get("rows",[]):
        maximum=item.get("weight") or 0
        used=item.get("covered_weight") or 0
        partial=" · 일부 평가" if used<maximum else ""
        notes=(item.get("notes") or [])[:2]
        rows.append(
            f'<tr><th scope="row">{safe(item.get("category",""))}</th>'
            f'<td class="num">{maximum:g}</td><td class="num">{used:g}</td>'
            f'<td class="num">{fmt(item.get("score"),"",1)}</td>'
            f'<td>{safe(" / ".join(str(v) for v in notes) if notes else "근거 미확인")}'
            f'<span class="hint">{safe(partial)}</span></td></tr>'
        )
    score_rows="".join(rows)
    def _items(values):
        return "".join(f"<li>{safe(v)}</li>" for v in values or []) or "<li>확인할 자료가 없습니다.</li>"

    target_section=""
    if target_summary.get("average") is not None:
        avg=fmt(target_summary["average"],"원",0)
        upside=fmt(target_summary.get("upside_pct"),"%",2)
        count=int(target_summary.get("count") or 0)
        broker_rows="".join(
            '<tr>'
            f'<td>{safe(i.get("broker",""))}</td>'
            f'<td>{safe(i.get("date",""))}</td>'
            f'<td class="num">{fmt(i.get("target"),"원",0)}</td>'
            '</tr>'
            for i in target_summary.get("rows",[])
        )
        target_section=(
            '<h2>최근 90일 애널리스트 목표주가</h2>'
            f'<div class="kpi-row"><div class="metric"><small>증권사별 최신 보고서 {count}곳</small>'
            f'<strong>{avg}</strong></div><div class="metric"><small>기준가 대비 상승여력</small>'
            f'<strong>{upside}</strong></div></div>'
            '<p class="fine">최근 90일, 증권사별 최신 보고서 1건의 목표가를 산술평균했습니다. '
            '가격 기준일을 확인해야 하며 이 값은 수익률 예측이나 보장이 아닙니다.</p>'
            f'<div class="target-chart">{target_chart_svg(price,target_summary,published_target)}</div>'
            '<details><summary>평균에 반영된 증권사·발행일·목표주가 확인</summary>'
            '<table><thead><tr><th>증권사</th><th>발행일</th><th>목표주가</th></tr></thead>'
            f'<tbody>{broker_rows}</tbody></table></details>'
        )
    elif published_target.get("target") is not None:
        target_section=(
            '<h2>제공처 목표주가 컨센서스</h2>'
            f'<div class="kpi-row"><div class="metric"><small>Npay 별도 집계 · '
            f'{safe(published_target.get("date","기준일 미확인"))}</small>'
            f'<strong>{fmt(published_target["target"],"원",0)}</strong></div>'
            '<div class="metric"><small>조회 가격 대비 상승여력</small>'
            f'<strong>{fmt(published_target.get("upside_pct"),"%",2)}</strong></div></div>'
            '<p class="fine">Npay 제공 평균으로 최근 보고서를 직접 산술평균한 값이 아닙니다. '
            '표본 수와 집계기간 미확인. 적정주가 또는 수익률 예측으로 사용하지 마세요.</p>'
            f'<div class="target-chart">{target_chart_svg(price,target_summary,published_target)}</div>'
        )
    else:
        target_section=(
            '<h2>애널리스트 목표주가</h2>'
            '<p class="unavailable">확인 가능한 복수 증권사 목표주가가 없으며, '
            '제공처 별도 컨센서스도 확인되지 않았습니다. 목표가 및 상승여력은 미산출입니다.</p>'
        )
    tech=plan.get("technical") or {}
    tech_context=(
        f"종가 기준 {safe(tech.get('asof') or '확인 불가')} · "
        f"20일선 {fmt(tech.get('ma20'),'원',0)} / "
        f"60일선 {fmt(tech.get('ma60'),'원',0)}"
    )
    return f'''<!DOCTYPE html><html lang="ko"><head>
    <meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
    <title>{safe(instrument.get('name','종목 미확인'))} | Stock Analyzer 리서치 제안서</title>
    <style>
    :root{{--ink:#30463d;--teal:#138c78;--orange:#e87d31;--border:#e9d9c6}}
    *{{box-sizing:border-box}}
    body{{margin:0;color:var(--ink);background:#fffaf3;
      font-family:"Noto Sans KR","Malgun Gothic",Arial,sans-serif}}
    main{{max-width:920px;margin:24px auto;background:#fffefa;
      padding:30px 34px 26px;border:1px solid var(--border);border-radius:16px}}
    h1{{font-size:30px;margin:6px 0 8px;color:#285845;letter-spacing:-.6px}}
    h2{{font-size:18px;color:#315746;margin:20px 0 10px;border-left:4px solid var(--orange);
      padding-left:11px;break-after:avoid}}
    h3{{font-size:14px;margin:3px 0 9px;color:#315746}}
    header{{padding:20px 23px;background:linear-gradient(112deg,#fff0d7,#e9f7ef);
      border:1px solid var(--border);border-left:5px solid var(--orange);border-radius:12px}}
    .eyebrow{{font-size:10px;font-weight:800;letter-spacing:1.8px;color:#b86a2f}}
    .fine,.source{{font-size:11px;color:#687b6e;line-height:1.65}}
    .source{{margin-top:9px}}
    .kpi-row{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:15px 0 7px}}
    .kpi-row .metric{{background:#fff8ec;border:1px solid var(--border);
      padding:12px 13px;border-radius:10px;min-width:0}}
    .metric small{{display:block;color:#6d7d6f;font-size:11px;margin-bottom:6px}}
    .metric strong{{font-size:22px;color:#376451;letter-spacing:-.5px;display:block;
      overflow-wrap:anywhere}}
    .two{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
    .strategy{{border:1px solid #ead8bf;background:#fffaf2;border-radius:11px;
      padding:13px 16px;break-inside:avoid}}
    .strategy.holder{{border-top:4px solid var(--teal)}}
    .strategy.buyer{{border-top:4px solid var(--orange)}}
    .strategy ul,.checks ul{{padding-left:18px;margin:5px 0 0}}
    li{{font-size:12px;line-height:1.55;margin:6px 0}}
    .checks{{background:#f2f8f0;border-radius:10px;padding:11px 15px;
      border:1px solid #dfebdd;break-inside:avoid}}
    .graph{{border:1px solid #e9e2d5;border-radius:10px;padding:8px;
      background:#fffefa;break-inside:avoid}}
    .graph svg{{display:block;width:100%;height:auto}}
    .legend{{font-size:11px;color:#607568;margin:5px 0 0}}
    .swatch{{display:inline-block;width:11px;height:3px;vertical-align:middle;margin-right:4px}}
    table{{border-collapse:collapse;width:100%;font-size:11px;table-layout:fixed}}
    th,td{{padding:8px 6px;border-bottom:1px solid #eae0d1;vertical-align:top;
      overflow-wrap:anywhere;word-break:keep-all}}
    thead th{{background:#fff0db;color:#385e4c;text-align:left}}
    .num{{text-align:center;white-space:nowrap}}
    .hint{{color:#a76c38}}
    .unavailable{{background:#f6f3ee;padding:11px 13px;border-radius:8px;
      color:#6d756e;font-size:12px}}
    details{{margin-top:10px;padding:9px 12px;border:1px solid var(--border);border-radius:8px}}
    summary{{font-size:12px;cursor:pointer}}
    .risk{{background:#fff1df;color:#755737;padding:12px 14px;font-size:11px;
      border-radius:9px;line-height:1.7;break-inside:avoid}}
    footer{{border-top:1px solid var(--border);margin-top:20px;padding-top:11px;
      color:#687b6e;font-size:10px;line-height:1.65}}
    .chart-empty{{font-size:12px;color:#8a867e;padding:32px;text-align:center}}
    @page{{size:A4;margin:10mm}}
    @media print{{
      body{{background:#fff}}
      main{{padding:0;border:0;margin:0;max-width:none}}
      header{{print-color-adjust:exact;-webkit-print-color-adjust:exact}}
      .metric,.strategy,.graph,.checks,.risk{{
        print-color-adjust:exact;-webkit-print-color-adjust:exact}}
      .strategy,.graph,table tr{{break-inside:avoid}}
      .page-break{{break-before:page}}
    }}
    @media(max-width:620px){{
      main{{margin:0;padding:16px}}
      .two{{grid-template-columns:1fr}}
      .metric strong{{font-size:16px}}
      .kpi-row{{gap:5px}}
    }}
    </style></head><body><main>
    <header>
      <div class="eyebrow">STOCK ANALYZER · CREATED BY K.H.AHN · INDEPENDENT RESEARCH</div>
      <h1>{safe(instrument.get('name','종목 미확인'))}
        <span style="font-size:17px;color:#7d8e83">{safe(instrument.get('code',''))}</span></h1>
      <div class="fine">정량평가 + 주가 시나리오 + 조건부 투자 체크포인트 · 기준 {safe(stamp)}</div>
    </header>
    <div class="kpi-row">
      <div class="metric"><small>확인 가격</small><strong>{fmt(price,'원',0)}</strong></div>
      <div class="metric"><small>종합 점수 (재가중)</small><strong>{fmt(score,' / 100',1)}</strong></div>
      <div class="metric"><small>평가 데이터 충족률</small><strong>{fmt(coverage,'%',0)}</strong></div>
    </div>
    <p class="fine">점수는 실제 검증된 배점만 재가중한 잠정치일 수 있으며, 가격은 지연 시세 또는 조회 시점 가격입니다.</p>

    <h2>최근 주가 추이와 기술적 기준</h2>
    <div class="graph">{price_chart_svg(prices)}</div>
    <p class="legend"><span class="swatch" style="background:#138c78"></span>종가
      &nbsp; <span class="swatch" style="background:#e87d31"></span>20일 이동평균
      &nbsp; <span class="swatch" style="background:#839e68"></span>60일 이동평균
      &nbsp; · {tech_context}</p>

    <h2>항목별 투자 매력도</h2>
    <div class="graph">{score_chart_svg(result)}</div>
    <p class="fine">오렌지색(*)은 일부 배점만 확인한 평가, 회색은 미산출입니다. 100점이라도 미확인 위험이 없다는 의미는 아닙니다.</p>

    {target_section}

    <h2>한 줄 종합 평가</h2>
    <div class="risk">{safe(narrative)}</div>
    <h2>기존 보유자와 신규 매수 검토자: 조건부 대응</h2>
    <div class="two">
      <div class="strategy holder">
        <h3>① 기존 보유자 관점</h3><ul>{_items(plan.get('holder'))}</ul>
      </div>
      <div class="strategy buyer">
        <h3>② 신규 매수 검토자 관점</h3><ul>{_items(plan.get('new_buyer'))}</ul>
      </div>
    </div>
    <h2>핵심 모니터링 포인트</h2>
    <div class="checks"><ul>{_items(plan.get('checkpoints'))}</ul></div>

    <h2>영역별 점수와 평가 근거</h2>
    <table><colgroup><col style="width:17%"/><col style="width:9%"/>
      <col style="width:9%"/><col style="width:11%"/><col style="width:54%"/></colgroup>
      <thead><tr><th>평가영역</th><th>배점</th><th>검증</th><th>점수</th><th>근거·한계</th></tr></thead>
      <tbody>{score_rows}</tbody></table>
    <p class="fine">자료 출처: {safe('; '.join(str(v) for v in sources.values() if v))} ·
      평가 기준과 세부 산출 근거는 앱 화면에서 확인 가능합니다.</p>
    <div class="risk">{safe(plan.get('disclaimer',''))}</div>
    <footer>STOCK ANALYZER · CREATED BY K.H.AHN ·
    본 문서는 투자 참고용 조건부 시나리오로 수익을 보장하거나 매수·매도를 지시하지 않습니다.
    투자목적·기간·경험·손실감내능력·보유 비중·고객 적합성을 별도 확인해야 합니다.
    증권사 목표주가는 리서치 의견이며 실현수익률 예측이 아닙니다.
    원천데이터의 라이선스와 회사 내부 준법 심사 절차를 확인한 후 외부 배포해야 합니다.
    문서생성: {safe(datetime.now().strftime('%Y-%m-%d %H:%M'))}</footer>
    </main></body></html>'''


def snapshot(instrument, result, stamp):
    return json.dumps({'version':1,'instrument':instrument,'created_at':datetime.now().isoformat(),
                       'price_asof':stamp,'score':result['total'],'coverage':result['coverage'],
                       'categories':{r['category']:{'score':r['score'],'weight':r['weight'],
                           'covered_weight':r.get('covered_weight',0),
                           'components':r.get('components',[])} for r in result['rows']}},
                      ensure_ascii=False, indent=2).encode('utf-8')

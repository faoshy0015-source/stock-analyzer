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


def render_html(instrument, result, narrative, price, stamp, sources):
    rows=''.join(f'<tr><td>{safe(x["category"])}</td><td>{x["weight"]}</td>'
                 f'<td>{x.get("covered_weight",0):g}</td>'
                 f'<td>{fmt(x["score"],"점")}</td><td>{safe(" / ".join(x["notes"][:2]) or "데이터 없음")}</td></tr>'
                 for x in result['rows'])
    return f'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
    <title>{safe(instrument['name'])} | HanaV Stock Analyzer</title>
    <style>body{{font-family:"Malgun Gothic",Arial,sans-serif;color:#15233b;margin:0;background:#f3f6fa}}main{{max-width:900px;margin:30px auto;background:#fff;padding:36px;box-shadow:0 8px 30px #dde3eb}}h1{{margin:0;color:#0b2442}}.sub{{color:#537189;font-size:12px}}.big{{font-size:37px;color:#078a82;font-weight:bold}}.row{{display:flex;gap:24px;flex-wrap:wrap;border-top:1px solid #eee;padding-top:20px}}.card{{flex:1;min-width:170px}}table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:13px}}th{{text-align:left;background:#eef4f7}}th,td{{padding:11px;border-bottom:1px solid #e5e9ee;vertical-align:top}}h2{{margin-top:30px;font-size:18px}}.alert{{background:#f0f7f6;padding:18px;line-height:1.75;border-left:3px solid #078a82}}footer{{margin-top:25px;padding-top:15px;color:#667887;font-size:11px;border-top:1px solid #ddd;line-height:1.6}}@media print{{body{{background:white}}main{{margin:0;box-shadow:none;padding:5mm}}}} </style></head>
    <body><main><div class="sub">HANAV INVESTMENT INTELLIGENCE · 자동생성 정량 리포트</div>
    <h1>{safe(instrument['name'])} <span class="sub">{safe(instrument['code'])}</span></h1>
    <div class="sub">기준 시점: {safe(stamp)} | 시세 제공처: {safe(sources.get('price','확인 불가'))}</div>
    <div class="row"><div class="card"><div class="sub">조회 가격</div><div class="big">{fmt(price,'원',0)}</div></div>
    <div class="card"><div class="sub">종합 점수 (산출 가능 항목 재가중)</div><div class="big">{fmt(result['total'],' / 100')}</div></div>
    <div class="card"><div class="sub">데이터 충족률 (배점 기준)</div><div class="big">{result['coverage']}%</div></div></div>
    <h2>종합 의견 | {safe(result['label'])}</h2><div class="alert">{safe(narrative)}</div>
    <h2>항목별 평가와 근거</h2><table><thead><tr><th>영역</th><th>전체 배점</th><th>반영 배점</th><th>평가 점수</th><th>주요 근거</th></tr></thead><tbody>{rows}</tbody></table>
    <footer>자료: {safe('; '.join(str(v) for v in sources.values() if v))}. 분석 시점 {safe(datetime.now().strftime('%Y-%m-%d %H:%M'))}.<br/>본 문서는 투자 참고용으로, 수익을 보장하거나 매수·매도를 권유하지 않습니다. 시세는 지연되거나 데이터 공급처가 변경될 수 있습니다. 공개 재무는 제출 시점 이후 반영되며 과거 실적은 미래 성과를 보장하지 않습니다. 밸류에이션은 동종업종 PER(6), 과거 PER·PBR 밴드(5), 3개년 ROE 지속성(5), 동기준 Forward PER(4)의 확인된 증거만 평가합니다. 재무건전성은 부채비율(5), 영업현금흐름 전환율(6), 이자보상배율(5), 유동비율(4)을 검증된 배점만 반영합니다. 전망 컨센서스, 과거자료 또는 KRX 비교 데이터가 없으면 해당 세부 배점을 제외하며, 업종 및 회계기준 차이로 평가 신뢰도가 제한됩니다. 외부 배포 전 데이터 권리·회사 준법 절차를 확인하세요.</footer></main></body></html>'''


def snapshot(instrument, result, stamp):
    return json.dumps({'version':1,'instrument':instrument,'created_at':datetime.now().isoformat(),
                       'price_asof':stamp,'score':result['total'],'coverage':result['coverage'],
                       'categories':{r['category']:{'score':r['score'],'weight':r['weight'],
                           'covered_weight':r.get('covered_weight',0),
                           'components':r.get('components',[])} for r in result['rows']}},
                      ensure_ascii=False, indent=2).encode('utf-8')

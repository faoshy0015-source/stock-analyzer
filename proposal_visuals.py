"""Self-contained print-friendly SVG charts and a real PNG research summary.

No browser screenshots and no network calls. Every mark is derived from data,
and a missing metric stays marked as unavailable.
"""
from __future__ import annotations

from html import escape
from io import BytesIO
from math import isfinite
from pathlib import Path
import re

import pandas as pd


GREEN="#138c78"
ORANGE="#e87d31"
AMBER="#e8a15e"
INK="#30463d"
GRAY="#84918a"
PAPER="#fffefa"
LIGHT="#e8e2d7"


def num(value):
    try:
        x=float(value)
        return x if isfinite(x) else None
    except (ValueError,TypeError,OverflowError):
        return None


def price_history(prices, sessions=125):
    """Return clean chronological closes without silently filling gaps."""
    if not isinstance(prices,pd.DataFrame) or prices.empty or "Close" not in prices:
        return pd.DataFrame()
    p=prices[["Close"]].copy()
    p.index=pd.to_datetime(p.index,errors="coerce")
    p=p.loc[p.index.notna()].copy()
    if getattr(p.index,"tz",None) is not None:
        p.index=p.index.tz_localize(None)
    p=p[~p.index.duplicated(keep="last")].sort_index()
    p["Close"]=pd.to_numeric(p["Close"],errors="coerce")
    p=p.loc[p["Close"]>0].dropna(subset=["Close"])
    p["MA20"]=p["Close"].rolling(20,min_periods=20).mean()
    p["MA60"]=p["Close"].rolling(60,min_periods=60).mean()
    return p.tail(max(2,int(sessions)))


def _paths(data, width, height, left, top, right, bottom):
    """Map daily close/MA observations into SVG path commands."""
    inner_w=width-left-right
    inner_h=height-top-bottom
    series=pd.concat([data[c] for c in ("Close","MA20","MA60")],ignore_index=True).dropna()
    low=float(series.min())
    high=float(series.max())
    if high<=low:high=low+max(1,low*.01)
    pad=(high-low)*.09
    low=max(0,low-pad)
    high+=pad
    def xy(index,value):
        x=left+inner_w*index/max(1,len(data)-1)
        y=top+inner_h*(high-float(value))/(high-low)
        return x,y
    paths={}
    for column in ("Close","MA20","MA60"):
        parts=[]; open_path=False
        for i,value in enumerate(data[column]):
            if not pd.notna(value):
                open_path=False
                continue
            x,y=xy(i,value)
            parts.append(f"{'L' if open_path else 'M'}{x:.1f},{y:.1f}")
            open_path=True
        paths[column]=" ".join(parts)
    return paths,low,high,xy


def price_chart_svg(prices, width=850, height=265, sessions=125):
    """Inline SVG, printable without plotly.js, internet or image downloads."""
    data=price_history(prices,sessions)
    if len(data)<2:
        return ('<div class="chart-empty">주가 차트: 조회 가능한 일별 종가 자료가 '
                '부족합니다.</div>')
    left,top,right,bottom=65,20,18,37
    paths,lo,hi,_=_paths(data,width,height,left,top,right,bottom)
    chart_w=width-left-right
    chart_h=height-top-bottom
    parts=[
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        'role="img" aria-label="일별 종가와 20일, 60일 이동평균선의 최근 주가 추이">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{PAPER}" rx="8"/>'
    ]
    for i in range(5):
        y=top+chart_h*i/4
        v=hi-(hi-lo)*i/4
        parts.append(
            f'<line x1="{left}" x2="{left+chart_w}" y1="{y:.1f}" y2="{y:.1f}" '
            f'stroke="{LIGHT}" stroke-width="1"/>'
            f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="11" '
            f'fill="{GRAY}">{v:,.0f}</text>'
        )
    for i in (0,len(data)//2,len(data)-1):
        x=left+chart_w*i/(len(data)-1)
        day=escape(pd.Timestamp(data.index[i]).strftime("%Y-%m-%d"))
        parts.append(
            f'<text x="{x:.1f}" y="{height-13}" text-anchor="middle" font-size="11" '
            f'fill="{GRAY}">{day}</text>'
        )
    for col,color,width_line in (("Close",GREEN,2.8),("MA20",ORANGE,1.8),("MA60","#839e68",1.8)):
        if paths[col]:
            parts.append(f'<path d="{paths[col]}" fill="none" stroke="{color}" '
                         f'stroke-width="{width_line}" stroke-linejoin="round"/>')
    parts.append("</svg>")
    return "".join(parts)


def score_chart_svg(scores, width=850, height=240):
    rows=(scores or {}).get("rows",[])
    if not rows:return '<div class="chart-empty">항목별 점수 자료 미확보</div>'
    h=max(height,30+len(rows)*34)
    name_width=124; left=130; plot_w=width-left-84
    body=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {h}" '
          'role="img" aria-label="실적, 가치평가, 수급, 재무건전성, 주가 추세 및 뉴스 점수">'
          f'<rect width="{width}" height="{h}" fill="{PAPER}" rx="8"/>']
    for i,row in enumerate(rows):
        y=28+i*34
        name=escape(str(row.get("category","")))
        value=num(row.get("score"))
        total=num(row.get("weight")) or 0
        used=num(row.get("covered_weight")) or 0
        color=ORANGE if 0<used<total else GREEN if used==total and value is not None else "#d7d6d1"
        bar=round(max(0,min(100,value or 0))/100*plot_w,1)
        score_text=(f"{value:.1f}{'*' if 0<used<total else ''}"
                    if value is not None else "미산출")
        body.append(
            f'<text x="4" y="{y+12}" fill="{INK}" font-size="12">{name}</text>'
            f'<rect x="{left}" y="{y}" width="{plot_w}" height="18" rx="4" fill="#f0efea"/>'
        )
        if value is not None:
            body.append(f'<rect x="{left}" y="{y}" width="{bar}" height="18" rx="4" fill="{color}"/>')
        body.append(f'<text x="{left+plot_w+9}" y="{y+13}" fill="{INK}" font-size="12">'
                    f'{escape(score_text)}</text>')
    body.append('</svg>')
    return "".join(body)


def target_chart_svg(current_price, target_summary=None, published_target=None, width=850):
    target_summary=target_summary or {}
    published_target=published_target or {}
    target=num(target_summary.get("average"))
    source="최근 90일 증권사별 최신 목표주가 산술평균"
    if target is None:
        target=num(published_target.get("target"))
        source="Npay 제공 평균 목표가 (별도 집계 · 표본 미확인)"
    now=num(current_price)
    if not now or not target or now<=0 or target<=0:
        return '<div class="chart-empty">목표주가 비교: 검증 가능한 목표가와 기준가격이 없습니다.</div>'
    maxv=max(now,target)*1.14
    parts=[
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 125" '
        'role="img" aria-label="기준 가격과 증권사 목표주가의 비교">'
        f'<rect width="{width}" height="125" fill="{PAPER}" rx="8"/>'
    ]
    for i,(label,v,color) in enumerate((("기준 가격",now,GREEN),("목표주가",target,ORANGE))):
        y=18+i*48
        w=600*v/maxv
        parts.append(
            f'<text x="8" y="{y+12}" fill="{INK}" font-size="13">{label}</text>'
            f'<rect x="113" y="{y}" width="{w:.1f}" height="22" fill="{color}" rx="4"/>'
            f'<text x="{min(width-105,120+w):.1f}" y="{y+15}" fill="{INK}" font-size="13">'
            f'{v:,.0f}원</text>'
        )
    parts.append(f'<text x="8" y="119" fill="{GRAY}" font-size="10">'
                 f'{escape(source)}</text></svg>')
    return "".join(parts)


def _font(size=20, bold=False):
    from PIL import ImageFont
    choices=[
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf" if bold
        else "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for name in choices:
        if Path(name).is_file():
            try:return ImageFont.truetype(name,size=size)
            except OSError:pass
    return ImageFont.load_default()


def _wrap(draw, value, font, max_width):
    """Break long Korean phrases by rendered pixel widths, not character count."""
    s=str(value or "")
    out=[]
    for paragraph in s.splitlines():
        line=""
        for char in paragraph:
            candidate=line+char
            if line and draw.textbbox((0,0),candidate,font=font)[2]>max_width:
                out.append(line)
                line=char
            else:line=candidate
        if line:out.append(line)
    return out


def _draw_text(draw, xy, message, font, fill, max_width, line_height, max_lines=4):
    x,y=xy
    for line in _wrap(draw,message,font,max_width)[:max_lines]:
        draw.text((x,y),line,font=font,fill=fill)
        y+=line_height
    return y


def png_summary(instrument, scores, price, price_stamp, prices=None,
                plan=None, target_summary=None, published_target=None):
    """Generate a real PNG (not JSON or screen capture), 1200 x 1700."""
    from PIL import Image, ImageDraw
    plan=plan or {}
    target_summary=target_summary or {}
    published_target=published_target or {}
    img=Image.new("RGB",(1200,1700),"#fffaf3")
    d=ImageDraw.Draw(img)
    ft_h=_font(48,True);ft_section=_font(29,True)
    ft_card=_font(40,True);ft_small=_font(19);ft_mid=_font(23)
    d.rounded_rectangle((38,35,1162,228),radius=24,fill="#eaf6ed",outline="#e9d9c3",width=2)
    d.rounded_rectangle((38,35,48,228),radius=4,fill=ORANGE)
    d.text((73,65),"STOCK ANALYZER  |  CREATED BY K.H.AHN",font=ft_small,fill="#ba6935")
    _draw_text(d,(73,109),f"{instrument.get('name','종목 미확인')}  ·  {instrument.get('code','')}",
               ft_h,INK,1050,56,1)
    d.text((73,185),f"기준: {price_stamp}  |  조건부 투자 검토자료",font=ft_small,fill=GRAY)

    blocks=[
        ("기준가격",f"{num(price):,.0f}원" if num(price) is not None else "미확인"),
        ("종합점수",f"{num(scores.get('total')):.1f} / 100" if num(scores.get('total')) is not None else "미산출"),
        ("데이터 충족률",f"{num(scores.get('coverage')):g}%" if num(scores.get('coverage')) is not None else "0%"),
    ]
    for i,(label,value) in enumerate(blocks):
        x1=40+i*380
        d.rounded_rectangle((x1,255,x1+357,382),radius=15,fill="#fffefa",
                            outline="#ead8bf",width=2)
        d.text((x1+18,273),label,font=ft_small,fill=GRAY)
        d.text((x1+18,314),value,font=ft_card,fill=GREEN)

    d.text((51,422),"항목별 정량점수",font=ft_section,fill=INK)
    for i,row in enumerate((scores.get("rows") or [])[:6]):
        y=479+i*57
        value=num(row.get("score"))
        total=num(row.get("weight")) or 0
        used=num(row.get("covered_weight")) or 0
        d.text((52,y+5),str(row.get("category","")),font=ft_mid,fill=INK)
        d.rounded_rectangle((293,y,986,y+29),radius=8,fill="#eeeae2")
        if value is not None and value>=0:
            right=293+max(1,693*min(100,value)/100)
            d.rounded_rectangle((293,y,right,y+29),radius=8,
                                fill=ORANGE if used<total else GREEN)
        value_text=(f"{value:.1f}{'*' if used<total else ''}"
                    if value is not None else "미산출")
        d.text((1007,y+3),value_text,font=ft_small,fill=INK)

    d.text((51,844),"주가 추이 (최근 최대 125거래일)",font=ft_section,fill=INK)
    d.rounded_rectangle((42,893,1157,1120),radius=14,fill="#fffefa",outline="#e9dbc7",width=2)
    hist=price_history(prices)
    if len(hist)>=2:
        values=[float(v) for v in hist["Close"]]
        lo,hi=min(values),max(values)
        if lo==hi:hi=lo+1
        coords=[]
        for i,v in enumerate(values):
            xx=65+1065*i/max(1,len(values)-1)
            yy=1092-168*(v-lo)/(hi-lo)
            coords.append((xx,yy))
        d.line(coords,fill=GREEN,width=5,joint="curve")
        d.text((66,1100),pd.Timestamp(hist.index[0]).strftime("%Y-%m-%d"),font=_font(15),fill=GRAY)
        d.text((943,1100),pd.Timestamp(hist.index[-1]).strftime("%Y-%m-%d"),font=_font(15),fill=GRAY)
        d.text((66,900),f"{hi:,.0f}원",font=_font(16),fill=GRAY)
    else:
        d.text((64,968),"조회 가능한 주가 이력이 부족합니다.",font=ft_mid,fill=GRAY)

    d.text((51,1141),"조건부 투자 대응",font=ft_section,fill=INK)
    for i,(title,key) in enumerate((("기존 보유자","holder"),("신규 매수 검토","new_buyer"))):
        x=42+i*568
        d.rounded_rectangle((x,1191,x+546,1489),radius=15,fill="#fffefa",
                            outline="#e8dac8",width=2)
        d.rectangle((x+15,1217,x+24,1255),fill=GREEN if i==0 else ORANGE)
        d.text((x+40,1214),title,font=ft_section,fill=INK)
        lines=(plan.get(key) or ["데이터가 부족하여 확인이 필요합니다."])[:2]
        y=1270
        for statement in lines:
            y=_draw_text(d,(x+21,y),"• "+statement,ft_small,INK,500,25,3)+10
    d.rounded_rectangle((42,1511,1158,1660),radius=12,fill="#fff0dc")
    d.text((59,1529),"검토 전 확인",font=ft_mid,fill="#ae642c")
    for i,txt in enumerate((plan.get("checkpoints") or [])[:3]):
        _draw_text(d,(59,1561+i*29),"• "+txt,ft_small,INK,1075,23,1)
    d.text((49,1673),"* 잠정/부분 점수 포함 · 투자 참고용 · 특정 매수·매도 지시가 아닙니다.",
           font=_font(14),fill=GRAY)
    buf=BytesIO()
    img.save(buf,format="PNG",optimize=True)
    return buf.getvalue()

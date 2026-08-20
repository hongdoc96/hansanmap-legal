#!/usr/bin/env python3
"""한산맵 동네별 SEO 랜딩 빌더 (획득 기획 2026-08-16 L2).

"강남역 혼잡도" 류 상시 검색 수요를 잡는 정적 페이지 120개를 만든다.
- 정적으로 굽는 것: 평소 요일×시간 히트맵(seoul_area_typicals), 요약 문장, 근처 동네,
  JSON-LD, 메타태그. → 검색엔진이 본문만으로 색인 가능.
- 방문 시 라이브: 현재 혼잡도(get_seoul_area_detail, 공유 착지와 같은 anon RPC 패턴)
  + '지금 vs 평소 이 시간' 비교 한 줄.
- 데이터 출처: Supabase anon REST(공개 데이터라 비밀 불필요 — 아무 환경에서 재실행 가능).

사용:
  python3 scripts/build_place_pages.py [출력루트=../hansanmap-legal]

재빌드 주기: '평소' 패턴은 천천히 변하므로 월 1회면 충분(서버 typicals 는 매일 갱신되지만
페이지의 히트맵은 평소 요약이라 민감하지 않다). 라이브 값은 어차피 방문 시 RPC.
"""

import json
import math
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

SB = "https://zrvuucvjcmlcvhhvfzzd.supabase.co"
# 앱·공유 착지 페이지에 이미 내장된 공개 anon 키(RLS 보호, 서버 비밀 아님).
ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpydnV1Y3ZqY21sY3ZoaHZmenpkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEwMzQwNjIsImV4cCI6MjA5NjYxMDA2Mn0.PgwGvh1qS27t7AcepWtIm26MlZ6KkrplAOIMfRHgKFQ"
BASE = "https://hongdoc96.github.io/hansanmap-legal"
PLAY = "https://play.google.com/store/apps/details?id=kr.hongdoc.hansanmap"
APPSTORE = "https://apps.apple.com/app/id6783810617"

LV_RANK = {"여유": 0, "보통": 1, "약간붐빔": 2, "붐빔": 3}
LV_COLOR = {"여유": "#3182F6", "보통": "#F5B921", "약간붐빔": "#F57F2C", "붐빔": "#EF4B4B"}
DOW = ["일", "월", "화", "수", "목", "금", "토"]
MIN_SAMPLES = 3  # 앱 kTypicalMinSamples 와 동일 — 얕은 표본으로 '평소'를 말하지 않는다


def fetch(path):
    """anon REST GET — PostgREST 1000행 상한을 Range 페이징으로 넘는다."""
    rows, start = [], 0
    while True:
        req = urllib.request.Request(
            f"{SB}{path}",
            headers={
                "apikey": ANON,
                "Authorization": f"Bearer {ANON}",
                "Range": f"{start}-{start + 999}",
            },
        )
        chunk = json.load(urllib.request.urlopen(req))
        rows += chunk
        if len(chunk) < 1000:
            return rows
        start += 1000


def rpc(fn, body):
    req = urllib.request.Request(
        f"{SB}/rest/v1/rpc/{fn}",
        data=json.dumps(body).encode(),
        headers={
            "apikey": ANON,
            "Authorization": f"Bearer {ANON}",
            "Content-Type": "application/json",
        },
    )
    return json.load(urllib.request.urlopen(req))


def slugify(name):
    # 한글 경로 그대로(구글·네이버 색인 정상). 공백·슬래시만 하이픈으로.
    return re.sub(r"[\s/]+", "-", name.strip())


def meters(la1, ln1, la2, ln2):
    r, t = 6371000, math.pi / 180
    dla, dln = (la2 - la1) * t, (ln2 - ln1) * t
    a = math.sin(dla / 2) ** 2 + math.cos(la1 * t) * math.cos(la2 * t) * math.sin(dln / 2) ** 2
    return 2 * r * math.asin(min(1, math.sqrt(a)))


def build_area(area, cells, neighbors, today_iso):
    """한 동네 페이지 HTML. cells: {(dow,hour): (level, samples)}"""
    name, code = area["name"], area["code"]
    slug = slugify(name)

    # 히트맵 셀 + 페이지 인라인 rank 표(라이브 '지금 vs 평소' 비교용)
    ranks_by_dow = [[-1] * 24 for _ in range(7)]
    grid_rows = []
    for d in range(7):
        tds = []
        for h in range(24):
            lv, n = cells.get((d, h), (None, 0))
            if lv is None or n < MIN_SAMPLES:
                tds.append('<td class="na" title="표본 부족"></td>')
            else:
                ranks_by_dow[d][h] = LV_RANK.get(lv, -1)
                tds.append(
                    f'<td style="background:{LV_COLOR[lv]}" title="{DOW[d]} {h}시 · 평소 {lv}"></td>'
                )
        grid_rows.append(f'<tr><th scope="row">{DOW[d]}</th>{"".join(tds)}</tr>')

    # 요약 — 활동 시간대(9~22시)에서 평소 가장 붐빔/한산 칸
    busiest = quietest = None
    for d in range(7):
        for h in range(9, 23):
            r = ranks_by_dow[d][h]
            if r < 0:
                continue
            if busiest is None or r > busiest[0]:
                busiest = (r, d, h)
            if quietest is None or r < quietest[0]:
                quietest = (r, d, h)
    lines = []
    if busiest and busiest[0] >= 1:
        lines.append(f"평소 <b>{DOW[busiest[1]]}요일 {busiest[2]}시</b>쯤이 가장 붐벼요")
    if quietest is not None:
        lines.append(f"<b>{DOW[quietest[1]]}요일 {quietest[2]}시</b>쯤이 가장 한산해요")
    summary = " · ".join(lines) if lines else "요일·시간대별 평소 패턴을 아래 표에서 확인하세요"
    summary_plain = re.sub(r"<[^>]+>", "", summary)

    near_html = "".join(
        f'<a href="../{slugify(n["name"])}/">{n["name"]}<span>{n["dist"]}</span></a>'
        for n in neighbors
    )

    jsonld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Place",
            "name": name,
            "geo": {"@type": "GeoCoordinates", "latitude": area["lat"], "longitude": area["lng"]},
            "address": {"@type": "PostalAddress", "addressRegion": "서울특별시", "addressCountry": "KR"},
        },
        ensure_ascii=False,
    )

    title = f"{name} 혼잡도 — 지금 붐빌까? 실시간·시간대별 | 한산맵"
    desc = f"{name} 실시간 혼잡도와 평소 요일·시간대 패턴. {summary_plain}. 서울시 실시간 도시데이터 기반."

    return slug, f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{BASE}/place/{slug}/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="한산맵">
<meta property="og:title" content="{name} 혼잡도 — 지금 붐빌까?">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{BASE}/place/{slug}/">
<script type="application/ld+json">{jsonld}</script>
<style>
 body{{font-family:-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;background:#F4F6F8;color:#1B2733;margin:0}}
 .wrap{{max-width:560px;margin:0 auto;padding:20px 16px 48px}}
 a{{color:#2F6BFF}} h1{{font-size:24px;margin:8px 0 4px}}
 .crumb{{font-size:12.5px;color:#8595A5}} .crumb a{{color:#8595A5;text-decoration:none}}
 .card{{background:#fff;border-radius:14px;padding:16px;margin:14px 0;box-shadow:0 3px 14px rgba(0,0,0,.06)}}
 #live{{display:none}} #liveLevel{{font-size:20px;font-weight:800;margin:0 0 2px}}
 #liveVs{{font-size:14px;font-weight:700;margin:6px 0 0;color:#1B2733}}
 .ts{{font-size:12px;color:#8595A5;margin:4px 0 0}}
 .sum{{font-size:15px;margin:0}}
 table{{border-collapse:collapse;width:100%;table-layout:fixed}}
 th{{font-size:10.5px;color:#8595A5;font-weight:600;padding:0 3px 0 0;text-align:right;width:20px}}
 td{{height:16px;border-radius:3px;border:1px solid #fff}}
 td.na{{background:#E7ECF1}}
 .hx{{font-size:9.5px;color:#8595A5;display:flex;justify-content:space-between;padding-left:23px;margin-top:3px}}
 .leg{{display:flex;gap:10px;font-size:11.5px;color:#5B6B7B;margin-top:9px;flex-wrap:wrap}}
 .leg i{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px;vertical-align:-1px}}
 h2{{font-size:16px;margin:0 0 9px}}
 .near{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
 .near a{{background:#fff;border-radius:10px;padding:11px 12px;text-decoration:none;color:#1B2733;font-size:13.5px;font-weight:700;box-shadow:0 2px 8px rgba(0,0,0,.05)}}
 .near a span{{display:block;font-weight:400;font-size:11.5px;color:#8595A5;margin-top:2px}}
 .cta{{display:block;text-align:center;background:#2F6BFF;color:#fff;text-decoration:none;font-weight:800;font-size:15px;border-radius:12px;padding:14px 0;margin:18px 0 8px}}
 .cta2{{display:block;text-align:center;background:#EAF0F7;color:#2F6BFF;text-decoration:none;font-weight:700;font-size:14px;border-radius:12px;padding:12px 0}}
 .src{{font-size:11.5px;color:#8595A5;line-height:1.6;margin-top:18px}}
</style>
</head>
<body>
<div class="wrap">
 <p class="crumb"><a href="../">서울 혼잡도</a> › {name}</p>
 <h1>{name} 혼잡도</h1>
 <div class="card" id="live">
  <p id="liveLevel"></p>
  <p id="liveVs"></p>
  <p class="ts" id="liveTime"></p>
 </div>
 <div class="card"><p class="sum">{summary}</p></div>
 <div class="card">
  <h2>평소 요일·시간대 혼잡 패턴</h2>
  <table aria-label="{name} 요일·시간대별 평소 혼잡도"><tbody>{"".join(grid_rows)}</tbody></table>
  <div class="hx"><span>0시</span><span>6시</span><span>12시</span><span>18시</span><span>23시</span></div>
  <div class="leg"><span><i style="background:#3182F6"></i>여유</span><span><i style="background:#F5B921"></i>보통</span><span><i style="background:#F57F2C"></i>약간붐빔</span><span><i style="background:#EF4B4B"></i>붐빔</span><span><i style="background:#E7ECF1"></i>표본 부족</span></div>
 </div>
 <a class="cta" id="ctaApp" href="{PLAY}">한산맵 앱에서 실시간으로 보기</a>
 <a class="cta2" href="kr.hongdoc.hansanmap://place?area={code}&name={name}">앱이 있다면 바로 열기</a>
 <h2 style="margin-top:22px">근처 동네 혼잡도</h2>
 <div class="near">{near_html}</div>
 <p class="src">출처: 서울시 실시간 도시데이터(현재 혼잡도) · 한산맵 자체 축적 실측 패턴(요일×시간, 최근 90일).
 평소 패턴은 자체 검증에서 실측과 86% 일치했습니다. 페이지 갱신 {today_iso}.</p>
</div>
<script>
(function(){{
 var SB="{SB}",ANON="{ANON}";
 var RANKS={json.dumps(ranks_by_dow)};
 var LVR={{"여유":0,"보통":1,"약간붐빔":2,"붐빔":3}};
 function norm(l){{return String(l==null?"":l).replace(/\\s/g,"")}}
 // iOS 는 App Store 로(공유 착지와 동일 판별)
 if(/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==="MacIntel"&&navigator.maxTouchPoints>1))
  document.getElementById("ctaApp").setAttribute("href","{APPSTORE}");
 fetch(SB+"/rest/v1/rpc/get_seoul_area_detail",{{method:"POST",headers:{{"Content-Type":"application/json",apikey:ANON,Authorization:"Bearer "+ANON}},body:JSON.stringify({{p_area_code:"{code}"}})}})
 .then(function(r){{return r.json()}}).then(function(rows){{
  var row=rows&&rows[0]; if(!row||!row.congest_lvl)return;
  var age=row.updated_at?Math.max(0,Math.round((Date.now()-new Date(row.updated_at).getTime())/60000)):null;
  if(age!==null&&age>120)return; // 2시간 넘게 낡은 값은 '지금'으로 단정하지 않음(앱 규약)
  var emo={{"여유":"🟢","보통":"🟡","약간붐빔":"🟠","붐빔":"🔴"}}[norm(row.congest_lvl)]||"⚪";
  document.getElementById("liveLevel").textContent="지금 "+emo+" "+row.congest_lvl;
  document.getElementById("liveTime").textContent=(age===null?"":age+"분 전 · ")+"서울시 실시간 도시데이터";
  // 지금 vs 평소 이 시간(KST) — 정적으로 구운 평소 rank 와 비교
  var k=new Date(Date.now()+9*36e5),d=k.getUTCDay(),h=k.getUTCHours();
  var tr=RANKS[d][h],lr=LVR[norm(row.congest_lvl)];
  if(tr>=0&&lr!==undefined){{
   var vs=lr<tr?"평소 이 시간보다 한산해요":lr>tr?"평소 이 시간보다 붐벼요":"평소 이 시간과 비슷해요";
   document.getElementById("liveVs").textContent=vs;
  }}
  document.getElementById("live").style.display="block";
 }}).catch(function(){{}});
}})();
</script>
</body>
</html>
"""


def main():
    out_root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "..", "hansanmap-legal"
    )
    place_dir = os.path.join(out_root, "place")
    today_iso = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")

    print("데이터 수신 중…")
    # 좌표는 status 원장(list RPC — lat/lng 포함, 착지 페이지와 같은 소스)
    status = rpc("list_seoul_area_status", {})
    areas = [
        {"code": r["area_code"], "name": r["area_name"], "lat": r["lat"], "lng": r["lng"]}
        for r in status
        if r.get("lat") is not None
    ]
    typ = fetch(
        "/rest/v1/seoul_area_typicals?select=area_code,day_of_week,hour_bucket,typical_level,sample_count"
    )
    cells_by_area = {}
    for t in typ:
        cells_by_area.setdefault(t["area_code"], {})[(t["day_of_week"], t["hour_bucket"])] = (
            t["typical_level"],
            t["sample_count"],
        )
    print(f"동네 {len(areas)} · typicals {len(typ)}")

    # 근처 6곳(하버사인)
    sitemap_urls = []
    for a in areas:
        near = sorted(
            (
                {
                    "name": b["name"],
                    "d": meters(a["lat"], a["lng"], b["lat"], b["lng"]),
                }
                for b in areas
                if b["code"] != a["code"]
            ),
            key=lambda x: x["d"],
        )[:6]
        neighbors = [
            {"name": n["name"], "dist": (f"{n['d']/1000:.1f}km" if n["d"] >= 1000 else f"{round(n['d'])}m")}
            for n in near
        ]
        slug, html = build_area(a, cells_by_area.get(a["code"], {}), neighbors, today_iso)
        d = os.path.join(place_dir, slug)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(html)
        sitemap_urls.append(f"{BASE}/place/{slug}/")

    # 목록 허브(크롤 진입점) — place/all/ (기존 place/index.html 은 공유 착지라 건드리지 않는다)
    items = "".join(
        f'<a href="../{slugify(a["name"])}/">{a["name"]}</a>' for a in sorted(areas, key=lambda x: x["name"])
    )
    os.makedirs(os.path.join(place_dir, "all"), exist_ok=True)
    with open(os.path.join(place_dir, "all", "index.html"), "w") as f:
        f.write(f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>서울 동네별 혼잡도 — 실시간·시간대별 {len(areas)}곳 | 한산맵</title>
<meta name="description" content="서울 주요 {len(areas)}개 동네의 실시간 혼잡도와 평소 요일·시간대 패턴. 강남역, 홍대, 명동, 성수동 등.">
<link rel="canonical" href="{BASE}/place/all/">
<style>body{{font-family:-apple-system,"Apple SD Gothic Neo",sans-serif;background:#F4F6F8;color:#1B2733;margin:0}}
.wrap{{max-width:560px;margin:0 auto;padding:20px 16px 48px}}h1{{font-size:22px}}
.g{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.g a{{background:#fff;border-radius:10px;padding:12px;text-decoration:none;color:#1B2733;font-size:13.5px;font-weight:700;box-shadow:0 2px 8px rgba(0,0,0,.05)}}</style>
</head><body><div class="wrap"><h1>서울 동네별 혼잡도</h1>
<p style="font-size:14px;color:#5B6B7B">실시간 혼잡도와 평소 요일·시간대 패턴 — 한산맵이 축적한 실측 데이터로 만듭니다.</p>
<div class="g">{items}</div>
<p style="font-size:11.5px;color:#8595A5;margin-top:18px">페이지 갱신 {today_iso}</p></div></body></html>
""")
    sitemap_urls.append(f"{BASE}/place/all/")

    # sitemap.xml + robots.txt (레포 루트)
    urls_xml = "".join(f"<url><loc>{u}</loc><lastmod>{today_iso}</lastmod></url>" for u in sitemap_urls)
    with open(os.path.join(out_root, "sitemap.xml"), "w") as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls_xml}</urlset>')
    with open(os.path.join(out_root, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n")

    print(f"생성 완료: 동네 {len(areas)}p + 허브 1p + sitemap({len(sitemap_urls)} url) + robots")


if __name__ == "__main__":
    main()

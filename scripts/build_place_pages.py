#!/usr/bin/env python3
"""한산맵 동네별 SEO 랜딩 빌더 (획득 기획 2026-08-16 L2).

"강남역 혼잡도" 류 상시 검색 수요를 잡는 정적 페이지 120개를 만든다.
- 정적으로 굽는 것: 평소 요일×시간 히트맵(seoul_area_typicals), 요약 문장, 요일별 표, 자주 묻는 질문,
  근처 동네, JSON-LD(Place·BreadcrumbList·FAQPage), 메타태그. → 검색엔진이 본문만으로 색인 가능.
- 방문 시 라이브: 현재 혼잡도(get_seoul_area_detail, 공유 착지와 같은 anon RPC 패턴)
  + '지금 vs 평소 이 시간' + 붐비면 언제 풀리는지(get_seoul_area_forecast) + 근처 동네 지금 혼잡도.
- 데이터 출처: Supabase anon REST(공개 데이터라 비밀 불필요 — 아무 환경에서 재실행 가능).

사용:
  python3 scripts/build_place_pages.py [출력루트=../hansanmap-legal] [--offline]

  --offline  네트워크 없이 기존 산출물(동네 페이지·sitemap)에서 입력을 복원해 템플릿만 다시 굽는다.
             데이터를 새로 받지 않으므로 페이지의 '패턴 집계일'은 앞당기지 않는다.
             템플릿을 바꾼 PR 을 주간 재빌드 전에 반영할 때, 그리고 CI 의 멱등성 검사(산출물이
             현재 템플릿과 일치하는가)에 쓴다.

재빌드 주기: 주 1회(.github/workflows/rebuild-places.yml). 라이브 값은 어차피 방문 시 RPC.
날짜 규약: 내용이 그대로면 파일도, 집계일도, sitemap lastmod 도 그대로 둔다 — 매주 모든 URL 의
lastmod 를 오늘로 찍으면 검색엔진이 lastmod 를 믿지 않게 된다.
"""

import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from html import escape

SB = "https://zrvuucvjcmlcvhhvfzzd.supabase.co"
# 앱·공유 착지 페이지에 이미 내장된 공개 anon 키(RLS 보호, 서버 비밀 아님).
ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpydnV1Y3ZqY21sY3ZoaHZmenpkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEwMzQwNjIsImV4cCI6MjA5NjYxMDA2Mn0.PgwGvh1qS27t7AcepWtIm26MlZ6KkrplAOIMfRHgKFQ"
BASE = "https://hongdoc96.github.io/hansanmap-legal"
PLAY = "https://play.google.com/store/apps/details?id=kr.hongdoc.hansanmap"
APPSTORE = "https://apps.apple.com/app/id6783810617"
# 공유 미리보기 카드 — scripts/make_og_image.py 가 굽는다.
# 없으면 카톡·SNS 공유 시 이미지 없는 카드가 뜬다(2026-09-09 실측: 경로 오타로 404였다).
OG_IMAGE = f"{BASE}/og-image.png"


def og_for(slug, have_cards):
    """동네 카드가 있으면 그것, 없으면 공통 카드.

    카드는 앱 저장소(scripts/make-og-image.py)에서 굽는다 — 폰트를 재배포하지 않으려고
    이 워크플로에서는 만들지 않는다. 그래서 새 동네가 생기면 카드가 없을 수 있고,
    그때 og:image 가 404 가 되지 않도록 폴백한다(2026-09-09 에 그 404 를 고쳤다).
    """
    return f"{BASE}/og/{urllib.parse.quote(slug)}.png" if slug in have_cards else OG_IMAGE


def canon(slug):
    """색인용 절대 URL — 한글 경로를 퍼센트 인코딩한다.

    sitemaps.org 규격이 loc 의 URL escape 를 요구한다. 브라우저는 raw 한글도 처리하지만
    크롤러는 규격대로 읽으므로 canonical·og:url·sitemap 을 같은 인코딩 형태로 맞춘다.
    """
    return f"{BASE}/place/{urllib.parse.quote(slug)}/"


def rel(slug):
    """동네 페이지끼리의 상대 링크 — canonical 과 같은 인코딩 형태."""
    return f"../{urllib.parse.quote(slug)}/"


LV_RANK = {"여유": 0, "보통": 1, "약간붐빔": 2, "붐빔": 3}
LV_NAME = ["여유", "보통", "약간붐빔", "붐빔"]
LV_COLOR = {"여유": "#3182F6", "보통": "#F5B921", "약간붐빔": "#F57F2C", "붐빔": "#EF4B4B"}
DOW = ["일", "월", "화", "수", "목", "금", "토"]
MIN_SAMPLES = 3  # 앱 kTypicalMinSamples 와 동일 — 얕은 표본으로 '평소'를 말하지 않는다

# 요약·표가 말하는 시간대 — 9~22시 버킷(= 09:00~23:00). 새벽의 '여유'로 한산함을 부풀리지 않는다.
ACTIVE = range(9, 23)
ACTIVE_LABEL = "9~23시"
# 글로 읽을 때의 요일 순서(월→일). 히트맵은 앱·공유 카드와 같게 일요일부터 그린다.
WEEK = [1, 2, 3, 4, 5, 6, 0]
RUNS_SHOWN = 3  # 한 문장에 싣는 구간 수 — 넘치면 '등'을 붙이고 표에 맡긴다


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


def js_json(obj):
    """<script> 안에 박는 JSON — 값에 '</script>' 가 들어도 태그가 닫히지 않게."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


# ─────────────────────────────────────────────────────────────────────────────
# 평소 패턴 해석 — 요약·표·FAQ 가 말하는 모든 문장의 근거
#
# 🔴 왜 다시 썼나(2026-09-29): 요약이 '가장 붐빔/가장 한산' 칸을 **한 칸**으로 골랐다.
#    동률이면 반복문이 먼저 만난 칸이 이겼고, 활동 시간의 대부분이 '여유'라 120곳 중 117곳이
#    "일요일 9시쯤이 가장 한산해요"라고 적고 있었다(일요일·9시가 반복의 첫 칸이라서).
#    붐빔도 같았다 — 강남역은 토요일 11~20시 내내 붐비는데 "월요일 19시"라고 적혔다.
#    그 문장이 meta description 으로 검색 결과에 그대로 나갔다.
#    이제 같은 단계의 칸을 **전부** 구간으로 모아 말하고, 각 주장에 근거 칸을 data-* 로 박아
#    scripts/check_places.py 가 히트맵 값과 대조한다(주장과 데이터가 갈리면 배포하지 않는다).
# ─────────────────────────────────────────────────────────────────────────────


def hour_runs(hours):
    """시각 목록 → 연속 구간 [(시작, 끝)] (끝 포함 버킷)."""
    out = []
    for h in sorted(set(hours)):
        if out and h == out[-1][1] + 1:
            out[-1][1] = h
        else:
            out.append([h, h])
    return [tuple(r) for r in out]


def fmt_run(s, e):
    # 버킷 h 는 h:00~h:59 — 구간은 끝 버킷의 다음 정시까지로 읽힌다(18~20 버킷 = 18~21시).
    return f"{s}시쯤" if s == e else f"{s}~{e + 1}시"


def fmt_runs(runs):
    shown = "·".join(fmt_run(s, e) for s, e in runs[:RUNS_SHOWN])
    return shown + (" 등" if len(runs) > RUNS_SHOWN else "")


def fmt_days(days):
    """요일 집합 → '평일'·'주말'·'매일'·'토요일'·'월·수~금'."""
    ds = [d for d in WEEK if d in set(days)]
    if len(ds) == 7:
        return "매일"
    if ds == [1, 2, 3, 4, 5]:
        return "평일"
    if ds == [6, 0]:
        return "주말"
    if len(ds) == 1:
        return f"{DOW[ds[0]]}요일"
    groups = []
    for i in (WEEK.index(d) for d in ds):
        if groups and i == groups[-1][-1] + 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    parts = []
    for g in groups:
        if len(g) >= 3:
            parts.append(f"{DOW[WEEK[g[0]]]}~{DOW[WEEK[g[-1]]]}")
        else:
            parts.extend(DOW[WEEK[i]] for i in g)
    return "·".join(parts)


def claim_attrs(kind, days, runs, rank, trunc=False):
    """주장의 근거 칸 — check_places.py 가 히트맵(RANKS)과 대조한다.

    kind: peak-all(전체 최고 단계) · peak-day(그 요일 최고) · low-day(그 요일 최저).
    trunc: 문장에 다 싣지 못하고 '등'으로 끊었다 — 완전성(빠진 칸 없음) 검사를 면제한다.
    """
    hours = ",".join(f"{s}-{e}" for s, e in runs)
    days_s = ",".join(str(d) for d in days)
    t = ' data-trunc="1"' if trunc else ""
    return f'data-claim="{kind}" data-days="{days_s}" data-hours="{hours}" data-rank="{rank}"{t}'


def analyze(ranks):
    """ranks[d][h] (-1 = 표본 부족) → 요일별·전체 패턴. 표본이 하나도 없으면 None."""
    days = {}
    for d in range(7):
        vals = {h: ranks[d][h] for h in ACTIVE if ranks[d][h] >= 0}
        if not vals:
            days[d] = None
            continue
        peak, low = max(vals.values()), min(vals.values())
        days[d] = {
            "peak": peak,
            "low": low,
            "peak_runs": hour_runs(h for h, r in vals.items() if r == peak),
            "low_runs": hour_runs(h for h, r in vals.items() if r == low),
            "load": sum(vals.values()) / len(vals),
        }
    have = [d for d in WEEK if days[d]]
    if not have:
        return None
    top = max(days[d]["peak"] for d in have)

    # 전체 최고 단계의 구간 — 같은 시간 구간을 가진 요일끼리 묶고, 칸 수가 많은 구간부터.
    # (한 칸으로 줄이지 않는다. 동률은 동률대로 전부 말하고, 넘치면 '등' + 표에 맡긴다.)
    by_run = {}
    for d in have:
        if days[d]["peak"] == top:
            for run in days[d]["peak_runs"]:
                by_run.setdefault(run, []).append(d)
    peaks = sorted(
        by_run.items(),
        key=lambda kv: (-(len(kv[1]) * (kv[0][1] - kv[0][0] + 1)), WEEK.index(kv[1][0]), kv[0][0]),
    )

    # 가장 붐비는 요일(평균 단계) — 문장에는 '가장'을 쓰지 않는다('붐비는 토요일에도 …').
    # 동률이면 주중 앞쪽이 걸리는데, 어느 쪽이든 그 요일의 한산 구간은 사실이다.
    busy_day = max(have, key=lambda d: (days[d]["load"], -WEEK.index(d)))

    wds = [days[d]["load"] for d in (1, 2, 3, 4, 5) if days[d]]
    cells = [ranks[d][h] for d in have for h in ACTIVE if ranks[d][h] >= 0]
    quiet_pct = round(100 * sum(1 for r in cells if r == 0) / len(cells))
    return {
        "days": days,
        "top": top,
        "peaks": peaks,
        "busy_day": busy_day,
        "weekday": sum(wds) / len(wds) if wds else None,
        "quiet_pct": quiet_pct,
    }


def weekend_vs_weekday(a):
    """토·일을 **따로** 평일 평균과 비교한다.

    ⚠️ 주말을 평균 내면 안 된다 — 강남역은 토요일이 가장 붐비는 요일인데 일요일이 한산해서
       주말 평균이 평일보다 낮게 나오고, "평일이 주말보다 붐벼요"라는 참이지만 오해를 부르는 문장이 됐다.
       0.15 단계 미만 차이는 '비슷'(활동 14시간 중 두어 시간이 한 단계 다른 정도).
    """
    wd = a["weekday"]
    if wd is None:
        return ""
    cmp = {}
    for d in (6, 0):
        x = a["days"][d]
        if x is not None:
            diff = x["load"] - wd
            cmp[d] = "same" if abs(diff) < 0.15 else ("more" if diff > 0 else "less")
    if not cmp:
        return ""
    if len(cmp) == 2 and len(set(cmp.values())) == 1:
        return {
            "same": "평일과 주말의 혼잡 정도가 비슷해요",
            "more": "주말(토·일)이 평일보다 붐비는 편이에요",
            "less": "주말(토·일)이 평일보다 한산한 편이에요",
        }[cmp[6]]
    mid = {"same": "평일과 비슷하고", "more": "평일보다 붐비고", "less": "평일보다 한산하고"}
    end = {"same": "평일과 비슷해요", "more": "평일보다 붐비는 편이에요", "less": "평일보다 한산한 편이에요"}
    ds = [d for d in (6, 0) if d in cmp]
    parts = [f"{DOW[d]}요일은 {mid[cmp[d]]}" for d in ds[:-1]]
    parts.append(f"{DOW[ds[-1]]}요일은 {end[cmp[ds[-1]]]}")
    return ", ".join(parts)


def describe(a):
    """패턴 → 요약 문장(HTML·평문)·요일별 표·FAQ 답. 모든 '가장'은 동률 전체를 말한다."""
    if a is None:
        busy_html = busy = "아직 평소 패턴을 말할 만큼 표본이 쌓이지 않았어요"
        return {
            "busy_html": busy_html, "busy": busy, "quiet_html": "", "quiet": "",
            "week": "", "rows": [], "faq": [],
        }
    days, top = a["days"], a["top"]

    # ① 가장 붐비는 때
    shown = a["peaks"][:RUNS_SHOWN]
    trunc = len(a["peaks"]) > RUNS_SHOWN
    segs_plain = [f"{fmt_days(ds)} {fmt_run(*run)}" for run, ds in shown]
    segs_html = [
        f'<b {claim_attrs("peak-all", ds, [run], top)}>{escape(p)}</b>'
        for (run, ds), p in zip(shown, segs_plain)
    ]
    more = " 등" if trunc else ""
    if top == 0:
        busy = busy_html = "평소엔 요일·시간대와 관계없이 여유로운 편이에요"
    elif top == 1:
        busy = f"평소 {', '.join(segs_plain)}{more}에 가장 북적이지만 '보통' 수준이에요"
        busy_html = f"평소 {', '.join(segs_html)}{more}에 가장 북적이지만 '보통' 수준이에요"
    else:
        busy = f"평소 {', '.join(segs_plain)}{more}에 가장 붐벼요({LV_NAME[top]})"
        busy_html = f"평소 {', '.join(segs_html)}{more}에 가장 붐벼요({LV_NAME[top]})"
    busy_attr = ' data-trunc="1"' if trunc else ""

    # ② 한산하게 가려면 — 붐비는 요일에도 비는 구간을 말한다(검색자가 실제로 묻는 것)
    bd = a["busy_day"]
    day = days[bd]
    pct = f"활동 시간({ACTIVE_LABEL}) 기준으로 평소 {a['quiet_pct']}%가 여유예요"
    if top == 0:
        quiet = quiet_html = pct
    elif day["low"] < day["peak"]:
        tail = "여유로운 편이에요" if day["low"] == 0 else f"덜 붐벼요({LV_NAME[day['low']]})"
        runs_txt = fmt_runs(day["low_runs"])
        quiet = f"붐비는 {DOW[bd]}요일에도 {runs_txt}엔 {tail}"
        t = len(day["low_runs"]) > RUNS_SHOWN
        attrs = claim_attrs("low-day", [bd], day["low_runs"][:RUNS_SHOWN], day["low"], t)
        quiet_html = f"붐비는 {DOW[bd]}요일에도 <b {attrs}>{escape(runs_txt)}</b>엔 {tail}"
    else:
        quiet = quiet_html = f"{DOW[bd]}요일은 활동 시간 내내 '{LV_NAME[day['peak']]}' 수준이에요"

    # ③ 평일 vs 토·일
    week = weekend_vs_weekday(a)

    # ④ 요일별 표(월→일) — 그 요일 기준 가장 북적이는 때·가장 한산한 때.
    #    이웃한 요일의 줄이 똑같으면 한 줄로 합친다(한산한 동네가 '종일 여유'를 일곱 번 말하지 않게).
    per_day = []  # (d, 붐빔 글, 한산 글, 붐빔 근거, 한산 근거) — 근거 = (kind, runs, rank, trunc)
    for d in WEEK:
        x = days[d]
        if x is None:
            per_day.append((d, "표본 부족", "표본 부족", None, None))
        elif x["peak"] == 0:
            per_day.append((d, "붐비는 시간 없음", "종일 여유", None, ("low-day", tuple(x["low_runs"]), 0, False)))
        else:
            peak_txt = f"{fmt_runs(x['peak_runs'])} ({LV_NAME[x['peak']]})"
            peak_c = ("peak-day", tuple(x["peak_runs"][:RUNS_SHOWN]), x["peak"], len(x["peak_runs"]) > RUNS_SHOWN)
            if x["low"] < x["peak"]:
                low_txt = f"{fmt_runs(x['low_runs'])} ({LV_NAME[x['low']]})"
                low_c = ("low-day", tuple(x["low_runs"][:RUNS_SHOWN]), x["low"], len(x["low_runs"]) > RUNS_SHOWN)
            else:
                low_txt, low_c = "—", None
            per_day.append((d, peak_txt, low_txt, peak_c, low_c))
    groups = []
    for rec in per_day:
        if groups and groups[-1][-1][1:] == rec[1:]:
            groups[-1].append(rec)
        else:
            groups.append([rec])
    rows = []
    for g in groups:
        ds = [r[0] for r in g]
        _, peak_txt, low_txt, peak_c, low_c = g[0]
        label = DOW[ds[0]] if len(ds) == 1 else fmt_days(ds)
        pa = claim_attrs(peak_c[0], ds, list(peak_c[1]), peak_c[2], peak_c[3]) if peak_c else ""
        la = claim_attrs(low_c[0], ds, list(low_c[1]), low_c[2], low_c[3]) if low_c else ""
        rows.append((label, peak_txt, low_txt, pa, la))

    # ⑤ 자주 묻는 질문 — 답은 위 문장과 같은 사실만(FAQPage JSON-LD 도 이 글자 그대로)
    faq = [("언제 가장 붐비나요?", busy + ".")]
    faq.append(("한산하게 가려면 언제 가야 하나요?", quiet + "." + ("" if top == 0 else f" {pct}.")))
    if week:
        busy_bits = [
            f"{DOW[d]}요일 {fmt_runs(days[d]['peak_runs'])}({LV_NAME[days[d]['peak']]})"
            for d in (6, 0) if days[d] and days[d]["peak"] > 0
        ]
        calm = [d for d in (6, 0) if days[d] and days[d]["peak"] == 0]
        detail = f" 주말에 가장 북적이는 때 — {', '.join(busy_bits)}." if busy_bits else ""
        if calm:
            detail += f" {fmt_days(calm)}엔 종일 여유로운 편이에요."
        faq.append(("주말에도 붐비나요?", week + "." + detail))

    return {
        "busy_html": busy_html, "busy": busy, "busy_attr": busy_attr,
        "quiet_html": quiet_html, "quiet": quiet,
        "week": week, "rows": rows, "faq": faq,
    }


AREAS_BEGIN = "/* AREAS:BEGIN */"
AREAS_END = "/* AREAS:END */"


def inject_landing_areas(place_dir, areas):
    """공유 착지 페이지(place/index.html)에 동네 코드→[이름, slug] 표를 박는다.

    🔴 왜 주입인가(2026-09-15): 착지 페이지가 제목을 URL 의 `name` 으로 쓰고 있었다.
       `?area=POI054&name=홍대` 면 제목은 '홍대' 인데 그 아래 혼잡도 카드는 혜화역 값이다.
       링크를 만드는 사람이 우리 브랜드·서울시 실데이터 위에 아무 문장이나 얹을 수 있었다.
       이제 제목의 근거는 이 표뿐이고, 표의 출처는 서버(list_seoul_area_status)다.

    ⚠️ slug 를 여기서 함께 굽는 이유: 착지 페이지가 정적 패턴 페이지로 링크를 거는데,
       slugify 규칙을 JS 에 한 벌 더 쓰면 언젠가 갈려서 없는 경로로 보낸다.
    """
    path = os.path.join(place_dir, "index.html")
    if not os.path.exists(path):
        print("  ⚠️ 착지 페이지 없음 — 주입 생략")
        return
    with open(path, encoding="utf-8") as f:
        html = f.read()
    b, e = html.find(AREAS_BEGIN), html.find(AREAS_END)
    if b < 0 or e < 0 or e < b:
        raise SystemExit(f"착지 페이지에 {AREAS_BEGIN} … {AREAS_END} 펜스가 없다 — 주입할 자리가 사라졌다")
    table = {a["code"]: [a["name"], slugify(a["name"])] for a in sorted(areas, key=lambda x: x["code"])}
    body = json.dumps(table, ensure_ascii=False, separators=(",", ":"))
    out = (
        html[:b]
        + AREAS_BEGIN
        + "\n    var AREA_NAMES = "
        + body
        + ";\n    "
        + html[e:]
    )
    if out != html:
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
    print(f"  착지 페이지 제목 표 주입: {len(table)}곳")


def meters(la1, ln1, la2, ln2):
    r, t = 6371000, math.pi / 180
    dla, dln = (la2 - la1) * t, (ln2 - ln1) * t
    a = math.sin(dla / 2) ** 2 + math.cos(la1 * t) * math.cos(la2 * t) * math.sin(dln / 2) ** 2
    return 2 * r * math.asin(min(1, math.sqrt(a)))


# 동네 페이지와 허브가 같이 쓰는 라이브 규약 조각(JS)
JS_COMMON = """ var SB="%(SB)s",ANON="%(ANON)s";
 var LVR={"여유":0,"보통":1,"약간붐빔":2,"붐빔":3};
 var COL={"여유":"#3182F6","보통":"#F5B921","약간붐빔":"#F57F2C","붐빔":"#EF4B4B"};
 var STALE=72e5; // 2시간 넘게 낡은 값은 '지금'으로 단정하지 않는다(앱 정직성 규약)
 function norm(l){return String(l==null?"":l).replace(/\\s/g,"")}
 function $(id){return document.getElementById(id)}
 function rpc(fn,body){return fetch(SB+"/rest/v1/rpc/"+fn,{method:"POST",headers:{"Content-Type":"application/json",apikey:ANON,Authorization:"Bearer "+ANON},body:JSON.stringify(body||{})}).then(function(r){return r.json()})}
 function fresh(r){var t=r&&r.updated_at?new Date(r.updated_at).getTime():0;return t>0&&Date.now()-t<=STALE}
 // iOS 는 App Store 로(공유 착지와 동일 판별 — iPadOS 13+ 는 UA 가 Macintosh 라 터치포인트로 보강)
 var IOS=/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==="MacIntel"&&navigator.maxTouchPoints>1);
 function storeLinks(ids){if(IOS)ids.forEach(function(id){var el=$(id);if(el)el.setAttribute("href","%(APPSTORE)s")})}
""" % {"SB": SB, "ANON": ANON, "APPSTORE": APPSTORE}


def build_area(area, cells, neighbors, data_date, have_cards=frozenset()):
    """한 동네 페이지 HTML. cells: {(dow,hour): (level, samples)}"""
    name, code = area["name"], area["code"]
    slug = slugify(name)
    og = og_for(slug, have_cards)
    n = escape(name)

    # 히트맵 셀 + 페이지 인라인 rank 표(라이브 '지금 vs 평소' 비교·근거 대조용)
    ranks_by_dow = [[-1] * 24 for _ in range(7)]
    grid_rows = []
    for d in range(7):
        tds = []
        for h in range(24):
            lv, cnt = cells.get((d, h), (None, 0))
            if lv is None or cnt < MIN_SAMPLES or lv not in LV_RANK:
                tds.append('<td class="na" title="표본 부족"></td>')
            else:
                ranks_by_dow[d][h] = LV_RANK[lv]
                tds.append(
                    f'<td style="background:{LV_COLOR[lv]}" title="{DOW[d]} {h}시 · 평소 {lv}"></td>'
                )
        grid_rows.append(f'<tr><th scope="row">{DOW[d]}</th>{"".join(tds)}</tr>')

    t = describe(analyze(ranks_by_dow))

    day_rows = "".join(
        f'<tr><th scope="row">{label}</th><td {pa}>{escape(pt)}</td><td {la}>{escape(lt)}</td></tr>'
        .replace("<td >", "<td>")
        for label, pt, lt, pa, la in t["rows"]
    )
    faq_html = "".join(
        f"<h3>{n}, {escape(q)}</h3><p>{escape(ans)}</p>" for q, ans in t["faq"]
    )
    near_html = "".join(
        f'<a href="{rel(slugify(x["name"]))}" data-c="{escape(x["code"])}">{escape(x["name"])}'
        f'<span>{x["dist"]}</span><span class="lv"></span></a>'
        for x in neighbors
    )

    url = canon(slug)
    ld = [
        {
            "@context": "https://schema.org",
            "@type": "Place",
            "name": name,
            "url": url,
            "geo": {"@type": "GeoCoordinates", "latitude": area["lat"], "longitude": area["lng"]},
            "address": {"@type": "PostalAddress", "addressRegion": "서울특별시", "addressCountry": "KR"},
        },
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "한산맵", "item": f"{BASE}/"},
                {"@type": "ListItem", "position": 2, "name": "서울 동네 혼잡도", "item": f"{BASE}/place/all/"},
                {"@type": "ListItem", "position": 3, "name": f"{name} 혼잡도", "item": url},
            ],
        },
    ]
    if t["faq"]:
        ld.append(
            {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": f"{name}, {q}",
                        "acceptedAnswer": {"@type": "Answer", "text": ans},
                    }
                    for q, ans in t["faq"]
                ],
            }
        )
    ld_html = "\n".join(f'<script type="application/ld+json">{js_json(o)}</script>' for o in ld)

    title = f"{name} 혼잡도 — 지금 붐빌까? 실시간·시간대별 | 한산맵"
    desc = f"{name} 실시간 혼잡도와 평소 요일·시간대 패턴. {t['busy']}."
    if t["quiet"]:
        desc += f" {t['quiet']}."
    d_ = escape(desc)
    week_html = f'<p class="wk">{escape(t["week"])}</p>' if t["week"] else ""
    quiet_html = f'<p class="sum2">{t["quiet_html"]}</p>' if t["quiet_html"] else ""
    deep = f"kr.hongdoc.hansanmap://place?area={urllib.parse.quote(code)}&amp;name={urllib.parse.quote(name)}"

    return slug, f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{d_}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="한산맵">
<meta property="og:locale" content="ko_KR">
<meta property="og:title" content="{n} 혼잡도 — 지금 붐빌까?">
<meta property="og:description" content="{d_}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{og}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{n} 요일·시간대별 평소 혼잡도">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{n} 혼잡도 — 지금 붐빌까?">
<meta name="twitter:description" content="{d_}">
<meta name="twitter:image" content="{og}">
{ld_html}
<style>
 body{{font-family:-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;background:#F4F6F8;color:#1B2733;margin:0}}
 .wrap{{max-width:560px;margin:0 auto;padding:20px 16px 48px}}
 a{{color:#2F6BFF}} h1{{font-size:24px;margin:8px 0 4px}}
 .crumb{{font-size:12.5px;color:#8595A5;margin:0}} .crumb a{{color:#8595A5;text-decoration:none}}
 .card{{background:#fff;border-radius:14px;padding:16px;margin:14px 0;box-shadow:0 3px 14px rgba(0,0,0,.06)}}
 #live{{display:none}} #liveLevel{{font-size:20px;font-weight:800;margin:0 0 2px}}
 #liveVs{{font-size:14px;font-weight:700;margin:6px 0 0;color:#1B2733}}
 #liveEase{{display:none;font-size:14px;font-weight:700;margin:4px 0 0;color:#1B2733}}
 .ts{{font-size:12px;color:#8595A5;margin:4px 0 0}}
 .sum{{font-size:15px;margin:0;line-height:1.55}}
 .sum2{{font-size:14px;margin:8px 0 0;line-height:1.55;color:#33414F}}
 .wk{{font-size:12.5px;margin:8px 0 0;color:#8595A5}}
 #hm{{border-collapse:collapse;width:100%;table-layout:fixed}}
 #hm th{{font-size:10.5px;color:#8595A5;font-weight:600;padding:0 3px 0 0;text-align:right;width:20px}}
 #hm td{{height:16px;border-radius:3px;border:1px solid #fff}}
 #hm td.na{{background:#E7ECF1}}
 #hm td.now{{outline:2px solid #1B2733;outline-offset:-1px}}
 #hmNow{{display:none;font-size:11.5px;color:#5B6B7B;margin:7px 0 0}}
 .hx{{font-size:9.5px;color:#8595A5;display:flex;justify-content:space-between;padding-left:23px;margin-top:3px}}
 .leg{{display:flex;gap:10px;font-size:11.5px;color:#5B6B7B;margin-top:9px;flex-wrap:wrap}}
 .leg i{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px;vertical-align:-1px}}
 h2{{font-size:16px;margin:0 0 9px}}
 .days{{border-collapse:collapse;width:100%;font-size:13px}}
 .days th,.days td{{padding:7px 4px;border-bottom:1px solid #EEF1F4;text-align:left;vertical-align:top;word-break:keep-all}}
 .days thead th{{font-size:11.5px;color:#8595A5;font-weight:600}}
 .days tbody th{{width:26px;font-weight:700;white-space:nowrap}}
 .near{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
 .near a{{background:#fff;border-radius:10px;padding:11px 12px;text-decoration:none;color:#1B2733;font-size:13.5px;font-weight:700;box-shadow:0 2px 8px rgba(0,0,0,.05)}}
 .near a span{{display:block;font-weight:400;font-size:11.5px;color:#8595A5;margin-top:2px}}
 .near a span.lv{{display:none;font-weight:700}} .near a span.lv.on{{display:block}}
 .faq h3{{font-size:14px;margin:14px 0 4px}} .faq h3:first-of-type{{margin-top:0}}
 .faq p{{font-size:13.5px;color:#33414F;margin:0;line-height:1.6}}
 #liveCta{{display:inline-block;margin:11px 0 0;font-size:13.5px;font-weight:800;color:#2F6BFF;text-decoration:none}}
 .ctaWhy{{font-size:13px;color:#5B6B7B;text-align:center;margin:20px 0 7px;line-height:1.5}}
 .cta{{display:block;text-align:center;background:#2F6BFF;color:#fff;text-decoration:none;font-weight:800;font-size:15px;border-radius:12px;padding:14px 0;margin:18px 0 8px}}
 .cta2{{display:block;text-align:center;background:#EAF0F7;color:#2F6BFF;text-decoration:none;font-weight:700;font-size:14px;border-radius:12px;padding:12px 0}}
 .src{{font-size:11.5px;color:#8595A5;line-height:1.6;margin-top:18px}}
</style>
</head>
<body>
<div class="wrap">
 <nav class="crumb" aria-label="현재 위치"><a href="../../">한산맵</a> › <a href="../all/">서울 동네 혼잡도</a> › {n}</nav>
 <h1>{n} 혼잡도</h1>
 <div class="card" id="live">
  <p id="liveLevel"></p>
  <p id="liveVs"></p>
  <p id="liveEase"></p>
  <p class="ts" id="liveTime"></p>
  <a id="liveCta" href="{PLAY}">한산해지면 알림 받기 →</a>
 </div>
 <div class="card"><p class="sum" id="sumBusy"{t.get("busy_attr", "")}>{t["busy_html"]}</p>{quiet_html}{week_html}</div>
 <div class="card">
  <h2>평소 요일·시간대 혼잡 패턴</h2>
  <table id="hm" aria-label="{n} 요일·시간대별 평소 혼잡도"><tbody>{"".join(grid_rows)}</tbody></table>
  <div class="hx"><span>0시</span><span>6시</span><span>12시</span><span>18시</span><span>23시</span></div>
  <div class="leg"><span><i style="background:#3182F6"></i>여유</span><span><i style="background:#F5B921"></i>보통</span><span><i style="background:#F57F2C"></i>약간붐빔</span><span><i style="background:#EF4B4B"></i>붐빔</span><span><i style="background:#E7ECF1"></i>표본 부족</span></div>
  <p id="hmNow"></p>
 </div>
 <div class="card">
  <h2>요일별 붐비는 때·한산한 때</h2>
  <table class="days"><thead><tr><th scope="col">요일</th><th scope="col">가장 북적이는 때</th><th scope="col">가장 한산한 때</th></tr></thead><tbody>{day_rows}</tbody></table>
  <p class="ts">활동 시간({ACTIVE_LABEL}) 기준 · 그 요일 안에서 비교</p>
 </div>
 <p class="ctaWhy">앱에서 별표해두면 이 동네가 한산해질 때 알려드려요</p>
 <a class="cta" id="ctaApp" href="{PLAY}">한산해지면 알림 받기</a>
 <a class="cta2" href="{deep}">앱이 있다면 바로 열기</a>
 <h2 style="margin-top:22px">근처 동네 혼잡도</h2>
 <div class="near">{near_html}</div>
 <div class="card faq">
  <h2>자주 묻는 질문</h2>
  {faq_html}
 </div>
 <p class="src">출처: 서울시 실시간 도시데이터(현재 혼잡도) · 한산맵 자체 축적 실측 패턴(요일×시간, 최근 90일).
 평소 패턴은 자체 검증에서 실측과 86% 일치했습니다. 패턴 집계 <time datetime="{data_date}">{data_date}</time>.</p>
</div>
<script>
(function(){{
{JS_COMMON} var CODE={js_json(code)},NAME={js_json(name)};
 var RANKS={js_json(ranks_by_dow)};
 var EMO={{"여유":"🟢","보통":"🟡","약간붐빔":"🟠","붐빔":"🔴"}};
 function kst(t){{var k=new Date(t+9*36e5);return {{d:k.getUTCDay(),h:k.getUTCHours(),day:Math.floor((t+9*36e5)/864e5)}}}}
 storeLinks(["ctaApp","liveCta"]);
 var now=kst(Date.now());
 // 히트맵의 '지금' 칸 — 평소 패턴을 지금 시각(KST)에 대어 읽게 한다
 var hm=$("hm"),tr=hm&&hm.rows&&hm.rows[now.d],cell=tr&&tr.cells&&tr.cells[now.h+1];
 if(cell){{cell.className+=" now";$("hmNow").textContent="테두리 칸이 지금("+"일월화수목금토".charAt(now.d)+"요일 "+now.h+"시)이에요";$("hmNow").style.display="block"}}
 // 붐빌 때만 — 12시간 예측에서 '지금보다 낮은 단계가 지속되는' 첫 시각(공유 착지·앱과 같은 규약).
 // 한 시간 반짝 낮아지는 값으로 약속을 만들지 않는다. 자정을 넘기면 '내일'을 붙인다.
 function easeAt(my){{
  rpc("get_seoul_area_forecast",{{p_area_name:NAME}}).then(function(rows){{
   if(!rows||!rows.length)return;
   var pts=[],i;
   for(i=0;i<rows.length;i++){{if(rows[i].is_current||!rows[i].target_at)continue;pts.push({{t:new Date(rows[i].target_at).getTime(),r:LVR[norm(rows[i].level)]}})}}
   pts.sort(function(a,b){{return a.t-b.t}});
   for(i=0;i<pts.length;i++){{
    if(pts[i].r===undefined||pts[i].r>=my)continue;
    var nx=pts[i+1];if(nx&&(nx.r===undefined||nx.r>=my))continue;
    var at=kst(pts[i].t);
    $("liveEase").textContent=(at.day>now.day?"내일 ":"")+at.h+"시 이후 풀릴 것으로 예상돼요";
    $("liveEase").style.display="block";return;
   }}
  }}).catch(function(){{}});
 }}
 rpc("get_seoul_area_detail",{{p_area_code:CODE}}).then(function(rows){{
  var row=rows&&rows[0];if(!row||!row.congest_lvl)return;
  var age=row.updated_at?Math.max(0,Math.round((Date.now()-new Date(row.updated_at).getTime())/60000)):null;
  if(age!==null&&age*6e4>STALE)return;
  var lv=norm(row.congest_lvl),lr=LVR[lv];
  $("liveLevel").textContent="지금 "+(EMO[lv]||"⚪")+" "+row.congest_lvl;
  $("liveTime").textContent=(age===null?"":age+"분 전 · ")+"서울시 실시간 도시데이터";
  var usual=RANKS[now.d][now.h];
  if(usual>=0&&lr!==undefined)$("liveVs").textContent=lr<usual?"평소 이 시간보다 한산해요":lr>usual?"평소 이 시간보다 붐벼요":"평소 이 시간과 비슷해요";
  $("live").style.display="block";
  if(lr>=2)easeAt(lr);
 }}).catch(function(){{}});
 // 근처 동네의 지금 — 붐비는 동네에서 '그럼 어디로'를 같은 화면에서 답한다. 순서(거리)는 바꾸지 않는다.
 rpc("list_seoul_area_status").then(function(rows){{
  if(!Array.isArray(rows))return;
  var by={{}};rows.forEach(function(r){{by[r.area_code]=r}});
  var list=document.querySelectorAll(".near a[data-c]");
  for(var i=0;i<list.length;i++){{
   var r=by[list[i].getAttribute("data-c")];if(!fresh(r))continue;
   var c=COL[norm(r.congestion_level)];if(!c)continue;
   var el=list[i].querySelector(".lv");el.textContent="● 지금 "+r.congestion_level;el.style.color=c;el.className="lv on";
  }}
 }}).catch(function(){{}});
}})();
</script>
</body>
</html>
"""


def build_hub(areas, list_date):
    """목록 허브(크롤 진입점) — place/all/."""
    items = "".join(
        f'<a href="{rel(slugify(a["name"]))}" data-c="{escape(a["code"])}">{escape(a["name"])}<span class="lv"></span></a>'
        for a in sorted(areas, key=lambda x: x["name"])
    )
    n = len(areas)
    ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "한산맵", "item": f"{BASE}/"},
            {"@type": "ListItem", "position": 2, "name": "서울 동네 혼잡도", "item": f"{BASE}/place/all/"},
        ],
    }
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>서울 동네별 혼잡도 — 실시간·시간대별 {n}곳 | 한산맵</title>
<meta name="description" content="서울 주요 {n}개 동네의 실시간 혼잡도와 평소 요일·시간대 패턴. 강남역, 홍대, 명동, 성수동 등.">
<link rel="canonical" href="{BASE}/place/all/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="한산맵">
<meta property="og:locale" content="ko_KR">
<meta property="og:title" content="서울 동네별 혼잡도 {n}곳">
<meta property="og:description" content="서울 주요 {n}개 동네의 실시간 혼잡도와 평소 요일·시간대 패턴.">
<meta property="og:url" content="{BASE}/place/all/">
<meta property="og:image" content="{OG_IMAGE}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{OG_IMAGE}">
<script type="application/ld+json">{js_json(ld)}</script>
<style>body{{font-family:-apple-system,"Apple SD Gothic Neo",sans-serif;background:#F4F6F8;color:#1B2733;margin:0}}
.wrap{{max-width:560px;margin:0 auto;padding:20px 16px 48px}}h1{{font-size:22px}}
.crumb{{font-size:12.5px;color:#8595A5;margin:0}} .crumb a{{color:#8595A5;text-decoration:none}}
.g{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.g a{{background:#fff;border-radius:10px;padding:12px;text-decoration:none;color:#1B2733;font-size:13.5px;font-weight:700;box-shadow:0 2px 8px rgba(0,0,0,.05)}}
.g .lv{{display:none;font-size:11.5px;font-weight:700;margin-top:4px}}
.g .lv.on{{display:block}}
.g.quiet a:not(.q0){{display:none}}
#onlyQuiet{{display:none;margin:0 0 12px;border:0;border-radius:10px;padding:10px 14px;background:#EAF0FF;color:#2F6BFF;font-weight:800;font-size:13.5px;cursor:pointer}}
.ctaWhy{{font-size:13px;color:#5B6B7B;text-align:center;margin:22px 0 7px;line-height:1.5}}
.cta{{display:block;text-align:center;background:#2F6BFF;color:#fff;text-decoration:none;font-weight:800;font-size:15px;border-radius:12px;padding:14px 0}}
#liveNote{{display:none;font-size:12px;color:#8595A5;margin:9px 0 0}}</style>
</head><body><div class="wrap"><nav class="crumb" aria-label="현재 위치"><a href="../../">한산맵</a> › 서울 동네 혼잡도</nav>
<h1>서울 동네별 혼잡도</h1>
<p style="font-size:14px;color:#5B6B7B">실시간 혼잡도와 평소 요일·시간대 패턴 — 한산맵이 축적한 실측 데이터로 만듭니다.</p>
<button type="button" id="onlyQuiet"></button>
<div class="g" id="grid">{items}</div>
<p id="liveNote"></p>
<p class="ctaWhy">앱에서 별표해두면 그 동네가 한산해질 때 알려드려요</p>
<a class="cta" id="ctaApp" href="{PLAY}">한산해지면 알림 받기</a>
<p style="font-size:11.5px;color:#8595A5;margin-top:18px">목록 갱신 <time datetime="{list_date}">{list_date}</time></p></div>
<script>
(function(){{
{JS_COMMON} storeLinks(["ctaApp"]);
 // 목록은 정적으로 이름순이다(크롤러가 보는 순서). 라이브는 색과 등급만 입힌다 — 재정렬하지 않는다.
 rpc("list_seoul_area_status").then(function(rows){{
  if(!Array.isArray(rows))return;
  var by={{}},newest=0;
  rows.forEach(function(r){{by[r.area_code]=r;var t=r.updated_at?new Date(r.updated_at).getTime():0;if(t>newest)newest=t}});
  var n=0,q=0,list=document.querySelectorAll(".g a[data-c]");
  for(var i=0;i<list.length;i++){{
   var a=list[i],r=by[a.getAttribute("data-c")];if(!fresh(r))continue; // 낡은 값은 동네마다 거른다
   var lv=norm(r.congestion_level),c=COL[lv];if(!c)continue;
   var el=a.querySelector(".lv");el.textContent="● "+r.congestion_level;el.style.color=c;el.className="lv on";n++;
   if(lv==="여유"){{a.className="q0";q++}}
  }}
  if(!n)return;
  var m=Math.max(0,Math.round((Date.now()-newest)/60000));
  $("liveNote").textContent="지금 혼잡도 "+n+"곳 · "+m+"분 전 · 서울시 실시간 도시데이터";
  $("liveNote").style.display="block";
  // '지금 어디가 한산한지' 한 번에 — 여유인 곳만 남기는 필터(정적 목록은 그대로, 보기만 바꾼다)
  if(!q)return;
  var b=$("onlyQuiet"),g=$("grid"),on=false,label="지금 여유로운 곳만 보기 ("+q+"곳)";
  b.textContent=label;b.style.display="inline-block";
  b.onclick=function(){{on=!on;g.className=on?"g quiet":"g";b.textContent=on?"전체 "+list.length+"곳 보기":label}};
 }}).catch(function(){{}});
}})();
</script>
</body></html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# 날짜·변경 판정 — 내용이 그대로면 아무것도 건드리지 않는다
# ─────────────────────────────────────────────────────────────────────────────

DATE_RES = [
    re.compile(r'<time datetime="(\d{4}-\d{2}-\d{2})"'),
    re.compile(r"페이지 갱신 (\d{4}-\d{2}-\d{2})"),  # 2026-09-29 이전 템플릿
]


def page_date(html):
    for rx in DATE_RES:
        m = rx.search(html)
        if m:
            return m.group(1)
    return None


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def write_page(path, render, today, keep_date):
    """render(date) → html. 바뀌었으면 쓰고 True.

    - 옛 날짜로 다시 구워 옛 파일과 같으면 → 데이터·템플릿 모두 그대로. 손대지 않는다.
    - 다르면: keep_date(오프라인 — 데이터를 새로 받지 않았다)면 옛 날짜를 유지하고,
      아니면 오늘 받은 데이터이므로 오늘 날짜로 굽는다.
    """
    old = read(path)
    old_date = page_date(old) if old else None
    if old_date:
        same = render(old_date)
        if same == old:
            return False
        html = same if keep_date else render(today)
    else:
        html = render(today)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return True


def old_lastmods(out_root):
    sm = read(os.path.join(out_root, "sitemap.xml")) or ""
    return dict(re.findall(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>", sm))


def ld_objects(html):
    out = []
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        o = json.loads(m.group(1))
        out.extend(o.get("@graph", [o]) if isinstance(o, dict) else o)
    return out


def load_offline(out_root):
    """기존 산출물에서 빌드 입력을 복원한다(네트워크 없음).

    순서는 sitemap(서버 목록 순서 그대로 구워졌다), 이름·좌표는 Place JSON-LD,
    코드·rank 는 페이지 스크립트에서. 표본 수는 페이지에 없으므로 rank 가 있는 칸은
    MIN_SAMPLES 로 복원한다(같은 칸이 같은 색으로 다시 구워진다).
    """
    sm = read(os.path.join(out_root, "sitemap.xml"))
    if not sm:
        raise SystemExit("--offline: sitemap.xml 이 없다 — 복원할 산출물이 없다(온라인 빌드가 먼저다)")
    prefix = f"{BASE}/place/"
    slugs = [
        urllib.parse.unquote(u[len(prefix):].rstrip("/"))
        for u in re.findall(r"<loc>([^<]+)</loc>", sm)
        if u.startswith(prefix) and u != f"{prefix}all/"
    ]
    areas, cells_by_area = [], {}
    for slug in slugs:
        page = read(os.path.join(out_root, "place", slug, "index.html"))
        if page is None:
            raise SystemExit(f"--offline: sitemap 의 place/{slug}/ 페이지가 없다")
        place = next(o for o in ld_objects(page) if o.get("@type") == "Place")
        code = re.search(r'(?:CODE=|p_area_code:)"(POI\d+)"', page).group(1)
        ranks = json.loads(re.search(r"var RANKS=(\[\[.*?\]\]);", page).group(1))
        if slugify(place["name"]) != slug:
            raise SystemExit(f"--offline: {slug} 의 이름 {place['name']!r} 이 slug 와 갈린다")
        areas.append({"code": code, "name": place["name"],
                      "lat": place["geo"]["latitude"], "lng": place["geo"]["longitude"]})
        cells_by_area[code] = {
            (d, h): (LV_NAME[r], MIN_SAMPLES)
            for d, row in enumerate(ranks) for h, r in enumerate(row) if r >= 0
        }
    return areas, cells_by_area


def load_online():
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
    return areas, cells_by_area


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    offline = "--offline" in sys.argv
    out_root = args[0] if args else os.path.join(os.path.dirname(__file__), "..", "..", "hansanmap-legal")
    place_dir = os.path.join(out_root, "place")
    og_dir = os.path.join(out_root, "og")
    have_cards = frozenset(
        f[:-4] for f in os.listdir(og_dir) if f.endswith(".png")
    ) if os.path.isdir(og_dir) else frozenset()
    today_iso = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")

    if offline:
        print("오프라인 — 기존 산출물에서 입력 복원")
        areas, cells_by_area = load_offline(out_root)
    else:
        print("데이터 수신 중…")
        areas, cells_by_area = load_online()

    lastmods = old_lastmods(out_root)
    sitemap = []  # (url, lastmod)
    changed = 0

    # 근처 6곳(하버사인)
    for a in areas:
        near = sorted(
            (
                {"name": b["name"], "code": b["code"], "d": meters(a["lat"], a["lng"], b["lat"], b["lng"])}
                for b in areas
                if b["code"] != a["code"]
            ),
            key=lambda x: x["d"],
        )[:6]
        neighbors = [
            {"name": x["name"], "code": x["code"],
             "dist": (f"{x['d']/1000:.1f}km" if x["d"] >= 1000 else f"{round(x['d'])}m")}
            for x in near
        ]
        cells = cells_by_area.get(a["code"], {})
        slug = slugify(a["name"])
        path = os.path.join(place_dir, slug, "index.html")
        hit = write_page(
            path,
            lambda date: build_area(a, cells, neighbors, date, have_cards)[1],
            today_iso,
            keep_date=offline,
        )
        changed += hit
        url = canon(slug)
        sitemap.append((url, today_iso if hit else lastmods.get(url, today_iso)))

    # 목록 허브(크롤 진입점) — place/all/
    # (place/index.html 은 공유 착지라 본문은 손으로 관리하고, 제목 표만 펜스 사이에 주입한다)
    hub_url = f"{BASE}/place/all/"
    hit = write_page(os.path.join(place_dir, "all", "index.html"),
                     lambda date: build_hub(areas, date), today_iso, keep_date=False)
    changed += hit
    sitemap.append((hub_url, today_iso if hit else lastmods.get(hub_url, today_iso)))

    # 공유 착지 페이지의 제목 근거 표(코드→[이름, slug]) 갱신 — 본문은 손으로 관리한다.
    inject_landing_areas(place_dir, areas)

    # 루트는 손으로 관리한다 — lastmod 는 옛 값을 잇는다(없으면 오늘).
    root_url = f"{BASE}/"
    sitemap.append((root_url, lastmods.get(root_url, today_iso)))

    # sitemap.xml + robots.txt (레포 루트)
    urls_xml = "".join(f"<url><loc>{u}</loc><lastmod>{m}</lastmod></url>" for u, m in sitemap)
    with open(os.path.join(out_root, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls_xml}</urlset>')
    with open(os.path.join(out_root, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n")

    print(f"생성 완료: 동네 {len(areas)}p + 허브 1p + sitemap({len(sitemap)} url) + robots"
          f" · 바뀐 페이지 {changed} · 동네 카드 {len(have_cards)}장 연결")


if __name__ == "__main__":
    main()

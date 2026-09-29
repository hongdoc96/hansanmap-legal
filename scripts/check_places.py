#!/usr/bin/env python3
"""동네 SEO 페이지(place/<동네>/ · place/all/) 계약 검사 — 빌드 뒤에 돌린다.

🔴 무엇을 막나(2026-09-29):
   ① 요약이 '가장 붐빔/가장 한산' 을 **한 칸**으로 골랐다. 동률이면 반복문이 먼저 만난 칸이 이겨
      120곳 중 117곳이 "일요일 9시쯤이 가장 한산해요"라고 적었고, 그 문장이 meta description 으로
      검색 결과에 나갔다. 강남역은 토요일 11~20시 내내 붐비는데 "월요일 19시"라고 적혔다.
      → 이제 모든 주장이 근거 칸(data-days·data-hours·data-rank)을 달고, 여기서 히트맵(RANKS)과
        대조한다. 빌더의 문장 로직을 다시 쓰지 않고 **데이터만으로** 참·거짓을 판정한다.
   ② 동네 페이지 빵부스러기 '서울 혼잡도'가 `../` — 허브가 아니라 공유 착지(앱 스킴으로 자동 이동하는
      '한산맵에서 열기' 껍데기)로 갔다. 120장 전부가 크롤러와 사람을 막다른 페이지로 보내고 있었다.
   ③ 루트에 viewport 가 없어 모바일에서 데스크톱 폭으로 축소 렌더됐다(모바일 우선 색인).

검사:
  A. sitemap ↔ 파일: sitemap 의 URL 마다 파일이 있고, 동네 페이지는 전부 sitemap 에 있다.
     착지·투표는 sitemap 밖이고 noindex 다. sitemap 안의 페이지는 noindex 가 아니고 viewport 가 있다.
  B. 동네 페이지: canonical = og:url = sitemap URL, og:image 파일 존재, JSON-LD 전부 파싱,
     Place 이름 = h1, BreadcrumbList 끝 = canonical, 빵부스러기가 착지(`../`)로 새지 않는다.
  C. 상대 링크는 전부 실제 파일에 닿는다(허브·근처 동네·빵부스러기).
  D. 주장 대조(①): 근거 칸의 값이 전부 data-rank 이고, 그 rank 가 주장한 극값(전체 최고·그 요일
     최고·그 요일 최저)이며, '등'으로 끊지 않았다면 같은 극값의 칸을 빠짐없이 덮는다.
  E. FAQPage JSON-LD 의 질문·답 = 화면의 질문·답(글자 그대로).

사용: python3 scripts/check_places.py [저장소루트=.]
      python3 scripts/check_places.py [저장소루트=.] --self-test   # 돌연변이로 검사기 자체 검증
"""

import html as H
import json
import os
import re
import sys
import urllib.parse

BASE = "https://hongdoc96.github.io/hansanmap-legal"
ACTIVE = range(9, 23)  # 빌더와 같은 활동 시간 — 주장의 극값은 이 안에서 잰다
NOINDEX = re.compile(r'<meta name="robots" content="[^"]*noindex')
VIEWPORT = re.compile(r"<meta name=[\"']?viewport")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def url_to_path(root, url):
    assert url.startswith(BASE + "/"), f"사이트 밖 URL: {url}"
    rel = urllib.parse.unquote(url[len(BASE) + 1:])
    return os.path.join(root, rel, "index.html") if rel.endswith("/") or rel == "" else os.path.join(root, rel)


def meta(html, attr, key):
    m = re.search(rf'<meta {attr}="{re.escape(key)}" content="([^"]*)"', html)
    return H.unescape(m.group(1)) if m else None


def ld_objects(html, where):
    out = []
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            out.append(json.loads(m.group(1)))
        except json.JSONDecodeError as e:
            raise AssertionError(f"{where}: JSON-LD 파싱 실패 — {e}")
    return out


def resolve(root, page_path, href):
    """상대 href → 저장소 안 파일 경로(없으면 None 이 아니라 그 경로를 돌려준다)."""
    target = urllib.parse.unquote(href.split("#")[0].split("?")[0])
    p = os.path.normpath(os.path.join(os.path.dirname(page_path), target))
    return os.path.join(p, "index.html") if href.endswith("/") else p


def check_links(root, page_path, html):
    for href in re.findall(r"""<a [^>]*href=["']([^"']+)["']""", html):
        href = H.unescape(href)
        if re.match(r"^[a-z][a-z0-9.+-]*:", href) or href.startswith("#"):
            continue  # 외부·앱 스킴·앵커
        p = resolve(root, page_path, href)
        assert os.path.exists(p), f"{page_path}: 링크 {href!r} 가 없는 파일로 간다 ({p})"


def check_claims(html, where):
    """D. 주장 ↔ 히트맵 대조. 빌더의 문장 로직과 독립 — RANKS 와 data-* 만 본다."""
    m = re.search(r"var RANKS=(\[\[.*?\]\]);", html)
    assert m, f"{where}: RANKS 가 없다"
    ranks = json.loads(m.group(1))

    def active(days):
        return [ranks[d][h] for d in days for h in ACTIVE if ranks[d][h] >= 0]

    all_vals = active(range(7))
    top = max(all_vals) if all_vals else None
    claims = re.findall(
        r'<(b|td) data-claim="([a-z-]+)" data-days="([\d,]+)" data-hours="([\d,-]+)" data-rank="(\d)"( data-trunc="1")?',
        html,
    )
    peak_all_cells, peak_all_trunc = set(), 'id="sumBusy" data-trunc="1"' in html
    n_peak_all = 0
    for _tag, kind, days_s, hours_s, rank_s, trunc in claims:
        days = [int(x) for x in days_s.split(",")]
        rank = int(rank_s)
        runs = [tuple(int(x) for x in part.split("-")) for part in hours_s.split(",")]
        cells = {(d, h) for d in days for s, e in runs for h in range(s, e + 1)}
        for d, h in sorted(cells):
            assert h in ACTIVE, f"{where}: {kind} 주장이 활동 시간 밖({h}시)을 말한다"
            assert ranks[d][h] == rank, (
                f"{where}: {kind} 주장 {days_s}/{hours_s} 의 {d}요일 {h}시가 실제 {ranks[d][h]} (주장 {rank})")
        # 구간은 극대여야 한다 — 같은 단계가 앞뒤로 이어지는데 잘라 말하면 동률을 한 칸으로 줄이는
        # 옛 결함과 같은 모양이다. '등'으로 끊은 문장(완전성 면제)도 이것만은 지켜야 한다.
        for d in days:
            for s, e in runs:
                for edge in (s - 1, e + 1):
                    assert not (edge in ACTIVE and ranks[d][edge] == rank), (
                        f"{where}: {kind} 주장 {d}요일 {s}-{e} 가 극대 구간이 아니다({edge}시도 같은 단계) — 같은 단계 칸을 빠뜨렸다")
        if kind == "peak-all":
            n_peak_all += 1
            assert rank == top, f"{where}: '가장 붐빔' 주장이 최고 단계({top})가 아니다({rank})"
            peak_all_cells |= cells
        elif kind in ("peak-day", "low-day"):
            # 요일마다 따로 잰다 — 표가 똑같은 이웃 요일을 한 줄로 합쳐도 주장은 각 요일에 대해 참이어야 한다.
            for d in days:
                vals = active([d])
                want = max(vals) if kind == "peak-day" else min(vals)
                assert rank == want, f"{where}: {kind} {d}요일 극값은 {want} 인데 {rank} 를 주장"
                if not trunc:
                    every = {(d, h) for h in ACTIVE if ranks[d][h] == rank}
                    missing = every - cells
                    assert not missing, f"{where}: {kind} {d}요일에서 같은 단계 칸을 빠뜨렸다 {sorted(missing)[:4]}"
        else:
            raise AssertionError(f"{where}: 모르는 주장 종류 {kind}")
    # '가장 붐빔'은 동률 전체를 말해야 한다 — 한 칸으로 줄이는 것이 이 검사가 막는 결함 그 자체다.
    if top and top > 0:
        assert n_peak_all > 0, f"{where}: 최고 단계가 {top} 인데 '가장 붐빔' 주장이 없다"
        if not peak_all_trunc:
            every = {(d, h) for d in range(7) for h in ACTIVE if ranks[d][h] == top}
            missing = every - peak_all_cells
            assert not missing, f"{where}: '가장 붐빔'이 같은 단계 칸을 빠뜨렸다 {sorted(missing)[:4]}"
    # 근거 없는 최상급 문장 금지 — 옛 결함의 모양('…쯤이 가장 한산해요')
    assert "가장 한산해요" not in html, f"{where}: 근거 칸 없는 '가장 한산해요' 문장"
    return len(claims)


def check_faq(html, where):
    """E. FAQPage JSON-LD = 화면의 질문·답."""
    shown = [(H.unescape(q), H.unescape(a)) for q, a in re.findall(r"<h3>(.*?)</h3><p>(.*?)</p>", html)]
    faq = [o for o in ld_objects(html, where) if o.get("@type") == "FAQPage"]
    if not shown:
        assert not faq, f"{where}: 화면에 없는 FAQ 를 구조화 데이터로만 싣는다"
        return
    assert len(faq) == 1, f"{where}: FAQPage 가 {len(faq)}개"
    ld = [(e["name"], e["acceptedAnswer"]["text"]) for e in faq[0]["mainEntity"]]
    assert ld == shown, f"{where}: FAQ 구조화 데이터가 화면과 다르다\n  화면 {shown[:1]}\n  LD   {ld[:1]}"


def check(root):
    sitemap = read(os.path.join(root, "sitemap.xml"))
    urls = re.findall(r"<loc>([^<]+)</loc>", sitemap)
    assert len(urls) == len(set(urls)), "sitemap 에 중복 URL"
    listed = {os.path.normpath(url_to_path(root, u)): u for u in urls}

    # A. sitemap ↔ 파일 · 색인 여부
    for path, u in listed.items():
        assert os.path.exists(path), f"sitemap 의 {u} 파일이 없다"
        page = read(path)
        assert not NOINDEX.search(page), f"sitemap 에 실은 {u} 가 noindex 다"
        assert VIEWPORT.search(page), f"{u}: viewport 가 없다 — 모바일에서 축소 렌더된다"
    place = os.path.join(root, "place")
    area_dirs = sorted(
        d for d in os.listdir(place)
        if d != "all" and os.path.isfile(os.path.join(place, d, "index.html"))
    )
    assert len(area_dirs) >= 100, f"동네 페이지가 {len(area_dirs)}장뿐 — 스캐너가 못 보고 있다"
    for private in ("place/index.html", "poll/index.html"):
        p = os.path.normpath(os.path.join(root, private))
        assert p not in listed, f"{private} 는 색인 대상이 아닌데 sitemap 에 있다"
        assert NOINDEX.search(read(p)), f"{private} 에 noindex 가 없다 — 쿼리 껍데기가 검색에 걸린다"

    # B·C·D·E. 동네 페이지
    n_claims = 0
    for slug in area_dirs:
        path = os.path.normpath(os.path.join(place, slug, "index.html"))
        where = f"place/{slug}/"
        assert path in listed, f"{where} 가 sitemap 에 없다"
        html = read(path)
        url = listed[path]
        canon = re.search(r'<link rel="canonical" href="([^"]+)"', html)
        assert canon and canon.group(1) == url, f"{where}: canonical {canon and canon.group(1)} ≠ sitemap {url}"
        assert meta(html, "property", "og:url") == url, f"{where}: og:url ≠ canonical"
        og = meta(html, "property", "og:image")
        assert og and os.path.exists(url_to_path(root, og)), f"{where}: og:image {og} 파일이 없다"
        objs = ld_objects(html, where)
        placed = [o for o in objs if o.get("@type") == "Place"]
        h1 = re.search(r"<h1>(.*?) 혼잡도</h1>", html)
        assert placed and h1 and placed[0]["name"] == H.unescape(h1.group(1)), f"{where}: Place 이름 ≠ h1"
        crumbs = [o for o in objs if o.get("@type") == "BreadcrumbList"]
        assert crumbs and crumbs[0]["itemListElement"][-1]["item"] == url, f"{where}: BreadcrumbList 끝이 이 페이지가 아니다"
        # ② 빵부스러기가 공유 착지로 새지 않는다 — `../` 는 place/index.html(앱 스킴 자동 이동)이다.
        assert 'href="../"' not in html, f"{where}: `../` 링크 — 허브가 아니라 공유 착지로 간다"
        assert 'href="../all/"' in html, f"{where}: 허브로 가는 빵부스러기가 없다"
        check_links(root, path, html)
        n_claims += check_claims(html, where)
        check_faq(html, where)

    hub = os.path.join(place, "all", "index.html")
    check_links(root, hub, read(hub))
    check_links(root, os.path.join(root, "index.html"), read(os.path.join(root, "index.html")))
    return len(area_dirs), n_claims


# ─────────────────────────────────────────────────────────────────────────────
# 자체 검증 — 돌연변이를 먹여 검사가 실제로 잡는지 본다(초록이 커버리지인지)
# ─────────────────────────────────────────────────────────────────────────────

GANGNAM = "place/강남역/index.html"


def _sub(pattern, repl, count=1):
    def f(s):
        out, n = re.subn(pattern, repl, s, count=count)
        assert n, f"돌연변이 앵커가 없다: {pattern}"
        return out
    return f


MUTATIONS = [
    # (설명, 대상 파일, 변환, 기대하는 실패 문구) — 엉뚱한 이유로 실패하면 잡은 게 아니다.
    ("빵부스러기를 옛 `../`(공유 착지)로", GANGNAM,
     _sub(r'<a href="\.\./all/">', '<a href="../">'), "공유 착지로 간다"),
    ("'가장 붐빔'을 한 칸으로 줄이기(옛 결함)", GANGNAM,
     _sub(r'(data-claim="peak-all" data-days=")[\d,]+(" data-hours=")\d+-\d+', r"\g<1>6\g<2>12-12"),
     "같은 단계 칸을 빠뜨렸다"),
    ("'등'으로 끊고도 끊지 않은 척하기(동률 구간 누락)", GANGNAM,
     _sub(r'id="sumBusy" data-trunc="1"', 'id="sumBusy"'), "같은 단계 칸을 빠뜨렸다"),
    ("한산 주장의 단계를 속이기", GANGNAM,
     _sub(r'(data-claim="low-day" data-days="\d" data-hours="[\d,-]+" data-rank=")0', r"\g<1>1"), "실제 0 (주장 1)"),
    ("근거 없는 옛 요약 문장 되살리기", GANGNAM,
     _sub(r'<p class="sum2">', '<p class="sum2"><b>일요일 9시</b>쯤이 가장 한산해요 · '), "근거 칸 없는"),
    ("FAQ 구조화 데이터만 몰래 바꾸기", GANGNAM,
     _sub(r'("acceptedAnswer":\{"@type":"Answer","text":")', r"\g<1>언제나 한산해요. "), "화면과 다르다"),
    ("근처 동네 링크를 없는 경로로", GANGNAM,
     _sub(r'(<div class="near"><a href=")[^"]+"', r'\g<1>../%EC%97%86%EB%8A%94%EB%8F%99%EB%84%A4/"'),
     "없는 파일로 간다"),
    ("canonical 을 다른 동네로", GANGNAM,
     _sub(r'(<link rel="canonical" href=")[^"]+"', rf'\g<1>{BASE}/place/%EC%97%AD%EC%82%BC%EC%97%AD/"'),
     "≠ sitemap"),
    ("공유 착지의 noindex 빼기", "place/index.html",
     _sub(r'\s*<meta name="robots" content="noindex" />', ""), "noindex 가 없다"),
    ("루트 viewport 빼기", "index.html",
     _sub(r"<meta name=viewport content='[^']*'>", ""), "viewport 가 없다"),
    ("sitemap 에서 동네 하나 빼기", "sitemap.xml",
     _sub(r"<url><loc>[^<]*%EA%B0%95%EB%82%A8%EC%97%AD/</loc><lastmod>[^<]*</lastmod></url>", ""),
     "sitemap 에 없다"),
]


def self_test(root):
    import shutil
    import tempfile

    n, c = check(root)
    print(f"  원본 통과 ✓ (동네 {n} · 주장 {c})")
    for label, rel, mutate, expect in MUTATIONS:
        base = tempfile.mkdtemp()
        tmp = os.path.join(base, "repo")
        try:
            # 저장소 통째로 — 일부만 복사하면 '파일 없음'으로 엉뚱하게 실패해 돌연변이를 잡은 척한다
            # (첫 판이 그랬다: 약관 페이지를 빠뜨려 모든 돌연변이가 루트 링크 검사에서 걸렸다).
            shutil.copytree(root, tmp, ignore=shutil.ignore_patterns(".git"))
            target = os.path.join(tmp, rel)
            src = read(target)
            mutated = mutate(src)
            assert mutated != src, f"{label}: 돌연변이가 아무것도 바꾸지 않았다"
            with open(target, "w", encoding="utf-8") as f:
                f.write(mutated)
            try:
                check(tmp)
            except AssertionError as ex:
                msg = str(ex)
                if expect not in msg:
                    raise SystemExit(f"🔴 {label}: 엉뚱한 이유로 실패했다 — 기대 {expect!r}, 실제 {msg[:120]!r}")
                print(f"  {label} → 잡힘 ✓ ({msg.splitlines()[0][:70]})")
                continue
            raise SystemExit(f"🔴 {label} 를 검사가 놓쳤다 — 이 계약은 장식이다")
        finally:
            shutil.rmtree(base, ignore_errors=True)
    print(f"돌연변이 {len(MUTATIONS)}종 전부 검출 — 계약이 실제로 본다")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    repo = args[0] if args else "."
    if "--self-test" in sys.argv:
        self_test(repo)
    else:
        n, c = check(repo)
        print(f"동네 페이지 계약 통과 — {n}곳 · 주장 {c}건 대조")

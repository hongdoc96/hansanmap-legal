#!/usr/bin/env python3
"""공유 착지 페이지(place/index.html) 계약 검사 — 빌드 뒤에 돌린다.

🔴 무엇을 막나(2026-09-15): 착지 페이지가 제목을 URL 의 `name` 으로 쓰고 있었다.
   `?area=POI054&name=홍대` 면 제목은 '홍대' 인데 그 아래 혼잡도 카드는 혜화역 값이다.
   링크를 만드는 사람이 우리 브랜드·서울시 실데이터·설치 버튼 위에 아무 문장이나 얹을 수 있었다.
   증상이 조용하다 — 페이지는 200 이고 카드도 정상이라 눈으로는 어긋난 걸 알 수 없다.

검사 넷:
  ① 제목 표(AREA_NAMES)가 비어 있지 않다 — 주입이 조용히 빠지면 모든 동네 링크가 무제목이 된다
  ② 허브(place/all/)가 아는 코드와 이름이 표와 일치한다 — 두 산출물이 갈리지 않게
  ③ 표의 slug 마다 실제 정적 페이지가 있다 — 출구 링크가 404 로 가지 않게
  ④ URL 의 `name` 은 **area 가 없을 때만** 제목이 될 수 있다 (구멍의 형태 자체를 잠근다)

사용: python3 scripts/check_landing.py [저장소루트=.]
      python3 scripts/check_landing.py --self-test   # 검사기 자체 검증(돌연변이)
"""

import json
import os
import re
import sys

BEGIN, END = "/* AREAS:BEGIN */", "/* AREAS:END */"
# ④ 의 앵커 — 값이 URL 이 아니라 표에서 온다는 것, 그리고 URL 폴백이 area 부재로 막혀 있다는 것.
KNOWN_ANCHOR = "var known = area ? AREA_NAMES[area] : null;"
URL_NAME_GUARDED = "(area ? null : params.get('name'))"
TITLE_ANCHOR = "document.getElementById('title').textContent"


def strip_comments(src):
    """`//` 주석을 **줄 끝까지** 지운다 — 줄 머리든 줄 끝이든.

    ⚠️ 줄 머리만 지우면 부족하다. 자체 검증에서 실제로 뚫렸다 —
       `var known = null; // var known = area ? AREA_NAMES[area] : null;` 는
       앵커가 주석 쪽에서 매치돼 검사를 그대로 통과했다(원본을 지운 게 아니라 옮긴 것이다).
    ⚠️ 그렇다고 `//` 를 무조건 자르면 URL 이 잘린다(`https://…`, `kr.hongdoc.hansanmap://place`).
       둘 다 바로 앞이 `:` 라 그 경우만 건너뛴다.
    """
    out = []
    for ln in src.split("\n"):
        i, cut = 0, None
        while True:
            j = ln.find("//", i)
            if j < 0:
                break
            if j > 0 and ln[j - 1] == ":":  # https:// · scheme://
                i = j + 2
                continue
            cut = j
            break
        out.append(ln if cut is None else ln[:cut])
    return "\n".join(out)


def area_table(landing_html):
    b, e = landing_html.find(BEGIN), landing_html.find(END)
    if b < 0 or e < 0 or e < b:
        raise AssertionError("AREAS 펜스가 없다 — 빌더가 제목 표를 넣을 자리를 잃었다")
    m = re.search(r"var AREA_NAMES\s*=\s*(\{.*\})\s*;", landing_html[b:e], re.S)
    if not m:
        raise AssertionError("펜스 안에 AREA_NAMES 대입이 없다")
    return json.loads(m.group(1))


def check(root):
    landing_path = os.path.join(root, "place", "index.html")
    with open(landing_path, encoding="utf-8") as f:
        landing = f.read()
    table = area_table(landing)

    # ① 표가 비어 있지 않다. 주입 실패는 조용하다 — 하한을 걸어 '아무것도 안 봤음'과 구분한다.
    assert len(table) >= 100, f"제목 표가 {len(table)}곳뿐 — 주입이 빠졌다(서울 동네는 120곳)"

    # ② 허브와 갈리지 않는다. 같은 빌드가 두 파일을 쓰므로 어긋나면 그 자체가 결함 신호다.
    hub_path = os.path.join(root, "place", "all", "index.html")
    with open(hub_path, encoding="utf-8") as f:
        hub = f.read()
    hub_pairs = re.findall(r'data-c="(POI\d+)">([^<]+)<', hub)
    assert len(hub_pairs) >= 100, f"허브에서 읽은 동네가 {len(hub_pairs)}곳뿐 — 스캐너가 못 보고 있다"
    for code, name in hub_pairs:
        assert code in table, f"허브에 있는 {code}({name})가 제목 표에 없다"
        assert table[code][0] == name, f"{code} 이름 불일치: 표 {table[code][0]!r} vs 허브 {name!r}"

    # ③ 출구 링크가 닿는다. '만들었다'와 '닿는다'는 다르다.
    for code, (name, slug) in table.items():
        d = os.path.join(root, "place", slug, "index.html")
        assert os.path.exists(d), f"{code}({name}) 의 정적 페이지가 없다: place/{slug}/"

    # ④ URL 의 name 은 area 가 없을 때만 제목이 된다.
    # 🔴 주석을 먼저 지운다 — 이 페이지의 주석은 함정을 설명하려고 그 코드를 그대로 인용한다.
    #    첫 판이 그래서 '표보다 제목을 먼저 정하기' 돌연변이를 놓쳤다(앵커가 주석에서 매치됐다).
    code = strip_comments(landing)
    n = code.count("params.get('name')")
    assert n == 1, f"params.get('name') 이 {n}번 — 개수를 고정한다(폴백 경로가 늘면 구멍이 는다)"
    assert URL_NAME_GUARDED in code, "URL 이름이 area 부재 가드 밖에 있다 — 제목 위조가 다시 가능하다"
    k = code.count(KNOWN_ANCHOR)
    assert k == 1, f"제목 근거 앵커가 {k}번 — 지워졌거나 주석으로 복제됐다: {KNOWN_ANCHOR}"
    i_known, i_title = code.find(KNOWN_ANCHOR), code.find(TITLE_ANCHOR)
    assert i_title >= 0, "제목 대입부를 찾지 못했다"
    assert i_known < i_title, "제목을 정하기 전에 표를 보지 않는다"

    return len(table)


MUTATIONS = [
    # (설명, 치환 전, 치환 후) — 각각이 실제로 검사를 깨야 한다.
    ("표 비우기", None, None),
    ("URL 폴백 가드 제거", URL_NAME_GUARDED, "params.get('name')"),
    ("표보다 제목을 먼저 정하기(줄 끝 주석에 인용)", KNOWN_ANCHOR, "var known = null; // " + KNOWN_ANCHOR),
    ("근거 줄 통째로 주석 처리", KNOWN_ANCHOR, "var known = null;\n        // " + KNOWN_ANCHOR),
    ("정적 페이지 없는 slug", '"POI054":["혜화역","혜화역"]', '"POI054":["혜화역","없는동네"]'),
]


def self_test(root):
    """검사기가 실제로 잡는지 — 돌연변이를 먹여 본다(초록이 커버리지인지 확인)."""
    import shutil
    import tempfile

    src = os.path.join(root, "place", "index.html")
    with open(src, encoding="utf-8") as f:
        original = f.read()
    assert check(root), "원본이 먼저 통과해야 한다"
    print("  원본 통과 ✓")

    for label, old, new in MUTATIONS:
        tmp = tempfile.mkdtemp()
        try:
            shutil.copytree(os.path.join(root, "place"), os.path.join(tmp, "place"))
            if old is None:  # 표 비우기
                b = original.find(BEGIN)
                e = original.find(END)
                mutated = original[:b] + BEGIN + "\n    var AREA_NAMES = {};\n    " + original[e:]
            else:
                assert original.count(old) == 1, f"{label}: 앵커가 {original.count(old)}건"
                mutated = original.replace(old, new)
            with open(os.path.join(tmp, "place", "index.html"), "w") as f:
                f.write(mutated)
            try:
                check(tmp)
            except AssertionError as ex:
                print(f"  {label} → 잡힘 ✓ ({str(ex)[:60]})")
                continue
            raise SystemExit(f"🔴 {label} 를 검사가 놓쳤다 — 이 계약은 장식이다")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"돌연변이 {len(MUTATIONS)}종 전부 검출 — 계약이 실제로 본다")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    repo = args[0] if args else "."
    if "--self-test" in sys.argv:
        self_test(repo)
    else:
        print(f"착지 페이지 계약 통과 — 동네 {check(repo)}곳")

#!/usr/bin/env python3
"""핼러윈 안내가 출처·동네 대응·실제 출구를 보존하는지 검사한다."""

import json
import re
import shutil
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree


# 서울시 2026 공식 발표의 14곳과 기존 동네 대응 범위를 독립적으로 고정한다.
EXPECTED = {
    "POI004": ("이태원 관광특구", "same"),
    "POI007": ("홍대 관광특구", "same"),
    "POI014": ("강남역", "same"),
    "POI116": ("익선동", "same"),
    "POI045": ("왕십리역", "same"),
    "POI027": ("발산역", "same"),
    "POI039": ("신림역", "same"),
    "POI068": ("성수동 카페거리", "same"),
    "POI071": ("압구정 로데오거리", "same"),
    "POI003": ("명동거리", "contains"),
    "POI037": ("논현역", "contains"),
    "POI015": ("건대 맛의거리", "adjacent"),
    "POI040": ("신촌 연세로", "adjacent"),
    "POI031": ("샤로수길", "adjacent"),
}
BASE = "https://hongdoc96.github.io/hansanmap-legal"
SLUG = "핼러윈-안전안내"


# 렌더 대상 HTML의 링크와 메타데이터를 읽고 임의 스크립트는 실행하지 않는다.
class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.areas = []
        self.canonical = []
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "data-area" in attrs:
            self.areas.append(attrs)
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical.append(attrs.get("href"))
        if tag == "meta" and "property" in attrs:
            self.meta[attrs["property"]] = attrs.get("content")


# 페이지·허브·사이트맵을 함께 검사해 재빌드 뒤에도 안내 출구가 남게 한다.
def check(root):
    path = root / "place" / SLUG / "index.html"
    source = path.read_text(encoding="utf-8")
    page = Page()
    page.feed(source)
    landing = (root / "place/index.html").read_text(encoding="utf-8")
    table = json.loads(re.search(r"var AREA_NAMES\s*=\s*(\{.*\})\s*;", landing).group(1))
    assert len(page.areas) == 14, "동네 출구는 14곳이어야 한다"
    assert {a["data-area"] for a in page.areas} == EXPECTED.keys(), "지정 장소가 달라졌다"
    for a in page.areas:
        code = a["data-area"]
        name, relation = EXPECTED[code]
        assert a.get("data-official-name") == name, f"{code} 지정 명칭 불일치"
        assert a.get("data-relation") == relation, f"{code} 대응 범위 불일치"
        slug = table[code][1]
        assert unquote(urlsplit(a["href"]).path) == f"../{slug}/", f"{code} 다른 동네로 이동"
        assert (root / "place" / slug / "index.html").is_file(), f"{code} 출구 404"
    assert page.canonical == [f"{BASE}/place/%ED%95%BC%EB%9F%AC%EC%9C%88-%EC%95%88%EC%A0%84%EC%95%88%EB%82%B4/"]
    assert page.meta["og:url"] == page.canonical[0], "공유 URL과 canonical이 다르다"
    image = page.meta["og:image"]
    assert image == f"{BASE}/og-image.png" and (root / "og-image.png").is_file(), "공유 이미지 404"
    assert source.count("서울시 2026 관리대상") == 5, "2026 목록의 연도·메타 출처가 다르다"
    assert source.count("2026년 10월 22일 공식 발표 기준") == 1, "공식 발표일이 없다"
    assert source.count('href="https://mediahub.seoul.go.kr/archives/2019819"') == 1, "2026 서울시 본문 출처가 없다"
    assert source.count("서울시 2025 지정 기준") == 0, "지난해 목록으로 잘못 소개한다"
    assert "인접" in source and "거리 자체의 혼잡도가 아니에요" in source
    assert "현장 통제와 공식 안내가 우선" in source
    assert source.count("중점관리 8곳·안전관리 6곳") == 1, "공식 관리대상 구분이 없다"
    assert not re.search(r"fetch\s*\(|eyJ[A-Za-z0-9_-]+\.|지금 안전", source), "본문에 키·개별 fetch·안전 단정을 넣지 않는다"
    assert source.count('src="../season-live.js"') == 1, "공용 실시간 판의 배선이 없다"
    hub = (root / "place/all/index.html").read_text(encoding="utf-8")
    assert hub.count(f'href="../{SLUG}/"') == 1, "허브 입구는 하나여야 한다"
    assert hub.count("서울시 2026 관리대상") == 1, "허브의 목록 연도가 다르다"
    builder = (root / "scripts/build_place_pages.py").read_text(encoding="utf-8")
    assert builder.count(f'href="../{SLUG}/"') == 1, "자동 재빌드가 입구를 지운다"
    assert builder.count("서울시 2026 관리대상") == 1, "재빌드하면 지난해 연도로 되돌아간다"
    urls = [n.text for n in ElementTree.parse(root / "sitemap.xml").iter() if n.tag.endswith("}loc")]
    assert urls.count(page.canonical[0]) == 1, "사이트맵 누락/중복"
    assert f'canon("{SLUG}")' in builder, "자동 재빌드가 사이트맵에서 지운다"
    print("핼러윈 안내 계약 통과 — 14곳·출처·대응 범위·실제 출구·공유·재빌드")


# 실제 HTML을 변형한 임시 사본으로 출구 삭제·범위 오표기·연도 상수화를 반증한다.
def self_test(root):
    check(root)
    original = (root / "place" / SLUG / "index.html").read_text(encoding="utf-8")
    mutations = {
        "동네 출구 삭제": re.sub(r"    <li>.*?data-area=\"POI004\".*?</li>\n", "", original),
        "인접을 같은 곳으로 상수화": original.replace('data-relation="adjacent"', 'data-relation="same"'),
        "출처를 2025로 상수화": original.replace("서울시 2026 관리대상", "서울시 2025 지정 기준"),
    }
    with tempfile.TemporaryDirectory(prefix="hansan-halloween-check-") as tmp:
        target = Path(tmp)
        landing = (root / "place/index.html").read_text(encoding="utf-8")
        table = json.loads(re.search(r"var AREA_NAMES\s*=\s*(\{.*\})\s*;", landing).group(1))
        files = ["place/index.html", "place/all/index.html", "scripts/build_place_pages.py", "sitemap.xml", "og-image.png"]
        files += [f"place/{table[code][1]}/index.html" for code in EXPECTED]
        for name in files:
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, target / name)
        page = target / "place" / SLUG / "index.html"
        page.parent.mkdir(parents=True)
        for name, changed in mutations.items():
            assert changed != original, f"{name} 변형이 적용되지 않았다"
            page.write_text(changed, encoding="utf-8")
            try:
                check(target)
            except AssertionError:
                print(f"돌연변이 검출 — {name}")
            else:
                raise AssertionError(f"회귀를 놓쳤다: {name}")
    check(root)


if __name__ == "__main__":
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    root = Path(args[0] if args else ".")
    self_test(root) if "--self-test" in sys.argv else check(root)

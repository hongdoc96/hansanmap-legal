#!/usr/bin/env python3
"""sitemap.xml 의 URL 을 IndexNow 로 검색엔진에 통보한다.

왜 필요한가: 동네 페이지 120장·sitemap·robots 를 다 만들어 두고도 2026-09-09 실측에서
색인이 0이었다. 검색엔진은 사이트의 존재를 스스로 알지 못한다 — 알려야 크롤링이 시작된다.
IndexNow 는 한 번의 POST 로 Bing·네이버·Seznam·Yandex 에 동시에 통보한다(무료, 계정 불필요).

키 검증: IndexNow 는 https://<host>/<key>.txt 를 읽어 본문이 키와 같은지 확인한다.
이 사이트는 GitHub Pages 서브패스라 호스트 루트에 파일을 둘 수 없으므로 keyLocation 을
명시한다 — 그 경우 제출 URL 은 **키 파일과 같은 디렉토리 이하**여야 한다(사양).
여기서는 키가 /hansanmap-legal/ 에 있고 모든 제출 URL 이 그 아래라 조건을 만족한다.

사용: python3 scripts/submit_indexnow.py [저장소루트=.]
"""

import json
import re
import sys
import urllib.error
import urllib.request

HOST = "hongdoc96.github.io"
BASE = f"https://{HOST}/hansanmap-legal"
KEY = "fe1e4274cea285f8094e3362fb5bf5fa"
ENDPOINT = "https://api.indexnow.org/indexnow"

root = sys.argv[1] if len(sys.argv) > 1 else "."
sitemap = open(f"{root}/sitemap.xml", encoding="utf-8").read()
urls = re.findall(r"<loc>([^<]+)</loc>", sitemap)
if not urls:
    sys.exit("sitemap.xml 에 URL 이 없다 — 재빌드가 먼저다")

# 키 파일과 같은 디렉토리 이하만 제출 가능(위 사양) — 어긋나면 422 로 전량 거부된다.
bad = [u for u in urls if not u.startswith(f"{BASE}/")]
if bad:
    sys.exit(f"키 위치 밖의 URL {len(bad)}개 — 제출 중단: {bad[:3]}")

body = json.dumps(
    {
        "host": HOST,
        "key": KEY,
        "keyLocation": f"{BASE}/{KEY}.txt",
        "urlList": urls,
    }
).encode()

req = urllib.request.Request(
    ENDPOINT, data=body, headers={"Content-Type": "application/json; charset=utf-8"}
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"IndexNow {r.status} — URL {len(urls)}개 통보")
except urllib.error.HTTPError as e:
    # 202=키 검증 대기(정상) · 429=너무 잦음. 둘 다 재빌드를 실패시킬 이유가 아니다.
    detail = e.read().decode(errors="replace")[:200]
    print(f"IndexNow {e.code} — {detail}")
    if e.code not in (202, 429):
        raise

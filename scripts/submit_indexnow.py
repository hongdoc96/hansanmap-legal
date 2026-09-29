#!/usr/bin/env python3
"""sitemap.xml 의 URL 을 IndexNow 로 검색엔진에 통보한다.

왜 필요한가: 동네 페이지 120장·sitemap·robots 를 다 만들어 두고도 2026-09-09 실측에서
색인이 0이었다. 검색엔진은 사이트의 존재를 스스로 알지 못한다 — 알려야 크롤링이 시작된다.
IndexNow 는 한 번의 POST 로 Bing·네이버·Seznam·Yandex 에 동시에 통보한다(무료, 계정 불필요).

키 검증: IndexNow 는 https://<host>/<key>.txt 를 읽어 본문이 키와 같은지 확인한다.
이 사이트는 GitHub Pages 서브패스라 호스트 루트에 파일을 둘 수 없으므로 keyLocation 을
명시한다 — 그 경우 제출 URL 은 **키 파일과 같은 디렉토리 이하**여야 한다(사양).
여기서는 키가 /hansanmap-legal/ 에 있고 모든 제출 URL 이 그 아래라 조건을 만족한다.

바뀐 것만 알린다(2026-09-29): 매주 전 URL 을 다시 통보하면 바뀌지 않은 페이지까지 '바뀌었다'고
말하는 셈이다 — IndexNow 는 변경 통보용이고, 같은 URL 반복 제출은 신호를 흐린다. 빌더가 내용이
그대로인 페이지의 lastmod 를 유지하므로, --since 로 그날 바뀐 URL 만 고른다.

사용: python3 scripts/submit_indexnow.py [저장소루트=.] [--since YYYY-MM-DD | --changed-vs 옛sitemap.xml]
  --since       lastmod 가 그날 이후인 URL 만(주간 재빌드 — 그날 빌더가 바꾼 것)
  --changed-vs  옛 sitemap 과 lastmod 가 다르거나 새로 생긴 URL 만(main 푸시 — 사람이 머지한 변경)
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


def entries_of(xml):
    return re.findall(r"<loc>([^<]+)</loc>(?:<lastmod>([^<]+)</lastmod>)?", xml)


def opt(args, flag):
    if flag not in args:
        return None
    i = args.index(flag)
    if i + 1 >= len(args):
        sys.exit(f"{flag} 에 값이 없다")
    val = args[i + 1]
    del args[i:i + 2]
    return val


args = sys.argv[1:]
since = opt(args, "--since")
prev_path = opt(args, "--changed-vs")
if since is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
    sys.exit(f"--since 는 YYYY-MM-DD: {since!r}")
root = args[0] if args else "."
sitemap = open(f"{root}/sitemap.xml", encoding="utf-8").read()
entries = entries_of(sitemap)
if not entries:
    sys.exit("sitemap.xml 에 URL 이 없다 — 재빌드가 먼저다")
if prev_path is not None:
    # 옛 sitemap 이 비어 있으면(첫 커밋 등) 전부 새것이다.
    prev = dict(entries_of(open(prev_path, encoding="utf-8").read()))
    urls = [u for u, m in entries if u not in prev or prev[u] != m]
    scope = "옛 sitemap 대비 바뀐"
elif since is not None:
    # lastmod 가 YYYY-MM-DD 라 문자열 비교가 날짜 비교다. lastmod 가 없으면 바뀐 것으로 본다.
    urls = [u for u, m in entries if not m or m >= since]
    scope = f"{since} 이후 바뀐"
else:
    urls = [u for u, _ in entries]
    scope = "전체"
if not urls:
    print(f"{scope} URL 없음 — 통보 생략")
    sys.exit(0)
print(f"{scope} URL {len(urls)}개")

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

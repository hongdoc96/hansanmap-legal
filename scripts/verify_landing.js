// 공유 착지 페이지 동작 테스트 — 페이지의 **실제 스크립트를 실행**해 제목을 재 본다.
//
// 🔴 왜 소스 계약(check_landing.py)만으로는 부족한가: 그것은 형태만 본다. 조건식을 뒤집거나
//    폴백을 바꾸면 형태는 그대로인 채 화면의 말이 달라진다. 이 결함이 정확히 그랬다 —
//    `?area=POI054&name=홍대` 가 제목만 '홍대' 로 바뀌고 카드는 혜화역 값이었는데,
//    페이지는 200 이고 카드도 정상이라 눈으로는 어긋난 걸 알 수 없었다.
//
// 사용: node scripts/verify_landing.js place/index.html
// (소스 문자열 검사는 형태만 본다 — 무엇이 화면에 뜨는지는 돌려 봐야 안다.)
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (!scripts.length) throw new Error("script 블록이 없다");

function run(search) {
  const els = {};
  const mk = () => ({ textContent: '한산맵에서 보기', style: {}, attrs: {},
                      setAttribute(k, v) { this.attrs[k] = v; },
                      appendChild() {}, className: '' });
  for (const id of ['title', 'openApp', 'storeLink', 'areaPage', 'live', 'liveLevel',
                    'liveTime', 'liveEase', 'liveAlts']) els[id] = mk();
  const sandbox = {
    document: { getElementById: id => els[id], createElement: () => mk() },
    window: { location: { search, set href(v) { sandbox.navigated = v; } } },
    navigator: { userAgent: 'Mozilla/5.0 (Linux; Android 14)', platform: 'Linux', maxTouchPoints: 5 },
    fetch: () => new Promise(() => {}),   // 응답 없음 — 제목은 네트워크와 무관해야 한다
    URLSearchParams, Date, Math, JSON, String, Number,
  };
  const vm = require('vm');
  const ctx = vm.createContext(sandbox);
  for (const s of scripts) vm.runInContext(s, ctx);
  return { title: els.title.textContent, more: els.areaPage,
           scheme: els.openApp.attrs.href, navigated: sandbox.navigated };
}

let fail = 0;
function eq(label, got, want) {
  const ok = got === want;
  if (!ok) fail++;
  console.log(`${ok ? '✓' : '🔴'} ${label}\n    got  ${JSON.stringify(got)}${ok ? '' : `\n    want ${JSON.stringify(want)}`}`);
}

const enc = encodeURIComponent;
// 🔴 이번에 고친 그것 — 위조된 이름은 제목이 되지 못한다(카드는 POI054=혜화역 값이다).
eq('위조 링크 ?area=POI054&name=홍대', run(`?area=POI054&name=${enc('홍대')}`).title,
   '혜화역 — 한산맵에서 보기');
eq('앱이 만든 정상 링크', run(`?area=POI054&name=${enc('혜화역')}`).title,
   '혜화역 — 한산맵에서 보기');
eq('이름에 · 가 든 동네', run(`?area=POI009&name=${enc('아무말')}`).title,
   '광화문·덕수궁 — 한산맵에서 보기');
eq('모르는 코드면 이름을 지어내지 않는다', run(`?area=POI999&name=${enc('강남역')}`).title,
   '한산맵에서 보기');
eq('매장 링크(area 없음)는 URL 이름뿐이라 그대로', run(`?name=${enc('연남동 우동집')}`).title,
   '연남동 우동집 — 한산맵에서 보기');
eq('긴 이름은 잘린다', run(`?name=${enc('가'.repeat(300))}`).title,
   '가'.repeat(40) + '… — 한산맵에서 보기');
eq('쿼리 없음', run('').title, '한산맵에서 보기');

const r = run(`?area=POI001&name=${enc('홍대')}`);
eq('출구 링크 텍스트', r.more.textContent, '강남 MICE 관광특구 평소 혼잡도 보기 →');
eq('출구 링크 경로(빌더 slug 와 동일)', r.more.attrs.href, enc('강남-MICE-관광특구') + '/');
eq('출구 링크 노출', r.more.style.display, 'block');
eq('매장 링크엔 출구가 없다', run(`?name=${enc('우동집')}`).more.style.display, undefined);
eq('앱 열기 스킴은 쿼리를 그대로 넘긴다',
   run('?area=POI054&at=1').scheme, 'kr.hongdoc.hansanmap://place?area=POI054&at=1');

console.log(fail ? `\n🔴 ${fail}건 실패` : '\n전부 통과');
process.exit(fail ? 1 : 0);

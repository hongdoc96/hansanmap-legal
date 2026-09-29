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

const ANDROID_UA = 'Mozilla/5.0 (Linux; Android 14)';
const IOS_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)';

function run(search, ua = ANDROID_UA) {
  const els = {};
  const mk = () => ({ textContent: '한산맵에서 보기', style: {}, attrs: {},
                      setAttribute(k, v) { this.attrs[k] = v; },
                      appendChild() {}, className: '' });
  for (const id of ['title', 'openApp', 'storeLink', 'areaPage', 'live', 'liveLevel',
                    'liveTime', 'liveEase', 'liveAlts', 'installHint']) els[id] = mk();
  const sandbox = {
    document: { getElementById: id => els[id], createElement: () => mk() },
    window: { location: { search, set href(v) { sandbox.navigated = v; } } },
    navigator: { userAgent: ua, platform: ua === IOS_UA ? 'iPhone' : 'Linux', maxTouchPoints: 5 },
    fetch: () => new Promise(() => {}),   // 응답 없음 — 제목은 네트워크와 무관해야 한다
    URLSearchParams, Date, Math, JSON, String, Number,
  };
  const vm = require('vm');
  const ctx = vm.createContext(sandbox);
  for (const s of scripts) vm.runInContext(s, ctx);
  return { title: els.title.textContent, more: els.areaPage,
           scheme: els.openApp.attrs.href, navigated: sandbox.navigated,
           store: els.storeLink.attrs.href, hint: els.installHint };
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


// 공유 설치 이어받기(F1·F2, 2026-09-29) — 스토어 버튼이 동네를 싣고, 설치 뒤 돌아오는 길을 안내한다.
// 형식은 앱 lib/core/utils/install_referrer.dart 와 **글자 하나까지** 같아야 한다(앱 테스트가 같은 문자열을 쓴다).
const PLAY = 'https://play.google.com/store/apps/details?id=kr.hongdoc.hansanmap';
const APPSTORE = 'https://apps.apple.com/app/id6783810617';
const REF = 'a1b2c3d4e5f6';
eq('Android 동네 링크 → Play 에 동네·토큰을 싣는다',
   run(`?area=POI054&name=${enc('혜화역')}&ref=${REF}`).store,
   PLAY + '&referrer=' + enc(`utm_source=hansan_share&utm_medium=landing&area=POI054&ref=${REF}`));
eq('토큰이 형식에 안 맞으면 토큰만 뺀다',
   run('?area=POI054&ref=ZZZ').store,
   PLAY + '&referrer=' + enc('utm_source=hansan_share&utm_medium=landing&area=POI054'));
eq('모르는 코드는 싣지 않는다(제목과 같은 근거)', run('?area=POI999').store, PLAY);
eq('매장 링크(area 없음)는 그냥 Play', run(`?name=${enc('우동집')}`).store, PLAY);
eq('iOS 는 App Store(설치 경로를 넘기지 않는다)', run(`?area=POI054&ref=${REF}`, IOS_UA).store, APPSTORE);
const hk = run(`?area=POI054&name=${enc('홍대')}`).hint;
eq('설치 뒤 안내 — 이름은 URL 이 아니라 표에서', hk.textContent,
   "설치한 뒤 이 페이지로 돌아와 '앱에서 열기'를 누르면 혜화역 화면이 바로 열려요.");
eq('설치 뒤 안내 노출', hk.style.display, 'block');
eq('iOS 에서도 안내가 뜬다', run('?area=POI009', IOS_UA).hint.style.display, 'block');
eq('모르는 코드엔 안내가 없다', run('?area=POI999').hint.style.display, undefined);
eq('매장 링크엔 안내가 없다', run(`?name=${enc('우동집')}`).hint.style.display, undefined);
eq('스토어 처리 뒤에도 자동 앱 열기는 그대로', run('?area=POI054').navigated,
   'kr.hongdoc.hansanmap://place?area=POI054');

console.log(fail ? `\n🔴 ${fail}건 실패` : '\n전부 통과');
process.exit(fail ? 1 : 0);

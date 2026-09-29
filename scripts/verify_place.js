// 동네 페이지·허브 동작 테스트 — 페이지의 **실제 스크립트를 실행**해 화면에 뜨는 말을 재 본다.
//
// 🔴 왜 소스 계약(check_places.py)만으로는 부족한가: 그것은 정적 본문과 근거 칸만 본다.
//    라이브 규약(2시간 넘은 값은 '지금'이라 부르지 않는다, 한 시간 반짝 낮아지는 예측으로
//    '풀린다'고 약속하지 않는다, 자정을 넘기면 '내일')은 스크립트가 지키는 것이라 돌려 봐야 안다.
//    네트워크 없이 — RPC 는 가짜 응답, 시계는 고정, DOM 은 페이지 HTML 에서 뽑은 최소 모형.
//
// 사용: node scripts/verify_place.js [저장소루트=.]
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = process.argv[2] || '.';
const APPSTORE = 'https://apps.apple.com/app/id6783810617';
const MIN = 60000;
const HOUR = 60 * MIN;

// KST 벽시계 → epoch ms (테스트 시각을 서울 기준으로 적기 위해)
const kst = (y, mo, d, h, mi = 0) => Date.UTC(y, mo - 1, d, h - 9, mi);
const SAT_14 = kst(2026, 10, 3, 14);     // 토요일 14:00
const SAT_2230 = kst(2026, 10, 3, 22, 30);

function el(id, cls = '') {
  return {
    id, className: cls, textContent: '', style: {}, attrs: {}, children: {}, onclick: null,
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    querySelector(sel) { return this.children[sel] || null; },
    appendChild(c) { (this.kids = this.kids || []).push(c); },
  };
}

function makeDate(nowMs) {
  const Real = Date;
  function FakeDate(...a) { return a.length ? new Real(...a) : new Real(nowMs); }
  FakeDate.now = () => nowMs;
  FakeDate.UTC = Real.UTC;
  FakeDate.parse = Real.parse;
  FakeDate.prototype = Real.prototype;
  return FakeDate;
}

// 페이지 HTML → 최소 DOM(id 요소 + 히트맵 표 + 링크 카드 목록)
function dom(html) {
  const byId = {};
  for (const m of html.matchAll(/ id="([^"]+)"/g)) byId[m[1]] = el(m[1]);
  const hm = html.match(/<table id="hm"[^>]*><tbody>([\s\S]*?)<\/tbody><\/table>/);
  if (hm) {
    byId.hm.rows = [...hm[1].matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map(r => ({
      cells: [...r[1].matchAll(/<(th|td)([^>]*)>/g)].map(c => {
        const k = c[2].match(/class="([^"]*)"/);
        return el('', k ? k[1] : '');
      }),
    }));
  }
  const cards = sel => [...html.matchAll(new RegExp(`<div class="${sel}"[^>]*>([\\s\\S]*?)</div>`, 'g'))]
    .flatMap(m => [...m[1].matchAll(/<a href="[^"]*" data-c="([^"]+)">/g)])
    .map(m => { const a = el(''); a.attrs['data-c'] = m[1]; a.children['.lv'] = el('', 'lv'); return a; });
  const lists = { '.near a[data-c]': cards('near'), '.g a[data-c]': cards('g') };
  return {
    byId, lists,
    document: {
      getElementById: id => byId[id] || null,
      querySelectorAll: sel => lists[sel] || [],
      createElement: () => el(''),
    },
  };
}

// routes: { rpc 이름: 응답 | Error | (body)=>응답 }
function run(file, { now, routes = {}, ios = false, search = '' }) {
  const html = fs.readFileSync(file, 'utf8');
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  if (!scripts.length) throw new Error(`${file}: script 블록이 없다`);
  const d = dom(html);
  const calls = [];
  const fetch = (url, opt) => {
    const fn = url.split('/rpc/')[1];
    const body = JSON.parse((opt && opt.body) || '{}');
    calls.push({ fn, body });
    let r = routes[fn];
    if (typeof r === 'function') r = r(body);
    if (r === undefined || r instanceof Error) return Promise.reject(r || new Error('no route ' + fn));
    return Promise.resolve({ json: () => Promise.resolve(JSON.parse(JSON.stringify(r))) });
  };
  const sandbox = {
    document: d.document,
    window: { location: { search, set href(v) { sandbox.navigated = v; } } },
    navigator: ios
      ? { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)', platform: 'iPhone', maxTouchPoints: 5 }
      : { userAgent: 'Mozilla/5.0 (Linux; Android 14)', platform: 'Linux', maxTouchPoints: 5 },
    fetch, Date: makeDate(now), URLSearchParams, Math, JSON, String, Number, Array, Object, Promise,
  };
  const ctx = vm.createContext(sandbox);
  for (const s of scripts) vm.runInContext(s, ctx);
  return { ...d, calls, settle: async () => { for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r)); } };
}

let fail = 0;
function eq(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) fail++;
  console.log(`${ok ? '✓' : '🔴'} ${label}${ok ? '' : `\n    got  ${JSON.stringify(got)}\n    want ${JSON.stringify(want)}`}`);
}

const iso = ms => new Date(ms).toISOString();
const detail = (lvl, ageMin, now) => [{ congest_lvl: lvl, updated_at: iso(now - ageMin * MIN) }];
const fc = (now, pts) => pts.map(([h, level]) => ({ target_at: iso(now + h * HOUR), level, is_current: false }));

(async () => {
  const page = path.join(root, 'place', '강남역', 'index.html');
  const html = fs.readFileSync(page, 'utf8');
  // 전제 확인 — 이 테스트가 기대는 평소값(토 14시 = 붐빔)이 페이지에 실제로 있는가
  const RANKS = JSON.parse(html.match(/var RANKS=(\[\[.*?\]\]);/)[1]);
  eq('전제: 강남역 평소 토요일 14시 = 붐빔(3)', RANKS[6][14], 3);
  const near = [...html.matchAll(/<div class="near">([\s\S]*?)<\/div>/g)][0][1];
  const [n1, n2, n3] = [...near.matchAll(/data-c="([^"]+)"/g)].map(m => m[1]);

  // ① 붐빔 · 신선 → 카드 + '평소와 비슷' + 지속되는 첫 하락 시각
  let r = run(page, {
    now: SAT_14,
    routes: {
      get_seoul_area_detail: detail('붐빔', 5, SAT_14),
      get_seoul_area_forecast: fc(SAT_14, [[1, '붐빔'], [2, '보통'], [3, '붐빔'], [4, '약간붐빔'], [5, '보통'], [6, '여유']]),
      list_seoul_area_status: [
        { area_code: n1, congestion_level: '여유', updated_at: iso(SAT_14 - 3 * MIN) },
        { area_code: n2, congestion_level: '붐빔', updated_at: iso(SAT_14 - 3 * HOUR) }, // 낡음
        { area_code: n3, congestion_level: '약간 붐빔', updated_at: iso(SAT_14 - 3 * MIN) }, // 공백 변형
      ],
    },
  });
  await r.settle();
  eq('카드 노출', r.byId.live.style.display, 'block');
  eq('지금 단계', r.byId.liveLevel.textContent, '지금 🔴 붐빔');
  eq('지금 vs 평소(토 14시 = 붐빔)', r.byId.liveVs.textContent, '평소 이 시간과 비슷해요');
  eq('몇 분 전', r.byId.liveTime.textContent, '5분 전 · 서울시 실시간 도시데이터');
  eq('예측은 서버 동네명으로 묻는다', r.calls.find(c => c.fn === 'get_seoul_area_forecast').body, { p_area_name: '강남역' });
  eq('한 시간 반짝(16시 보통) 무시 → 지속 하락 18시', r.byId.liveEase.textContent, '18시 이후 풀릴 것으로 예상돼요');
  eq('풀림 줄 노출', r.byId.liveEase.style.display, 'block');
  eq('히트맵 지금 칸(토 14시)', r.byId.hm.rows[6].cells[15].className.includes('now'), true);
  eq('다른 칸엔 표시 없음', r.byId.hm.rows[6].cells[14].className.includes('now'), false);
  eq('지금 칸 안내', r.byId.hmNow.textContent, '테두리 칸이 지금(토요일 14시)이에요');
  const nearEls = r.lists['.near a[data-c]'];
  eq('근처(신선·여유) 표시', [nearEls[0].children['.lv'].textContent, nearEls[0].children['.lv'].className], ['● 지금 여유', 'lv on']);
  eq('근처(3시간 낡음) 미표시', nearEls[1].children['.lv'].className, 'lv');
  eq('근처(공백 든 단계명도 정규화)', nearEls[2].children['.lv'].className, 'lv on');
  eq('안드로이드 CTA 는 Play', r.byId.ctaApp.attrs.href, undefined);

  // ② 낡은 값(3시간) → '지금'으로 단정하지 않는다
  r = run(page, { now: SAT_14, routes: { get_seoul_area_detail: detail('붐빔', 180, SAT_14) } });
  await r.settle();
  eq('낡은 값: 카드 숨김', r.byId.live.style.display, undefined);
  eq('낡은 값: 예측 안 부름', r.calls.some(c => c.fn === 'get_seoul_area_forecast'), false);

  // ③ 여유 → 한산 비교만, 예측은 부르지도 않는다
  r = run(page, { now: SAT_14, routes: { get_seoul_area_detail: detail('여유', 1, SAT_14) } });
  await r.settle();
  eq('여유: 평소보다 한산', r.byId.liveVs.textContent, '평소 이 시간보다 한산해요');
  eq('여유: 예측 안 부름', r.calls.some(c => c.fn === 'get_seoul_area_forecast'), false);

  // ④ 자정 넘김 → '내일'
  r = run(page, {
    now: SAT_2230,
    routes: {
      get_seoul_area_detail: detail('붐빔', 2, SAT_2230),
      get_seoul_area_forecast: fc(SAT_2230, [[0.5, '붐빔'], [1.5, '보통'], [2.5, '여유']]),
    },
  });
  await r.settle();
  eq('자정 넘긴 풀림엔 내일', r.byId.liveEase.textContent, '내일 0시 이후 풀릴 것으로 예상돼요');

  // ⑤ 예측이 끝까지 안 풀리면 침묵
  r = run(page, {
    now: SAT_14,
    routes: { get_seoul_area_detail: detail('약간붐빔', 1, SAT_14), get_seoul_area_forecast: fc(SAT_14, [[1, '붐빔'], [2, '약간붐빔']]) },
  });
  await r.settle();
  eq('안 풀리면 풀림 줄 없음', r.byId.liveEase.style.display, undefined);

  // ⑥ 모르는 단계 → ⚪, 비교·예측 없음
  r = run(page, { now: SAT_14, routes: { get_seoul_area_detail: detail('정보없음', 1, SAT_14) } });
  await r.settle();
  eq('모르는 단계: ⚪', r.byId.liveLevel.textContent, '지금 ⚪ 정보없음');
  eq('모르는 단계: 비교 없음', r.byId.liveVs.textContent, '');

  // ⑦ 네트워크 실패 → 조용히(예외 없음), 정적 본문만
  r = run(page, { now: SAT_14, routes: {} });
  await r.settle();
  eq('실패: 카드 숨김', r.byId.live.style.display, undefined);

  // ⑧ iOS → App Store
  r = run(page, { now: SAT_14, ios: true });
  await r.settle();
  eq('iOS: 하단 CTA', r.byId.ctaApp.attrs.href, APPSTORE);
  eq('iOS: 카드 CTA', r.byId.liveCta.attrs.href, APPSTORE);

  // ── 허브 ──
  const hub = path.join(root, 'place', 'all', 'index.html');
  const hubHtml = fs.readFileSync(hub, 'utf8');
  const codes = [...hubHtml.matchAll(/data-c="([^"]+)"/g)].map(m => m[1]);
  r = run(hub, {
    now: SAT_14,
    routes: {
      list_seoul_area_status: [
        { area_code: codes[0], congestion_level: '여유', updated_at: iso(SAT_14 - 4 * MIN) },
        { area_code: codes[1], congestion_level: '붐빔', updated_at: iso(SAT_14 - 4 * MIN) },
        { area_code: codes[2], congestion_level: '여유', updated_at: iso(SAT_14 - 9 * MIN) },
        { area_code: codes[3], congestion_level: '여유', updated_at: iso(SAT_14 - 5 * HOUR) }, // 낡음
      ],
    },
  });
  await r.settle();
  const g = r.lists['.g a[data-c]'];
  eq('허브: 신선한 3곳만 색', g.filter(a => a.children['.lv'].className === 'lv on').length, 3);
  eq('허브: 낡은 곳은 여유여도 필터 대상 아님', g[3].className, '');
  eq('허브: 안내', r.byId.liveNote.textContent, '지금 혼잡도 3곳 · 4분 전 · 서울시 실시간 도시데이터');
  eq('허브: 필터 버튼', [r.byId.onlyQuiet.textContent, r.byId.onlyQuiet.style.display], ['지금 여유로운 곳만 보기 (2곳)', 'inline-block']);
  r.byId.onlyQuiet.onclick();
  eq('허브: 필터 켬', [r.byId.grid.className, r.byId.onlyQuiet.textContent], ['g quiet', `전체 ${codes.length}곳 보기`]);
  r.byId.onlyQuiet.onclick();
  eq('허브: 필터 끔', r.byId.grid.className, 'g');

  r = run(hub, { now: SAT_14, routes: { list_seoul_area_status: [
    { area_code: codes[0], congestion_level: '여유', updated_at: iso(SAT_14 - 3 * HOUR) }] } });
  await r.settle();
  eq('허브: 전부 낡으면 안내·버튼 없음', [r.byId.liveNote.style.display, r.byId.onlyQuiet.style.display], [undefined, undefined]);

  // ── 공유 착지도 같은 '내일' 규약 ──
  const landing = path.join(root, 'place', 'index.html');
  r = run(landing, {
    now: SAT_2230, search: '?area=POI014',
    routes: {
      get_seoul_area_detail: detail('붐빔', 2, SAT_2230),
      list_seoul_area_status: [{ area_code: 'POI014', area_name: '강남역', congestion_level: '붐빔', lat: 37.498, lng: 127.028 }],
      get_seoul_area_forecast: fc(SAT_2230, [[0.5, '붐빔'], [1.5, '보통'], [2.5, '여유']]),
    },
  });
  await r.settle();
  eq('착지: 자정 넘긴 풀림엔 내일', r.byId.liveEase.textContent, '내일 0시 이후 풀릴 것으로 예상돼요');
  r = run(landing, {
    now: SAT_14, search: '?area=POI014',
    routes: {
      get_seoul_area_detail: detail('붐빔', 2, SAT_14),
      list_seoul_area_status: [{ area_code: 'POI014', area_name: '강남역', congestion_level: '붐빔', lat: 37.498, lng: 127.028 }],
      get_seoul_area_forecast: fc(SAT_14, [[1, '붐빔'], [4, '보통'], [5, '여유']]),
    },
  });
  await r.settle();
  eq('착지: 같은 날이면 내일 없음', r.byId.liveEase.textContent, '18시 이후 풀릴 것으로 예상돼요');

  console.log(fail ? `\n🔴 ${fail}건 실패` : '\n전부 통과');
  process.exit(fail ? 1 : 0);
})();

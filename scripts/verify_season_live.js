// 실제 계절 판 모듈의 신선도·정렬·오류·기간 종료를 고정 시계로 검사한다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sourcePath = path.join(__dirname, '../place/season-live.js');
assert.ok(fs.existsSync(sourcePath), '두 계절 페이지가 공유할 실시간 판이 없다');
const api = require(sourcePath);
const now = Date.parse('2026-10-26T12:00:00+09:00');
const row = (code, level, at) => ({area_code: code, congestion_level: level, updated_at: at});

// 서울시 RPC가 반환한 관측 시각을 사용하며 경계 직후에는 등급을 숨긴다.
assert.equal(api.statusFor(row('A', '보통', '2026-10-26T11:30:00+09:00'), now).level, '보통');
assert.equal(api.statusFor(row('A', '붐빔', new Date(now - 90 * 60000).toISOString()), now).level, '붐빔');
assert.equal(api.statusFor(row('A', '붐빔', new Date(now - 90 * 60000 - 1).toISOString()), now).level, null);
assert.equal(api.statusFor(row('A', '붐빔', null), now).level, null);
assert.equal(api.statusFor(row('A', '붐빔', 'not-a-date'), now).level, null);
assert.equal(api.statusFor(row('A', '미지', new Date(now).toISOString()), now).level, null);
assert.equal(api.statusFor(row('A', '여유', new Date(now + 120000).toISOString()), now).level, null);

// 최소 DOM만 대역이며 실제 모듈의 fetch·정렬·링크 보존·시간 갱신을 실행한다.
function surface({order = 'busy', end, rows, failure = false, hold = false} = {}) {
  let current = now;
  const events = {};
  const timers = new Map();
  let nextTimer = 0;
  let calls = 0;
  let resolveFetch;
  const list = {children: [], appendChild(li) {
    this.children = this.children.filter(x => x !== li); this.children.push(li);
  }};
  const links = ['quiet', 'busy', 'stale', 'missing'].map(code => {
    const li = {parentNode: list};
    const a = {dataset: {area: code}, href: `../${code}/`, children: [],
      parentElement: li, appendChild(node) {this.children.push(node);},
      closest() {return li;}};
    li.link = a; list.children.push(li); return a;
  });
  const panel = {hidden: false, dataset: {order, ...(end ? {endsAt: end} : {})},
    querySelectorAll() {return links;}};
  const message = {textContent: ''};
  const document = {hidden: false, getElementById(id) {
    return id === 'seasonLive' ? panel : id === 'seasonLiveMessage' ? message : null;
  }, createElement() {return {className: '', textContent: ''};},
  querySelectorAll() {return links;},
  addEventListener(name, fn) {events[name] = fn;}};
  class Clock extends Date {static now() {return current;}}
  const window = {HansanPublicClient: {url: 'https://example.supabase.co', key: 'sb_publishable_fixture'},
    addEventListener(name, fn) {events[name] = fn;}, AbortController,
    fetch(url, options) {
      calls++; assert.equal(url, 'https://example.supabase.co/rest/v1/rpc/list_seoul_area_status');
      assert.equal(options.method, 'POST'); assert.equal(options.body, '{}');
      assert.equal(options.headers.apikey, 'sb_publishable_fixture');
      assert.equal(options.headers.Authorization, undefined);
      const response = {ok: true, json: async () => rows};
      return hold ? new Promise(resolve => {resolveFetch = () => resolve(response);})
        : failure ? Promise.reject(new Error('offline')) : Promise.resolve(response);
    }, setTimeout(fn) {timers.set(++nextTimer, fn); return nextTimer;},
    clearTimeout(id) {timers.delete(id);}};
  const ctx = vm.createContext({window, document, Date: Clock, console, module: undefined});
  vm.runInContext(fs.readFileSync(sourcePath, 'utf8'), ctx);
  return {panel, message, links, list, calls: () => calls, events,
    async settle() {for (let i = 0; i < 8; i++) await Promise.resolve();},
    advance(instant) {current = Date.parse(instant); events.pageshow?.();},
    release() {resolveFetch?.();}};
}

(async () => {
  const rows = [row('quiet', '여유', '2026-10-26T11:30:00+09:00'),
    row('busy', '붐빔', '2026-10-26T11:30:00+09:00'),
    row('stale', '붐빔', '2026-10-26T10:00:00+09:00')];
  const busy = surface({rows}); await busy.settle();
  assert.equal(busy.calls(), 1);
  assert.deepEqual(busy.list.children.map(x => x.link.dataset.area), ['busy', 'quiet', 'stale', 'missing']);
  assert.match(busy.links[0].children[0].textContent, /여유.*30분 전/);
  assert.doesNotMatch(busy.links[2].children[0].textContent, /붐빔/);
  busy.advance('2026-10-26T13:01:00+09:00');
  assert.doesNotMatch(busy.links[1].children[0].textContent, /붐빔/);
  assert.equal(busy.calls(), 1, '복귀 시 새 네트워크 요청을 늘리지 않는다');
  const quiet = surface({order: 'quiet', rows}); await quiet.settle();
  assert.equal(quiet.list.children[0].link.dataset.area, 'quiet');
  const offline = surface({failure: true}); await offline.settle();
  assert.match(offline.message.textContent, /불러오지 못/);
  assert.deepEqual(offline.links.map(x => x.href), ['../quiet/', '../busy/', '../stale/', '../missing/']);
  const empty = surface({rows: []}); await empty.settle();
  assert.match(empty.message.textContent, /확인할 수 없/);
  const malformed = surface({rows: {bad: true}}); await malformed.settle();
  assert.match(malformed.message.textContent, /불러오지 못/);
  const ended = surface({end: '2026-10-26T12:00:00+09:00', rows}); await ended.settle();
  assert.equal(ended.panel.hidden, true); assert.equal(ended.calls(), 0);
  const pending = surface({end: '2026-10-26T12:01:00+09:00', rows, hold: true});
  pending.advance('2026-10-26T12:01:00+09:00'); pending.release(); await pending.settle();
  assert.equal(pending.panel.hidden, true, '늦은 응답이 종료한 판을 되살리지 않는다');
  assert.equal(pending.links[0].children[0].hidden, true);
  assert.equal(pending.links[0].href, '../quiet/', '기간 종료 뒤에도 동네 출구를 보존한다');
  console.log('계절 실시간 판: 신선도·한 번 조회·양방향 정렬·실패 출구·기간 종료 통과');
})().catch(error => {console.error(error); process.exitCode = 1;});

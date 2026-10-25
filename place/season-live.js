// 계절 안내 두 곳이 같은 공개 목록을 한 번 읽고, 낡으면 등급 대신 링크를 남긴다.
(function (factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else api.mount(document, window);
}(function () {
  var ranks = {'여유': 0, '보통': 1, '약간붐빔': 2, '붐빔': 3};
  var maxAge = 90 * 60000;

  // RPC가 보정한 관측 시각을 사용하며 시각·등급이 불명확하면 현재 상태를 말하지 않는다.
  function statusFor(row, now) {
    var at = row && Date.parse(row.updated_at || '');
    var age = now - at;
    var level = row && String(row.congestion_level || '').replace(/\s/g, '');
    if (!Number.isFinite(at) || age < -60000 || ranks[level] === undefined) {
      return {level: null, age: null, at: null};
    }
    return {level: age > maxAge ? null : level, age: Math.max(0, age), at: at};
  }

  // 정적 링크는 먼저 보이고, 실패·90분 경과·한국 시각 기간 종료에도 출구가 남는다.
  async function mount(document, window) {
    var panel = document.getElementById('seasonLive');
    if (!panel) return;
    var message = document.getElementById('seasonLiveMessage');
    var end = Date.parse(panel.dataset.endsAt || '');
    var rows = [];
    var failed = false;
    var loading = true;
    var timer;
    var requestTimer;
    var controller = window.AbortController ? new window.AbortController() : null;
    var entries = Array.from(document.querySelectorAll('a[data-area]')).map(function (link, index) {
      var status = document.createElement('span');
      status.className = 'live-reading';
      link.appendChild(status);
      return {link: link, item: link.closest('li'), code: link.dataset.area, index: index, status: status};
    });

    // 처음 조회한 자료만 다시 판정하므로 열린 페이지에서도 오래된 등급이 남지 않는다.
    function render() {
      window.clearTimeout(timer);
      var now = Date.now();
      if (Number.isFinite(end) && now >= end) {
        panel.hidden = true;
        entries.forEach(function (entry) {
          entry.status.hidden = true;
          entry.item.parentNode.appendChild(entry.item);
        });
        if (controller) controller.abort();
        return false;
      }
      var byCode = new Map(rows.map(function (row) {return [row.area_code, row];}));
      var fresh = 0;
      var delay = Number.isFinite(end) ? Math.min(60000, end - now) : 60000;
      entries.forEach(function (entry) {
        var value = statusFor(byCode.get(entry.code), now);
        entry.rank = value.level === null ? null : ranks[value.level];
        if (value.level !== null) {
          fresh++;
          delay = Math.min(delay, value.at + maxAge - now + 1);
        }
        var age = value.age === null ? '' : ' · ' + Math.floor(value.age / 60000) + '분 전';
        var time = value.at === null ? '' : ' (' + new Date(value.at).toLocaleTimeString('ko-KR',
          {timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false}) + ' 기준)';
        entry.status.textContent = loading ? '자료를 확인하고 있어요' : failed
          ? '동네 링크에서 다시 확인하세요' : (value.level || (value.age === null
            ? '현재 자료를 확인할 수 없어요' : '자료가 오래됐어요')) + age + time;
      });
      if (!loading && !failed) {
        entries.slice().sort(function (a, b) {
          if (a.rank === null || b.rank === null) return a.rank === b.rank ? a.index - b.index : a.rank === null ? 1 : -1;
          return (panel.dataset.order === 'busy' ? b.rank - a.rank : a.rank - b.rank) || a.index - b.index;
        }).forEach(function (entry) {entry.item.parentNode.appendChild(entry.item);});
      }
      message.textContent = loading ? '혼잡도 자료를 확인하고 있어요. 동네 링크는 바로 열 수 있어요.' : failed
        ? '현재 자료를 불러오지 못했어요. 아래 동네 링크에서 다시 확인하세요.' : fresh
          ? '관측 시각을 확인할 수 있는 동네 ' + fresh + '곳 · ' + (panel.dataset.order === 'busy' ? '붐비는 순' : '한산한 순')
          : '현재 상태를 확인할 수 없어요. 아래 동네 링크에서 확인하세요.';
      timer = window.setTimeout(render, Math.max(1, delay));
      return true;
    }

    if (!render()) return;
    document.addEventListener('visibilitychange', function () {if (!document.hidden) render();});
    window.addEventListener('pageshow', render);
    window.addEventListener('pagehide', function () {
      window.clearTimeout(timer);
      if (controller) controller.abort();
    });
    try {
      var config = window.HansanPublicClient;
      if (!config || !String(config.key).startsWith('sb_publishable_')) throw new Error('public key unavailable');
      rows = await Promise.race([
        window.fetch(config.url + '/rest/v1/rpc/list_seoul_area_status', {
          method: 'POST', headers: {'Content-Type': 'application/json', apikey: config.key},
          body: '{}', signal: controller ? controller.signal : undefined,
        }).then(function (response) {
          if (!response.ok) throw new Error('status unavailable');
          return response.json();
        }),
        new Promise(function (_, reject) {
          requestTimer = window.setTimeout(function () {
            if (controller) controller.abort();
            reject(new Error('request timed out'));
          }, 8000);
        }),
      ]);
      if (!Array.isArray(rows)) throw new Error('invalid response');
      rows = rows.filter(function (row) {return row && typeof row.area_code === 'string';});
    } catch (_) {
      failed = true;
      rows = [];
    } finally {
      window.clearTimeout(requestTimer);
      loading = false;
      render();
    }
  }
  return {statusFor: statusFor, mount: mount};
}));

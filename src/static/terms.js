// 화면에 보이는 이름(현장 용어 / 장비 원명칭)을 /api/terms (src/terms.json) 에서 읽어 바꿔 준다.
// 사용: Terms.init() 한 번 부른 뒤 Terms.t('feed_pusher'), HTML 의 data-term="feed_pusher" 는 Terms.apply() 가 채운다.
window.Terms = (() => {
  let data = null, mode = 'field';
  const q = new URLSearchParams(location.search).get('terms');
  const get = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const set = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* 저장이 막혀 있어도 화면은 동작한다 */ } };
  return {
    async init() {
      try { data = await (await fetch('/api/terms')).json(); } catch (e) { data = { terms: {}, tags: {}, default_mode: 'field' }; }
      mode = ['field', 'lab'].includes(q) ? q : (get('termsMode') || data.default_mode || 'field');
      return mode;
    },
    mode: () => mode,
    setMode(m) { mode = m; set('termsMode', m); },
    t(key) {
      const e = data && data.terms && data.terms[key];
      return e ? (e[mode] || e.lab || key) : key;
    },
    tag(id) {
      const e = data && data.tags && data.tags[id];
      return e ? (e[mode] || e.lab || id) : id;
    },
    apply(root = document) {
      root.querySelectorAll('[data-term]').forEach(el => { el.textContent = this.t(el.dataset.term); });
      root.querySelectorAll('[data-tag]').forEach(el => { el.title = this.tag(el.dataset.tag); });
    },
  };
})();

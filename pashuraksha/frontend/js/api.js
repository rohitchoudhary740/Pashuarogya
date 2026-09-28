/* PashuRaksha shared API client + offline report queue + helpers */
/* API origin.
   Same-origin by default (backend serves this app). If the frontend is hosted
   separately — Vercel/Netlify in front of a Render backend — set it with either
     <meta name="pashu-api" content="https://your-api.onrender.com">
   or  <script>window.PASHU_API = 'https://your-api.onrender.com'</script>
   placed before this file. Auth is a Bearer token, not a cookie, so a plain
   CORS allow-list is enough — no credentialed-request setup needed. */
const API = {
  base: (window.PASHU_API ||
         (document.querySelector('meta[name="pashu-api"]') || {}).content ||
         '').replace(/\/+$/, ''),
  token: localStorage.getItem('pr_token') || '',
  user: JSON.parse(localStorage.getItem('pr_user') || 'null'),

  async call(path, opts = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (this.token) headers['Authorization'] = 'Bearer ' + this.token;
    const res = await fetch(this.base + path, { ...opts, headers });
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    return res.json();
  },
  get(p) { return this.call(p); },
  post(p, body) { return this.call(p, { method: 'POST', body: JSON.stringify(body || {}) }); },

  setSession(token, user) {
    this.token = token; this.user = user;
    localStorage.setItem('pr_token', token);
    localStorage.setItem('pr_user', JSON.stringify(user));
  },
  logout() {
    localStorage.removeItem('pr_token'); localStorage.removeItem('pr_user');
    location.href = '/';
  },
  requireRole(...roles) {
    if (!this.user || !roles.includes(this.user.role)) location.href = '/';
  },
};

/* ------------------------- offline queue (farmer reports) ------------------ */
const Queue = {
  KEY: 'pr_queue',
  all() { return JSON.parse(localStorage.getItem(this.KEY) || '[]'); },
  save(q) { localStorage.setItem(this.KEY, JSON.stringify(q)); },
  push(report) {
    const q = this.all();
    report.client_uuid = report.client_uuid ||
      ('cx-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8));
    q.push(report); this.save(q);
    return report.client_uuid;
  },
  async flush() {
    let q = this.all();
    if (!q.length) return 0;
    let sent = 0;
    for (const r of [...q]) {
      try {
        await API.post('/api/reports', r);
        q = q.filter(x => x.client_uuid !== r.client_uuid);
        this.save(q); sent++;
      } catch (e) {
        if (!navigator.onLine) break;   // still offline — stop trying
        // server rejected (validation) — drop so the queue can't jam
        q = q.filter(x => x.client_uuid !== r.client_uuid);
        this.save(q);
      }
    }
    return sent;
  },
  count() { return this.all().length; },
};

window.addEventListener('online', async () => {
  netbar(false);
  const n = await Queue.flush();
  if (n) toast(`✅ ${n} report(s) synced to server`, 'ok');
  document.dispatchEvent(new CustomEvent('pr-synced'));
});
window.addEventListener('offline', () => netbar(true));

function netbar(off) {
  const el = document.getElementById('netbar');
  if (el) el.classList.toggle('off', off);
}

/* -------------------------------- UI helpers ------------------------------ */
function toast(msg, cls = '') {
  let t = document.getElementById('toast');
  if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t); }
  t.textContent = msg; t.className = 'show ' + cls;
  clearTimeout(t._h); t._h = setTimeout(() => t.className = '', 3200);
}
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}
function esc(s) { return String(s ?? '').replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function fmtDT(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) + ' ' +
         d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}
function bandColor(b) {
  return { high: '#B23A2C', moderate: '#C97B18', medium: '#C97B18', low: '#1B7A46' }[b] || '#1B7A46';
}

/* service worker registration (offline shell) */
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

/* re-triggerable view entrance (stagger handled in CSS via .vin) */
window.animView = (v) => {
  if (!v) return;
  v.classList.remove('vin');
  void v.offsetWidth;          // reflow to restart animation
  v.classList.add('vin');
};

/* ============================================================
   LIVE CROSS-DASHBOARD SYNC
   Every dashboard polls /api/sync/state. When any counter moves —
   a farmer files a report, a vet collects a sample, a lab publishes a
   result, an officer approves a claim — every other open dashboard
   refreshes itself. This is what makes alerts feel instant.
   ============================================================ */
const Sync = {
  version: null, timer: null, cbs: [], counts: {}, last: null, paused: false,

  start(cb, ms = 6000) {
    if (cb) this.cbs.push(cb);
    if (this.timer) return;
    const tick = async () => {
      if (this.paused || document.hidden) return;
      try {
        const s = await API.get('/api/sync/state');
        const first = this.version === null;
        const changed = !first && s.version !== this.version;
        const prev = this.counts;
        this.version = s.version; this.counts = s.counts; this.last = s.last_action;
        this.paint(true);
        if (changed) {
          const d = {};
          for (const k in s.counts) {
            const delta = (s.counts[k] || 0) - (prev[k] || 0);
            if (delta) d[k] = delta;
          }
          this.cbs.forEach(f => { try { f(d, s); } catch (e) {} });
          this.announce(d);
        }
      } catch (e) { this.paint(false); }
    };
    tick();
    this.timer = setInterval(tick, ms);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
  },

  /* human-readable "what just changed elsewhere" toast */
  announce(d) {
    const L = (localStorage.getItem('pr_lang') || 'hi');
    const M = {
      cases:        { hi: 'नई रिपोर्ट', mr: 'नवीन तक्रार', en: 'new report' },
      alerts:       { hi: 'नया अलर्ट', mr: 'नवीन सूचना', en: 'new alert' },
      outbreaks:    { hi: 'नया प्रकोप क्लस्टर', mr: 'नवीन उद्रेक', en: 'new outbreak cluster' },
      samples:      { hi: 'नया नमूना', mr: 'नवीन नमुना', en: 'new sample' },
      samples_result:{hi: 'लैब परिणाम आया', mr: 'प्रयोगशाळा निकाल', en: 'lab result published' },
      claims:       { hi: 'नया मुआवजा दावा', mr: 'नवीन भरपाई दावा', en: 'new compensation claim' },
      tasks_done:   { hi: 'कार्य पूरा हुआ', mr: 'कार्य पूर्ण', en: 'task completed' },
      camps:        { hi: 'नया टीकाकरण शिविर', mr: 'नवीन शिबिर', en: 'new vaccination camp' },
      vaccinations: { hi: 'टीकाकरण दर्ज', mr: 'लसीकरण नोंद', en: 'vaccination recorded' },
      treatments:   { hi: 'उपचार दर्ज', mr: 'उपचार नोंद', en: 'treatment recorded' },
      animals:      { hi: 'नया पशु पंजीकृत', mr: 'नवीन जनावर', en: 'animal registered' },
    };
    const parts = [];
    for (const k in d) {
      if (d[k] > 0 && M[k]) parts.push(`${d[k]} ${M[k][L] || M[k].en}`);
    }
    if (parts.length && typeof toast === 'function') {
      toast('🔄 ' + parts.slice(0, 2).join(' · '), 'ok');
    }
  },

  paint(online) {
    const p = document.getElementById('syncPill');
    if (!p) return;
    const L = (localStorage.getItem('pr_lang') || 'hi');
    const lbl = online ? { hi: 'लाइव · डेटाबेस जुड़ा', mr: 'लाइव · डेटाबेस जोडलेले', en: 'Live · database synced' }
                       : { hi: 'ऑफ़लाइन', mr: 'ऑफलाइन', en: 'Offline' };
    p.className = 'syncpill' + (online ? '' : ' busy');
    p.innerHTML = `<span class="dot"></span><span class="lbl">${lbl[L] || lbl.en}</span>`;
    p.title = online && this.last
      ? `Last write: ${this.last.action} ${this.last.detail || ''} — ${this.last.by || ''}`
      : '';
  },
};
window.Sync = Sync;

/* Sticky headers: measure the real header height so the nav band / tab strip
   docks exactly under it instead of guessing a pixel value. */
function syncStickyOffsets() {
  const set = (v, el) => document.documentElement.style
    .setProperty(v, (el ? Math.round(el.getBoundingClientRect().height) : 0) + 'px');
  set('--govtop-h', document.querySelector('.gov-top'));
  set('--govbar-h', document.querySelector('.govbar'));
}
window.addEventListener('load', syncStickyOffsets);
window.addEventListener('resize', syncStickyOffsets);
document.addEventListener('DOMContentLoaded', syncStickyOffsets);

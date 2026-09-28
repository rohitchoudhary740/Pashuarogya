/* Veterinary workspace: triage-ranked case queue → investigation → treatment →
   sample chain-of-custody → lab results. Lab role gets the Lab tab focused. */
API.requireRole('vet', 'lab', 'field');
document.getElementById('who').textContent = `${API.user.name} · ${API.user.role}`;

let KB = null;
let tab = API.user.role === 'lab' ? 'lab' : 'queue';
const view = document.getElementById('view');

const TABS = [
  ['queue', '📋 Case Queue'], ['tasks', '🚑 My Tasks'],
  ['lab', '🧪 Samples & Lab'], ['alerts', '🔔 Alerts'],
];

init();
async function init() {
  try { KB = await API.get('/api/kb'); } catch (e) {}
  renderTabs(); render();
  // live sync — a farmer's new report or a lab result lands here instantly
  Sync.start(d => {
    if (tab === 'queue' && (d.cases || d.samples_result || d.treatments)) queue();
    else if (tab === 'lab' && (d.samples || d.samples_result)) lab();
    else if (tab === 'tasks' && (d.tasks_open || d.tasks_done)) tasks();
    else if (tab === 'alerts' && d.alerts) alerts();
  }, 6000);
}
function renderTabs() {
  const tabs = document.getElementById('tabs');
  tabs.innerHTML = '';
  TABS.forEach(([k, label]) => {
    const b = el('button', 'tab' + (tab === k ? ' active' : ''), label);
    b.onclick = () => { tab = k; renderTabs(); render(); };
    tabs.appendChild(b);
  });
}
function render() { ({ queue, lab, alerts, tasks })[tab](); animView(view); }

/* ------------------------------- CASE QUEUE ------------------------------- */
async function queue() {
  view.innerHTML = '<div class="muted">Loading…</div>';
  let cases = [];
  try { cases = await API.get('/api/cases'); } catch (e) { view.innerHTML = esc(e.message); return; }

  view.innerHTML = '';
  const open = cases.filter(c => !['CLOSED', 'NEGATIVE'].includes(c.status));
  const kpis = el('div', 'kpis');
  const high = open.filter(c => c.triage_band === 'high').length;
  const zoo = open.filter(c => c.zoonotic).length;
  kpis.innerHTML = `
    <div class="kpi crit"><div class="v">${high}</div><div class="l">HIGH triage cases</div></div>
    <div class="kpi warn"><div class="v">${open.filter(c => c.triage_band === 'medium').length}</div><div class="l">Medium triage</div></div>
    <div class="kpi"><div class="v">${open.length}</div><div class="l">Open cases (14 d)</div></div>
    <div class="kpi ${zoo ? 'crit' : 'ok'}"><div class="v">${zoo}</div><div class="l">Zoonotic-flagged</div></div>`;
  view.appendChild(kpis);

  const card = el('div', 'card'); card.style.marginTop = '16px';
  card.innerHTML = `<h3>Triage-ranked queue <span class="muted" style="font-weight:400;
    text-transform:none;font-family:var(--f-b);font-size:12px">— sorted by severity, then time.
    The AI ranks; the veterinarian decides.</span></h3>`;
  const tbl = el('table', '', `<thead><tr>
    <th>#</th><th>Triage</th><th>Village</th><th>Species</th><th>Signs</th>
    <th>Suspected (not diagnosis)</th><th>N / ☠</th><th>Via</th><th>Status</th><th></th>
    </tr></thead>`);
  const tb = el('tbody');
  cases.forEach(c => {
    const tr = el('tr', '', `
      <td class="mono">${c.id}</td>
      <td><span class="chip ${c.triage_band}">${c.triage_band}</span>
          ${c.zoonotic ? '<span class="chip zoo" title="zoonotic">☣</span>' : ''}</td>
      <td>${esc(c.village)}</td>
      <td>${esc(c.species)}</td>
      <td style="max-width:180px;font-size:12px">${c.symptoms.map(esc).join(', ')}</td>
      <td style="font-size:12.5px">${c.suspected_names.map(n => esc(n) + '?').join(', ') || '—'}</td>
      <td class="mono">${c.affected_count}${c.dead_count ? ' / <b style="color:var(--red)">' + c.dead_count + '</b>' : ''}</td>
      <td class="mono" style="font-size:11px">${esc(c.channel)}</td>
      <td class="mono" style="font-size:11px">${esc(c.status)}</td>
      <td><button class="btn sm outline">Open</button></td>`);
    tr.querySelector('button').onclick = () => caseModal(c);
    tb.appendChild(tr);
  });
  tbl.appendChild(tb);
  const scroll = el('div'); scroll.style.overflowX = 'auto';
  scroll.appendChild(tbl); card.appendChild(scroll); view.appendChild(card);
}

function caseModal(c) {
  const m = document.getElementById('modal');
  const syms = (KB && KB.symptoms) || {};
  m.innerHTML = `
    <h2>Case #${c.id} — ${esc(c.village)}</h2>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
      <span class="chip ${c.triage_band}">${c.triage_band} triage</span>
      <span class="chip info">${esc(c.species)}</span>
      <span class="chip info">${esc(c.channel)}</span>
      ${c.zoonotic ? '<span class="chip zoo">☣ zoonotic risk — One Health</span>' : ''}
      <span class="chip info mono">${esc(c.status)}</span>
    </div>
    <p><b>Signs:</b> ${c.symptoms.map(s => `${(syms[s] || {}).icon || ''} ${esc((syms[s] || {}).en || s)}`).join(' · ')}</p>
    <p><b>Affected:</b> ${c.affected_count} &nbsp; <b>Deaths:</b> ${c.dead_count}
       &nbsp; <b>Reported:</b> ${fmtDT(c.reported_at)}</p>
    <p><b>Suspected categories</b> <span class="muted">(rule-based triage — diagnosis is yours)</span>:
       ${c.suspected_names.map(n => `<span class="chip medium">${esc(n)}?</span>`).join(' ') || '—'}</p>
    ${c.samples.length ? `<p><b>Samples:</b> ${c.samples.map(s =>
        `<span class="mono">${esc(s.code)}</span> (${esc(s.lab_result || s.status)})`).join(', ')}</p>` : ''}
    <hr style="border:0;border-top:1px solid var(--hair);margin:14px 0">
    <div class="grid g2">
      <button class="btn sm" data-a="assign">👤 Assign to me</button>
      <button class="btn sm" data-a="investigate">🔍 Start investigation</button>
      <button class="btn sm green" data-a="sample">🧪 Collect sample (QR)</button>
      <button class="btn sm saffron" data-a="escalate">⬆ Escalate to block</button>
    </div>
    <div style="margin-top:14px">
      <label class="muted" style="font-size:12.5px">Clinical diagnosis & treatment (vet only)</label>
      <input id="dx" placeholder="Diagnosis (e.g. LSD — clinical)" style="margin:6px 0">
      <textarea id="tx" rows="2" placeholder="Treatment given / prescribed"></textarea>
      <label class="muted" style="font-size:12px;display:block;margin-top:6px">🥛 Milk/meat withdrawal period (days) —
        farmer gets a countdown in the app &amp; on the animal's passport</label>
      <input id="wd" type="number" min="0" max="60" value="0" style="width:120px;margin:4px 0">
      <div style="display:flex;gap:8px;margin-top:8px">
        <button class="btn sm green" data-a="treat">💊 Record treatment</button>
        <button class="btn sm outline" data-a="close">✓ Close case</button>
      </div>
    </div>`;
  m.querySelectorAll('button[data-a]').forEach(b => {
    b.onclick = async () => {
      const a = b.dataset.a;
      try {
        if (a === 'sample') {
          const s = await API.post(`/api/cases/${c.id}/sample`);
          sampleSlip(s, c);
          return;
        }
        await API.post(`/api/cases/${c.id}/action`, {
          action: a,
          diagnosis: document.getElementById('dx')?.value || '',
          treatment: document.getElementById('tx')?.value || '',
          withdrawal_days: parseInt(document.getElementById('wd')?.value || '0', 10) || 0,
          escalate_to: 'block',
        });
        toast(`Case #${c.id}: ${a} ✓`, 'ok');
        closeModal(); render();
      } catch (e) { toast(e.message, 'err'); }
    };
  });
  openModal();
}

function sampleSlip(s, c) {
  const m = document.getElementById('modal');
  m.innerHTML = `
    <h2>🧪 Sample collected</h2>
    <div style="text-align:center;padding:18px;background:var(--surface-2);border-radius:12px">
      <div class="mono" style="font-size:26px;font-weight:700;letter-spacing:.08em">${esc(s.code)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:6px">
        Chain-of-custody ID · Case #${c.id} · ${esc(c.village)}</div>
      <div style="font-size:52px;margin-top:10px">▣</div>
      <div class="muted" style="font-size:11px">Print & attach to the sample container.
        The farmer can see this sample's status live in their app.</div>
    </div>
    <button class="btn" style="width:100%;margin-top:14px" onclick="closeModal();render()">Done</button>`;
}

/* ---------------------------------- LAB ----------------------------------- */
async function lab() {
  view.innerHTML = '<div class="muted">Loading…</div>';
  let samples = [];
  try { samples = await API.get('/api/samples'); } catch (e) { view.innerHTML = esc(e.message); return; }
  view.innerHTML = '';

  const flow = ['COLLECTED', 'DISPATCHED', 'RECEIVED', 'TESTING', 'RESULT'];
  const kpis = el('div', 'kpis');
  kpis.innerHTML = flow.map(f => {
    const n = samples.filter(s => s.status === f).length;
    return `<div class="kpi ${f === 'RESULT' ? 'ok' : ''}"><div class="v">${n}</div><div class="l">${f}</div></div>`;
  }).join('');
  view.appendChild(kpis);

  const card = el('div', 'card'); card.style.marginTop = '16px';
  card.innerHTML = `<h3>Sample chain-of-custody</h3>`;
  const tbl = el('table', '', `<thead><tr><th>Code</th><th>Case</th><th>Village</th>
    <th>Species</th><th>Suspected</th><th>Status</th><th>Result</th><th>Action</th></tr></thead>`);
  const tb = el('tbody');
  const diseases = (KB && KB.diseases) || {};
  samples.forEach(s => {
    const nextIdx = flow.indexOf(s.status) + 1;
    const next = flow[nextIdx];
    const tr = el('tr');
    tr.innerHTML = `
      <td class="mono"><b>${esc(s.code)}</b></td>
      <td class="mono">#${s.case_id}</td>
      <td>${esc(s.village || '')}</td>
      <td>${esc(s.species || '')}</td>
      <td style="font-size:12px">${esc(s.suspected || '')}</td>
      <td><span class="chip ${s.status === 'RESULT' ? 'low' : 'info'}">${esc(s.status)}</span></td>
      <td>${s.lab_result ? `<span class="chip ${s.lab_result}">${esc(s.lab_result)}</span>
          <span class="mono" style="font-size:10.5px">${esc(s.result_disease || '')}</span>` : '—'}</td>
      <td></td>`;
    const actions = tr.lastElementChild;
    if (s.status === 'TESTING') {
      const sel = el('select');
      sel.style.cssText = 'width:auto;padding:5px 8px;font-size:12px;margin-right:6px';
      sel.innerHTML = Object.entries(diseases).map(([k, d]) =>
        `<option value="${k}">${esc(d.name.en)}</option>`).join('');
      if (s.suspected) sel.value = s.suspected.split(',')[0] in diseases ? s.suspected.split(',')[0] : sel.value;
      const pos = el('button', 'btn sm danger', 'Positive');
      const neg = el('button', 'btn sm green', 'Negative');
      pos.style.marginRight = '5px';
      pos.onclick = () => publishResult(s, 'positive', sel.value);
      neg.onclick = () => publishResult(s, 'negative', '');
      actions.append(sel, pos, neg);
    } else if (next && s.status !== 'RESULT') {
      const b = el('button', 'btn sm outline', `→ ${next}`);
      b.onclick = async () => {
        await API.post(`/api/samples/${s.id}`, { status: next });
        toast(`${s.code} → ${next}`, 'ok'); render();
      };
      actions.appendChild(b);
    }
    tb.appendChild(tr);
  });
  tbl.appendChild(tb);
  const scroll = el('div'); scroll.style.overflowX = 'auto';
  scroll.appendChild(tbl); card.appendChild(scroll); view.appendChild(card);
}

async function publishResult(s, result, disease) {
  try {
    await API.post(`/api/samples/${s.id}`, { lab_result: result, result_disease: disease });
    toast(result === 'positive'
      ? `⚠ ${s.code} POSITIVE — case confirmed, authorities alerted`
      : `${s.code} negative — case cleared`, result === 'positive' ? 'err' : 'ok');
    render();
  } catch (e) { toast(e.message, 'err'); }
}

/* -------------------------------- MY TASKS -------------------------------- */
const TASK_IC = { mvu_dispatch: '🚑', sample_collection: '🧪',
                  ring_vaccination: '💉', verification: '🔍' };
async function tasks() {
  view.innerHTML = '<div class="muted">Loading…</div>';
  let rows = [];
  try { rows = await API.get('/api/tasks'); } catch (e) { view.innerHTML = esc(e.message); return; }
  const myRole = API.user.role === 'field' ? 'vet' : API.user.role;  // field works vet tasks
  const mine = rows.filter(x => x.assigned_role === myRole || x.assigned_role === API.user.role);
  const open = mine.filter(x => x.status !== 'DONE');
  view.innerHTML = '';
  const kpis = el('div', 'kpis');
  kpis.innerHTML = `
    <div class="kpi ${open.length ? 'warn' : 'ok'}"><div class="v">${open.length}</div>
      <div class="l">Open field tasks</div></div>
    <div class="kpi ok"><div class="v">${mine.filter(x => x.status === 'DONE').length}</div>
      <div class="l">Completed</div></div>`;
  view.appendChild(kpis);
  const card = el('div', 'card'); card.style.marginTop = '16px';
  card.innerHTML = `<h3>Dispatch &amp; containment tasks
    <span class="muted" style="font-weight:400;text-transform:none;font-family:var(--f-b);
    font-size:12px">— auto-created by the Outbreak Radar; completing them is the containment record.</span></h3>`;
  if (!mine.length) card.appendChild(el('div', 'muted', 'No tasks assigned to your role.'));
  mine.forEach(x => {
    const d = el('div', '', `
      <div style="display:flex;gap:12px;align-items:flex-start;padding:11px 0;
        border-bottom:1px solid var(--surface-2);${x.status === 'DONE' ? 'opacity:.5' : ''}">
        <span style="font-size:22px">${TASK_IC[x.kind] || '📌'}</span>
        <div style="flex:1"><b style="font-size:14px">${esc(x.title)}</b>
          <div class="mono" style="font-size:10.5px;color:var(--muted);margin-top:3px">
            📍 ${esc(x.village || '')} · ${fmtDT(x.created_at)} ·
            <span class="chip ${x.status === 'DONE' ? 'low' : x.status === 'IN_PROGRESS' ? 'medium' : 'info'}">${x.status}</span></div></div>
        <span class="acts" style="display:flex;gap:6px;flex:0 0 auto"></span></div>`);
    const acts = d.querySelector('.acts');
    if (x.status === 'OPEN') {
      const b = el('button', 'btn sm outline', 'Start');
      b.onclick = async () => { await API.post('/api/tasks/' + x.id, { status: 'IN_PROGRESS' }); render(); };
      acts.appendChild(b);
    }
    if (x.status !== 'DONE') {
      const b = el('button', 'btn sm green', '✓ Done');
      b.onclick = async () => { await API.post('/api/tasks/' + x.id, { status: 'DONE' });
        toast('Task completed ✓', 'ok'); render(); };
      acts.appendChild(b);
    }
    card.appendChild(d);
  });
  view.appendChild(card);
}

/* --------------------------------- ALERTS --------------------------------- */
async function alerts() {
  view.innerHTML = '';
  let list = [];
  try { list = await API.get('/api/alerts'); } catch (e) {}
  const card = el('div', 'card', `<h3>Alerts for ${esc(API.user.role)}</h3>`);
  if (!list.length) card.appendChild(el('div', 'muted', 'No alerts'));
  list.forEach(a => {
    const item = el('div', `alert-item ${a.severity}`, `
      <div class="t">${esc(a.title)}</div><div class="b">${esc(a.body)}</div>
      <div class="meta">${a.village ? '📍 ' + esc(a.village) + ' · ' : ''}${fmtDT(a.created_at)}
        ${a.acknowledged ? ' · ✓ ack' : ''}</div>`);
    if (!a.acknowledged) {
      const b = el('button', 'btn sm outline', 'Acknowledge');
      b.style.marginTop = '6px';
      b.onclick = async () => { await API.post(`/api/alerts/${a.id}/ack`); render(); };
      item.appendChild(b);
    }
    card.appendChild(item);
  });
  view.appendChild(card);
}

/* --------------------------------- modal ---------------------------------- */
function openModal() { document.getElementById('modalBg').classList.add('open'); }
function closeModal() { document.getElementById('modalBg').classList.remove('open'); }
document.getElementById('modalBg').addEventListener('click', e => {
  if (e.target.id === 'modalBg') closeModal();
});

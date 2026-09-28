/* पशु मित्र — PashuAarogya voice assistant.
   Speech in (Web Speech API) · speech out (SpeechSynthesis) · rule-based intent
   router with page-specific "skills". Hindi by default, Marathi/English on toggle.
   No cloud LLM: works offline for navigation/help, uses the platform API for data. */
(function () {
  const LANGS = { hi: 'hi-IN', mr: 'mr-IN', en: 'en-IN' };
  const lang = () => (window.LANG || localStorage.getItem('pr_lang') || 'hi');

  /* ---------------------------------------------------------- speech out --- */
  // Indicators for female voices across Windows (Swara, Kalpana, Neerja, Heera, Zira),
  // Chrome / Android (Google voices, natural female voices, etc.)
  const FEMALE_VOICE_REGEX = /(swara|kalpana|neerja|heera|zira|priya|aditi|veena|shreya|ananya|sangeeta|geeta|radha|sunita|rekha|kavita|jyoti|meera|pooja|divya|aarohi|jenny|aria|samantha|victoria|karen|female|woman|girl|natural)/i;
  const MALE_VOICE_REGEX = /(hemant|madhav|ravi|prabhat|david|mark|george|guy|male\b|man\b|boy\b)/i;

  function pickFemaleVoice(want) {
    if (!('speechSynthesis' in window)) return null;
    const voices = speechSynthesis.getVoices() || [];
    if (!voices.length) return null;

    let targetLang = want || 'hi';
    let pool = voices.filter(x => x.lang && x.lang.toLowerCase().startsWith(targetLang));
    if (!pool.length && targetLang === 'mr') {
      pool = voices.filter(x => x.lang && x.lang.toLowerCase().startsWith('hi'));
    }

    // 1. Explicit female voice for target language
    let v = pool.find(x => FEMALE_VOICE_REGEX.test(x.name) && !MALE_VOICE_REGEX.test(x.name));
    // 2. Non-male voice for target language
    if (!v) v = pool.find(x => !MALE_VOICE_REGEX.test(x.name));
    // 3. Any voice for target language
    if (!v && pool.length) v = pool[0];
    // 4. Any Indian female voice
    if (!v) {
      v = voices.find(x => (x.lang.toLowerCase().includes('in') || x.lang.toLowerCase().startsWith('hi')) &&
                           FEMALE_VOICE_REGEX.test(x.name) && !MALE_VOICE_REGEX.test(x.name));
    }
    // 5. Any female voice at all in the browser
    if (!v) v = voices.find(x => FEMALE_VOICE_REGEX.test(x.name) && !MALE_VOICE_REGEX.test(x.name));

    return v;
  }

  window.speak = function speak(text) {
    return new Promise(resolve => {
      if (!('speechSynthesis' in window) || !text) return resolve(false);
      const want = lang();

      const doSpeak = () => {
        const v = pickFemaleVoice(want);
        const u = new SpeechSynthesisUtterance(text);
        if (v) {
          u.voice = v;
          u.lang = v.lang;
        } else {
          u.lang = LANGS[want] || 'hi-IN';
        }
        // Female vocal tuning: 1.18 pitch provides a distinct, pleasant feminine tone across all OS voices
        u.pitch = 1.18;
        u.rate = 0.94;
        u.onend = () => resolve(true);
        u.onerror = () => resolve(false);
        speechSynthesis.cancel();
        speechSynthesis.speak(u);
      };

      const existingVoices = speechSynthesis.getVoices();
      if (!existingVoices || existingVoices.length === 0) {
        let fired = false;
        const onVoices = () => {
          if (!fired) {
            fired = true;
            speechSynthesis.removeEventListener('voiceschanged', onVoices);
            doSpeak();
          }
        };
        speechSynthesis.addEventListener('voiceschanged', onVoices);
        setTimeout(() => {
          if (!fired) {
            fired = true;
            speechSynthesis.removeEventListener('voiceschanged', onVoices);
            doSpeak();
          }
        }, 200);
      } else {
        doSpeak();
      }
    });
  };

  /* --------------------------------------------------------------- strings -- */
  const T = {
    hi: { title: 'पशु मित्र', sub: 'आवाज़ सहायक · बोलकर पूछें',
      hint: 'बोलिए — जैसे "मेरी गाय बीमार है", "टीकाकरण शिविर कब है", "मुआवजा"',
      listening: '🎧 सुन रही हूँ…', type: 'या यहाँ लिखें…', ask: 'पूछें',
      nosr: 'इस ब्राउज़र में आवाज़ पहचान नहीं है — नीचे लिखकर पूछें।',
      greet: 'नमस्ते! मैं पशु मित्र हूँ। बताइए, कैसे मदद करूँ?',
      fallback: 'माफ़ कीजिए, समझ नहीं आया। आप ये कह सकते हैं:', mic: 'बोलें' },
    mr: { title: 'पशु मित्र', sub: 'आवाज सहाय्यक · बोलून विचारा',
      hint: 'बोला — जसे "माझी गाय आजारी आहे", "लसीकरण शिबिर कधी", "भरपाई"',
      listening: '🎧 ऐकत आहे…', type: 'किंवा इथे लिहा…', ask: 'विचारा',
      nosr: 'या ब्राउझरमध्ये आवाज ओळख नाही — खाली लिहून विचारा.',
      greet: 'नमस्कार! मी पशु मित्र. सांगा, कशी मदत करू?',
      fallback: 'माफ करा, समजले नाही. तुम्ही असे विचारू शकता:', mic: 'बोला' },
    en: { title: 'Pashu Mitra', sub: 'Voice assistant · just ask',
      hint: 'Say — "my cow is sick", "when is the vaccination camp", "compensation"',
      listening: '🎧 Listening…', type: 'or type here…', ask: 'Ask',
      nosr: 'Voice recognition is not available in this browser — type below.',
      greet: 'Namaste! I am Pashu Mitra. How can I help?',
      fallback: "Sorry, I didn't get that. You can say:", mic: 'Speak' },
  };
  const t = k => (T[lang()] || T.hi)[k];

  /* ------------------------------------------------------------------ CSS -- */
  const CSS = `
  .pm-fab{position:fixed;right:16px;z-index:1500;width:58px;height:58px;border-radius:50%;border:0;
    background:linear-gradient(135deg,#F4801F,#E8720C);color:#fff;font-size:26px;cursor:pointer;
    box-shadow:0 10px 26px -8px rgba(232,114,12,.65),0 2px 6px rgba(0,0,0,.15);
    display:flex;align-items:center;justify-content:center;transition:transform 160ms cubic-bezier(.23,1,.32,1)}
  .pm-fab:active{transform:scale(.94)}
  .pm-fab .lbl{position:absolute;right:66px;top:50%;transform:translateY(-50%);background:#123566;color:#fff;
    font-size:12px;font-weight:600;padding:5px 10px;border-radius:8px;white-space:nowrap;font-family:var(--f-b,sans-serif);
    opacity:0;transition:opacity 200ms;pointer-events:none}
  .pm-fab:hover .lbl,.pm-fab.show-lbl .lbl{opacity:1}
  .pm-fab.rec{animation:pmpulse 1.1s infinite}
  @keyframes pmpulse{50%{box-shadow:0 0 0 14px rgba(232,114,12,.18)}}
  .pm-bg{position:fixed;inset:0;background:rgba(11,42,84,.45);z-index:1600;opacity:0;visibility:hidden;
    transition:opacity 150ms,visibility 0s linear 150ms;display:flex;align-items:flex-end;justify-content:center}
  .pm-bg.open{opacity:1;visibility:visible;transition:opacity 200ms,visibility 0s}
  .pm-sheet{background:#fff;width:100%;max-width:520px;border-radius:20px 20px 0 0;padding:16px 18px
    calc(16px + env(safe-area-inset-bottom));max-height:82vh;display:flex;flex-direction:column;gap:10px;
    transform:translateY(24px);transition:transform 150ms cubic-bezier(.23,1,.32,1);
    box-shadow:0 -12px 40px rgba(0,0,0,.25);font-family:var(--f-b,sans-serif);color:#1C2434}
  .pm-bg.open .pm-sheet{transform:translateY(0);transition:transform 280ms cubic-bezier(.32,.72,0,1)}
  .pm-hd{display:flex;align-items:center;gap:10px}
  .pm-hd .av{width:42px;height:42px;border-radius:50%;background:linear-gradient(135deg,#FCEDDD,#F8D9BC);
    display:flex;align-items:center;justify-content:center;font-size:22px;border:2px solid #E8720C}
  .pm-hd b{font-family:var(--f-d,sans-serif);font-size:18px;display:block;line-height:1.05}
  .pm-hd .s{font-size:11.5px;color:#5D6579}
  .pm-x{margin-left:auto;background:#F0EEE7;border:0;width:34px;height:34px;border-radius:50%;font-size:16px;cursor:pointer}
  .pm-log{overflow-y:auto;display:flex;flex-direction:column;gap:8px;min-height:120px;max-height:46vh;padding:4px 2px}
  .pm-m{max-width:88%;padding:10px 13px;border-radius:14px;font-size:14.5px;line-height:1.45;
    animation:pmin 220ms cubic-bezier(.23,1,.32,1)}
  @keyframes pmin{from{opacity:0;transform:translateY(6px)}}
  .pm-m.u{align-self:flex-end;background:#1B4C8C;color:#fff;border-bottom-right-radius:4px}
  .pm-m.a{align-self:flex-start;background:#F0EEE7;border-bottom-left-radius:4px}
  .pm-m.a .acts{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
  .pm-m.a .acts button{background:#fff;border:1.5px solid #1B4C8C;color:#1B4C8C;border-radius:99px;
    padding:5px 12px;font-size:13px;font-weight:600;cursor:pointer}
  .pm-m.a .acts button:active{transform:scale(.97)}
  .pm-hint{font-size:12px;color:#5D6579;text-align:center}
  .pm-row{display:flex;gap:8px;align-items:center}
  .pm-row input{flex:1;padding:11px 13px;border:1.5px solid #DDD9CE;border-radius:12px;font-size:14.5px;
    font-family:inherit}
  .pm-mic{width:52px;height:52px;border-radius:50%;border:0;background:linear-gradient(135deg,#F4801F,#E8720C);
    color:#fff;font-size:22px;cursor:pointer;flex:0 0 52px;transition:transform 160ms cubic-bezier(.23,1,.32,1)}
  .pm-mic:active{transform:scale(.92)}
  .pm-mic.rec{background:#B23A2C;animation:pmpulse 1.1s infinite}
  .pm-ex{display:flex;gap:6px;flex-wrap:wrap}
  .pm-ex button{background:#fff;border:1px solid #DDD9CE;border-radius:99px;padding:5px 11px;font-size:12.5px;cursor:pointer}
  @media(prefers-reduced-motion:reduce){.pm-fab,.pm-sheet,.pm-m{animation:none;transition:none}}`;

  /* ------------------------------------------------------------------ core -- */
  const A = {
    skills: [], page: 'farmer', examples: [], offsetBottom: 24, rec: null, greeted: false,
    llm: null, hist: [], onAction: null,

    init(opts = {}) {
      Object.assign(this, opts);
      const st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);
      const fab = document.createElement('button');
      fab.className = 'pm-fab'; fab.id = 'pmFab';
      fab.style.bottom = this.offsetBottom + 'px';
      fab.innerHTML = `🎙️<span class="lbl">${t('title')}</span>`;
      fab.title = t('title');
      fab.onclick = () => this.open(true);
      document.body.appendChild(fab);
      setTimeout(() => { fab.classList.add('show-lbl'); setTimeout(() => fab.classList.remove('show-lbl'), 3200); }, 1200);

      const bg = document.createElement('div'); bg.className = 'pm-bg'; bg.id = 'pmBg';
      bg.innerHTML = `<div class="pm-sheet" role="dialog" aria-label="${t('title')}">
        <div class="pm-hd"><div class="av">👩‍🌾</div><div><b>${t('title')}</b><span class="s">${t('sub')}</span></div>
          <button class="pm-x" id="pmClose">✕</button></div>
        <div class="pm-log" id="pmLog"></div>
        <div class="pm-ex" id="pmEx"></div>
        <div class="pm-row"><input id="pmIn" placeholder="${t('type')}">
          <button class="pm-mic" id="pmMic" title="${t('mic')}">🎤</button></div>
        <div class="pm-hint" id="pmHint">${this.hint || t('hint')}</div></div>`;
      document.body.appendChild(bg);
      bg.onclick = e => { if (e.target === bg) this.close(); };
      document.getElementById('pmClose').onclick = () => this.close();
      document.getElementById('pmMic').onclick = () => this.listen();
      const inp = document.getElementById('pmIn');
      inp.addEventListener('keydown', e => { if (e.key === 'Enter' && inp.value.trim()) { this.handle(inp.value.trim()); inp.value = ''; } });
      const ex = document.getElementById('pmEx');
      ex.innerHTML = this.examples.map(x => `<button>${x}</button>`).join('');
      ex.querySelectorAll('button').forEach(b => b.onclick = () => this.handle(b.textContent));
      if (location.hash === '#mitra') setTimeout(() => this.open(false), 700);   // deep-link
      // LLM brain available? (Gemini via backend; key never reaches the browser)
      this.checkLLM = () => {
        fetch('/api/assistant/status').then(r => r.json()).then(s => {
          this.llm = s.llm ? s : null;
          const sub = bg.querySelector('.pm-hd .s');
          if (s.llm && sub) {
            sub.innerHTML = t('sub') + ' · <span style="color:#7C3AED;font-weight:600">✨ Gemini</span>';
          }
        }).catch(() => {});
      };
      this.checkLLM();
    },

    open(autoListen = false) {
      if (this.checkLLM) this.checkLLM();
      document.getElementById('pmBg').classList.add('open');
      if (!this.greeted) { this.greeted = true; this.reply(t('greet')); }
      if (autoListen && (window.SpeechRecognition || window.webkitSpeechRecognition)) setTimeout(() => this.listen(), 350);
    },
    close() { document.getElementById('pmBg').classList.remove('open'); if (this.rec) this.rec.stop(); speechSynthesis && speechSynthesis.cancel(); },

    say(m, cls = 'a', actions = []) {
      const log = document.getElementById('pmLog');
      const d = document.createElement('div'); d.className = 'pm-m ' + cls;
      d.innerHTML = m + (actions.length ? '<div class="acts"></div>' : '');
      if (actions.length) actions.forEach(a => {
        const b = document.createElement('button'); b.textContent = a.label;
        b.onclick = () => { a.run(); if (a.close !== false) this.close(); };
        d.querySelector('.acts').appendChild(b);
      });
      log.appendChild(d); log.scrollTop = log.scrollHeight;
    },
    reply(text, actions = [], spoken) { this.say(text, 'a', actions); return speak(spoken || text.replace(/<[^>]+>/g, '')); },

    listen() {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      const mic = document.getElementById('pmMic'), hint = document.getElementById('pmHint');
      if (!SR) { hint.textContent = t('nosr'); return; }
      if (this.rec) { this.rec.stop(); return; }
      speechSynthesis && speechSynthesis.cancel();
      const rec = new SR(); this.rec = rec;
      rec.lang = LANGS[lang()] || 'hi-IN'; rec.interimResults = false; rec.maxAlternatives = 1;
      mic.classList.add('rec'); document.getElementById('pmFab').classList.add('rec'); hint.textContent = t('listening');
      rec.onresult = e => { this.handle(e.results[0][0].transcript); };
      rec.onend = () => { mic.classList.remove('rec'); document.getElementById('pmFab').classList.remove('rec');
        hint.textContent = this.hint || t('hint'); this.rec = null; };
      rec.onerror = () => { rec.onend(); };
      rec.start();
    },

    async handle(q) {
      this.say(q, 'u');
      this.hist.push({ role: 'user', text: q });
      const ql = q.toLowerCase();
      // 1) precise rule-based skills: instant, offline, they act directly
      for (const s of this.skills) {
        if (s.match(ql)) {
          try { const r = await s.run(q, ql); if (r) { this.hist.push({ role: 'assistant', text: r.text.replace(/<[^>]+>/g, '') });
            await this.reply(r.text, r.actions || [], r.spoken); } }
          catch (e) { this.reply('⚠ ' + (e.message || 'error')); }
          return;
        }
      }
      // 2) Gemini: free-form questions with live context from the platform
      if (this.llm) { await this.askLLM(q); return; }
      this.reply(`${t('fallback')}<br>${this.examples.map(x => '• ' + x).join('<br>')}`, [], t('fallback'));
    },

    async askLLM(q) {
      const log = document.getElementById('pmLog');
      const think = document.createElement('div'); think.className = 'pm-m a';
      think.innerHTML = '<span style="opacity:.6">✨ …</span>'; log.appendChild(think); log.scrollTop = log.scrollHeight;
      try {
        const r = await API.post('/api/assistant/chat', {
          query: q, lang: lang(), page: this.page, history: this.hist.slice(-8, -1) });
        think.remove();
        this.hist.push({ role: 'assistant', text: r.reply });
        if (this.hist.length > 16) this.hist = this.hist.slice(-16);
        const act = r.action, btns = [];
        if (act && this.onAction) {
          const label = act.type === 'report' ? { hi: '📢 रिपोर्ट भरें', mr: '📢 तक्रार भरा', en: '📢 File report' }[lang()]
                      : { hi: '↗ खोलें', mr: '↗ उघडा', en: '↗ Open' }[lang()];
          btns.push({ label, run: () => this.onAction(act) });
        }
        const tag = `<div style="font-size:10px;color:#7C3AED;margin-top:6px">✨ Gemini · ${esc(r.model || '')}</div>`;
        await this.reply(esc(r.reply) + tag, btns, r.reply);
        // a recognised sick-animal description pre-fills the report automatically
        if (act && act.type === 'report' && this.onAction) { setTimeout(() => { this.onAction(act); this.close(); }, 600); }
      } catch (e) {
        think.remove();
        this.reply(`${t('fallback')}<br>${this.examples.map(x => '• ' + x).join('<br>')}`, [], t('fallback'));
        console.warn('assistant LLM error', e);
      }
    },
  };

  /* keyword helper: any of the words appears in the query */
  A.kw = (ql, words) => words.some(w => ql.includes(w.toLowerCase()));
  window.PashuMitra = A;
})();

/* ============================ GUIDED VOICE INTERVIEW ========================
   A farmer rarely volunteers a full clinical picture. Left to an open mic they
   say "my cow is sick" and stop. So पशु मित्र runs the consultation the way a
   vet would on the phone: one short question at a time, in the farmer's own
   language, about things they can actually observe — is the milk down, is she
   eating, is the body hot, any lumps.

   Each answer maps to a symptom code the triage engine already understands, so
   a spoken conversation produces exactly the same structured case a tapped form
   does — including when the illness started, which is what makes reporting
   delay measurable.
   ========================================================================== */
(function () {
  const A = window.PashuMitra;
  if (!A) return;
  const lang = () => (window.LANG || localStorage.getItem('pr_lang') || 'hi');
  const L = (hi, mr, en) => (lang() === 'mr' ? mr : lang() === 'en' ? en : hi);

  /* ------------------------------------------------------------ parsing --- */
  const tokens = q => String(q).toLowerCase().replace(/[।,.!?]/g, ' ').split(/\s+/).filter(Boolean);
  const YES = ['हाँ', 'हां', 'हा', 'होय', 'जी', 'है', 'हैं', 'आहे', 'हो', 'yes', 'yeah', 'yep', 'y', 'ok'];
  const NO = ['नहीं', 'नही', 'ना', 'नाही', 'नको', 'no', 'nope', 'n'];
  const NUMW = {
    'एक': 1, 'दो': 2, 'दोन': 2, 'तीन': 3, 'चार': 4, 'पांच': 5, 'पाँच': 5, 'पाच': 5,
    'छह': 6, 'सहा': 6, 'सात': 7, 'आठ': 8, 'नौ': 9, 'नऊ': 9, 'दस': 10, 'दहा': 10,
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7,
    'eight': 8, 'nine': 9, 'ten': 10, 'कोई': 0, 'कोणी': 0, 'none': 0, 'zero': 0,
  };

  // "ना" is a whole word for "no" but also sits inside जानवर, so match tokens,
  // never substrings. A wrong yes/no here would quietly corrupt the case.
  const said = (q, list) => tokens(q).some(w => list.includes(w));
  const yesNo = q => (said(q, NO) ? false : said(q, YES) ? true : null);

  function num(q) {
    const m = String(q).match(/\d+/);
    if (m) return parseInt(m[0], 10);
    for (const w of tokens(q)) if (w in NUMW) return NUMW[w];
    return null;
  }

  function onsetDays(q) {
    const s = String(q).toLowerCase();
    if (/आज|today/.test(s)) return 0;
    if (/कल|काल|yesterday/.test(s)) return 1;
    if (/परसों|परवा/.test(s)) return 2;
    const n = num(q);
    if (n == null) return null;
    if (/हफ्ता|हफ़्ता|सप्ताह|आठवड|week/.test(s)) return n * 7;
    if (/महीन|महिन|month/.test(s)) return n * 30;
    return n;                                   // a bare number means days
  }

  const SPK = {
    cattle: ['गाय', 'गाई', 'cow', 'cattle', 'बैल'], buffalo: ['भैंस', 'भैस', 'म्हैस', 'buffalo'],
    goat: ['बकरी', 'शेळी', 'goat'], sheep: ['भेड़', 'भेड', 'मेंढी', 'sheep'],
    poultry: ['मुर्गी', 'मुर्गा', 'कोंबडी', 'poultry', 'chicken'],
  };
  const species = q => Object.keys(SPK).find(k => SPK[k].some(w => String(q).toLowerCase().includes(w)));

  /* ---------------------------------------------------------- questions --- */
  // `sym` is the symptom code added when the answer is yes; `symNo` when it is
  // no — a cow that has stopped eating is the classic "no" that matters.
  const Q = [
    {
      id: 'species', type: 'species',
      ask: () => L('कौन सा पशु बीमार है? गाय, भैंस, बकरी, भेड़ या मुर्गी?',
        'कोणते जनावर आजारी आहे? गाय, म्हैस, शेळी, मेंढी की कोंबडी?',
        'Which animal is ill — cow, buffalo, goat, sheep or poultry?'),
      chips: () => [L('गाय', 'गाय', 'Cow'), L('भैंस', 'म्हैस', 'Buffalo'),
        L('बकरी', 'शेळी', 'Goat'), L('मुर्गी', 'कोंबडी', 'Poultry')],
    },
    {
      id: 'onset', type: 'onset',
      ask: () => L('कब से बीमार है? जैसे — आज, कल, या तीन दिन से।',
        'किती दिवसांपासून आजारी आहे? जसे — आज, काल, किंवा तीन दिवस.',
        'How long has it been ill? Say today, yesterday, or three days.'),
      chips: () => [L('आज से', 'आजपासून', 'Today'), L('कल से', 'काल पासून', 'Yesterday'),
        L('तीन दिन', 'तीन दिवस', '3 days'), L('एक हफ्ता', 'एक आठवडा', 'A week')],
    },
    {
      id: 'milk', type: 'yesno', sym: 'low_milk',
      skip: d => d.species === 'poultry',
      ask: () => L('क्या दूध कम हो गया है?', 'दूध कमी झाले आहे का?', 'Has the milk gone down?'),
    },
    {
      id: 'egg', type: 'yesno', sym: 'egg_drop',
      skip: d => d.species !== 'poultry',
      ask: () => L('क्या अंडे कम हो गए हैं?', 'अंडी कमी झाली आहेत का?', 'Have eggs dropped?'),
    },
    {
      id: 'eating', type: 'yesno', symNo: 'anorexia',
      ask: () => L('क्या पशु चारा खा रहा है?', 'जनावर चारा खात आहे का?', 'Is the animal eating?'),
    },
    {
      id: 'fever', type: 'yesno', sym: 'fever',
      ask: () => L('शरीर गरम लग रहा है, बुखार है?', 'अंग गरम आहे का, ताप आहे?',
        'Does the body feel hot — any fever?'),
    },
    {
      id: 'skin', type: 'yesno', sym: 'nodules',
      ask: () => L('शरीर पर गांठें या घाव दिख रहे हैं?', 'अंगावर गाठी किंवा जखमा दिसतात का?',
        'Any lumps or sores on the body?'),
    },
    {
      id: 'mouth', type: 'yesno', sym: 'oral_lesions',
      ask: () => L('मुँह या खुर में छाले हैं, या मुँह से लार गिर रही है?',
        'तोंडात किंवा खुरात फोड आहेत, किंवा तोंडातून लाळ गळते का?',
        'Blisters in the mouth or hoof, or drooling?'),
    },
    {
      id: 'count', type: 'number',
      ask: () => L('कितने पशु बीमार हैं?', 'किती जनावरे आजारी आहेत?', 'How many animals are ill?'),
      chips: () => ['1', '2', '3', '5'],
    },
    {
      id: 'dead', type: 'number',
      ask: () => L('क्या कोई पशु मरा है? कितने?', 'एखादे जनावर मेले आहे का? किती?',
        'Has any animal died? How many?'),
      chips: () => [L('कोई नहीं', 'कोणी नाही', 'None'), '1', '2'],
    },
  ];

  /* ------------------------------------------------------------- engine --- */
  A.startInterview = function (seed) {
    this.interview = {
      i: 0,
      data: Object.assign({
        species: null, symptoms: [], onset_days_ago: null,
        affected_count: 1, dead_count: 0,
      }, seed || {}),
    };
    this.open(false);
    this.reply(L('ठीक है, कुछ छोटे सवाल पूछता हूँ। आप बोलकर या टैप करके जवाब दें।',
      'ठीक आहे, काही छोटे प्रश्न विचारतो. बोलून किंवा टॅप करून उत्तर द्या.',
      'Alright, a few short questions. Answer by voice or tap.'))
      .then(() => this.nextQuestion());
  };

  A.nextQuestion = function () {
    const iv = this.interview;
    if (!iv) return;
    while (iv.i < Q.length && Q[iv.i].skip && Q[iv.i].skip(iv.data)) iv.i++;
    if (iv.i >= Q.length) return this.finishInterview();
    const q = Q[iv.i];
    const chips = (q.chips ? q.chips() : [L('हाँ', 'होय', 'Yes'), L('नहीं', 'नाही', 'No')])
      .map(c => ({ label: c, close: false, run: () => this.handle(c) }));
    const step = `<div style="font-size:10.5px;opacity:.6;margin-bottom:3px">${iv.i + 1} / ${Q.length}</div>`;
    this.reply(step + q.ask(), chips, q.ask()).then(() => {
      // hands-free: start listening again the moment the question finishes
      if (window.SpeechRecognition || window.webkitSpeechRecognition) {
        setTimeout(() => { if (this.interview) this.listen(); }, 250);
      }
    });
  };

  A.interviewAnswer = function (raw) {
    const iv = this.interview;
    const q = Q[iv.i], d = iv.data;
    let ok = true;
    if (q.type === 'species') {
      const sp = species(raw);
      if (sp) d.species = sp; else ok = false;
    } else if (q.type === 'onset') {
      const days = onsetDays(raw);
      if (days != null) d.onset_days_ago = days; else ok = false;
    } else if (q.type === 'number') {
      const v = num(raw);
      if (v == null) ok = false;
      else if (q.id === 'count') d.affected_count = Math.max(1, v);
      else d.dead_count = Math.max(0, v);
    } else {                                   // yes / no
      const v = yesNo(raw);
      if (v == null) ok = false;
      else {
        const code = v ? q.sym : q.symNo;
        if (code && !d.symptoms.includes(code)) d.symptoms.push(code);
      }
    }
    if (!ok) {                                 // not understood — ask again
      return this.reply(L('माफ़ कीजिए, समझ नहीं आया। फिर से बताइए।',
        'माफ करा, समजले नाही. पुन्हा सांगा.',
        "Sorry, I didn't catch that. Please say it again."))
        .then(() => this.nextQuestion());
    }
    iv.i++;
    this.nextQuestion();
  };

  A.finishInterview = function () {
    const d = this.interview.data;
    this.interview = null;
    const SPN = {
      cattle: L('गाय', 'गाय', 'Cow'), buffalo: L('भैंस', 'म्हैस', 'Buffalo'),
      goat: L('बकरी', 'शेळी', 'Goat'), sheep: L('भेड़', 'मेंढी', 'Sheep'),
      poultry: L('मुर्गी', 'कोंबडी', 'Poultry'),
    };
    // KB is declared with let in farmer.js, so it is NOT on window — reach it
    // by identifier, guarded for the pages that never load a knowledge base.
    const kb = (typeof KB !== 'undefined' && KB && KB.symptoms) || {};
    const symNames = d.symptoms.map(c => (kb[c] && (kb[c][lang()] || kb[c].en)) || c);
    const since = d.onset_days_ago === 0
      ? L('आज से', 'आजपासून', 'since today')
      : L(`${d.onset_days_ago} दिन से`, `${d.onset_days_ago} दिवसांपासून`,
          `for ${d.onset_days_ago} days`);
    const summary = L(
      `समझ गया — <b>${SPN[d.species] || ''}</b>, ${since}, ${d.affected_count} पशु बीमार`
        + (d.dead_count ? `, ${d.dead_count} मरे` : '')
        + (symNames.length ? `।<br>लक्षण: <b>${symNames.join(', ')}</b>` : '।'),
      `समजले — <b>${SPN[d.species] || ''}</b>, ${since}, ${d.affected_count} जनावरे आजारी`
        + (d.dead_count ? `, ${d.dead_count} मेली` : '')
        + (symNames.length ? `.<br>लक्षणे: <b>${symNames.join(', ')}</b>` : '.'),
      `Got it — <b>${SPN[d.species] || ''}</b>, ${since}, ${d.affected_count} ill`
        + (d.dead_count ? `, ${d.dead_count} dead` : '')
        + (symNames.length ? `.<br>Signs: <b>${symNames.join(', ')}</b>` : '.'));
    const confirm = L('क्या मैं यह तक्रार भेज दूँ?', 'ही तक्रार पाठवू का?',
      'Shall I send this report?');
    this.reply(summary + '<br><br>' + confirm, [
      {
        label: L('✅ हाँ, भेजें', '✅ होय, पाठवा', '✅ Yes, send'),
        run: () => window.PR && PR.submitFromVoice(d),
      },
      {
        label: L('✏️ पहले देखूँ', '✏️ आधी पाहतो', '✏️ Review first'),
        run: () => window.PR && PR.fillReport(d),
      },
    ], summary.replace(/<[^>]+>/g, '') + '. ' + confirm);
  };

  /* An interview in progress owns every answer, ahead of skills and the LLM. */
  const origHandle = A.handle.bind(A);
  A.handle = async function (q) {
    if (this.interview) { this.say(q, 'u'); return this.interviewAnswer(q); }
    return origHandle(q);
  };
})();

# पशुआरोग्य · PashuAarogya AI

**Livestock Disease Early-Warning, Surveillance & Response Platform**
SIH Problem Statement 26128 · Government of Maharashtra · MSInS

## ✨ The six innovations (what to demo, in this order)

| # | Feature | Where | The 15-second demo |
|---|---|---|---|
| 1 | **📸 Pashu Lens** — real EfficientNetV2 breed/type identification (50 Indian breeds, subject + quality gates), ported from PashuPehchaan | Farmer → जनावरे | Photograph a cow → breed in Marathi with confidence → one-tap register |
| 2 | **📡 Outbreak Radar** — space-time scan statistics, One Health flag, auto-tasks | Portal → Overview | Point at the p-value; open the anthrax cluster's ☣ notice |
| 3 | **🔮 What-if Planner** — SEIR forecast, ring-vaccination scenario, doses needed | Portal → Forecast | Press ▶ Play; read "cases prevented" |
| 4 | **🪪 Health Passport + Movement Permit** — QR per animal, milk-withdrawal countdown, live permit | Farmer → 🪪 / `/passport.html?tag=…` | Scan → **BLOCKED: inside LSD zone** |
| 5 | **🗣️ Pashu Mitra** — voice in, voice out, IVR, SMS | Farmer → तक्रार | Speak Marathi → hear the triage read back |
| 6 | **💰 Reporting pays** — case record → compensation claim → officer approval | Farmer → सेवा · Portal → Claims | Approve → farmer sees ✅ instantly |

Plus **📄 SITREP** (Portal → Reports): the one-page morning Situation Report, auto-generated and printable.

### 🎙️ पशु मित्र — the voice assistant (Hindi by default)
The orange mic button on every screen opens a conversational assistant: speak or
type in Hindi (Marathi/English on the language toggle). It understands intents,
answers with voice, and acts:
- Farmer: *"मेरी गाय बीमार है, बुखार और गांठें हैं"* → starts the report with the
  species and symptoms pre-filled · *"टीकाकरण शिविर कब है?"* · *"मुआवजे का क्या हुआ?"* ·
  *"लम्पी रोग क्या है?"* · *"आज का मौसम"* · *"मदद / 1962"*
- Officials: *"आज की स्थिति?"* (reads the live summary) · *"पूर्वानुमान दिखाओ"* ·
  *"दावे खोलो"* · *"SITREP"* · *"रडार फिर से चलाओ"* · *"अगला दिन सिमुलेट करो"*
**Two-layer brain.** Precise rule-based skills answer first (instant, offline,
they act directly). Anything free-form goes to **Google Gemini** with live context
from the platform — the farmer's animals, claims, camps, weather, alerts; the
official's clusters, tasks and forecast — so answers are grounded, not generic.
Gemini returns a reply plus an optional action (pre-fill a report with the
species and symptoms it recognised, or open a section), which the app executes.
Guard-rails in the system prompt: no definitive diagnosis, no drug doses, always
route serious cases to the vet / 1962, never invent numbers or camps.

Setup: put `GEMINI_API_KEY=...` in a `.env` at the repo root (see
`.env.example`; the file is git-ignored). Without a key the assistant still
works on its rule-based skills. The key stays on the server — the browser only
ever calls `/api/assistant/chat`.
Language default is **Hindi everywhere** (`pr_lang`), with मराठी / English one tap away.

### 🗣️ The voice interview (new)
Tapping **🎙️ बोलकर शिकायत दर्ज करें** on the report screen hands the whole
consultation to पशु मित्र. It asks one short question at a time, the way a vet
would on the phone — *"क्या दूध कम हो गया है?"*, *"क्या पशु चारा खा रहा है?"*,
*"शरीर पर गांठें?"* — and each answer maps to a symptom code the triage engine
already understands. It listens again automatically after every question, so a
farmer who cannot read never touches the screen. At the end it reads the case
back and offers **✅ भेजें** or **✏️ पहले देखूँ**.

### 🕒 "How long has the animal been ill?"
The report now asks for the onset (one tap: आज / कल / २-३ दिन / एक हफ्ता, or an
exact date), and the voice interview asks the same question. Before this the API
stamped `onset_date = today`, so the reporting delay was always zero and the PS's
first expected outcome could not be shown. The district dashboard now carries a
**median reporting delay** KPI (onset → report, 30-day window).

### ⚠️ Zone-wide outbreak awareness
When the radar detects a cluster, every village in the zone gets the advisory in
Marathi/Hindi/English — not just the village that reported — and each farmer in
the zone sees a red awareness banner at the top of their home screen, with a
🔊 listen button. Neighbouring villages are the ones who can still prevent it.

### 📍 Nearby veterinary centres
Farmer → सेवा lists the real institution ladder nearest first: block dispensary →
district polyclinic → district lab, plus the 1962 mobile unit, with distance,
opening hours, one-tap **call 1962** and directions. No phone numbers are
invented — everything routes through the genuine 1962 helpline.

### 🟢 Live farmer enrolment (for the demo)
The login page has **🆕 Register here**: name, mobile, village — the farmer is
created and signed in in one step. The district dashboard shows a live wall
counting registrations against a target of 20 (`PASHU_LIVE_TARGET`), with each
new name, village and herd size appearing within one sync poll. It is the
on-stage proof that records really reach the database.

### 🗺️ Two regions: Maharashtra + Indore (M.P.)
The problem statement is Maharashtra's, so Maharashtra stays the primary dataset
and keeps every outbreak storyline. **Indore district** (Depalpur, Sanwer, Mhow,
Hatod, Rau) is seeded alongside it with Malwa breeds — Malvi, Nimari, Bhadawari,
Kadaknath — so the team can demo, and enrol real farmers, in the geography they
are standing in. Demo logins `9000000011` (farmer, Betma) and `9000000012`
(D.V.O. Indore). Set `PASHU_REGION=mh` to seed Maharashtra only.
> Tehsil names and coordinates are real; the village names are illustrative and
> must be replaced with LGD-verified names before any real deployment.

### Pashu Lens AI sidecar
`run.bat` starts it automatically if the PashuPehchaan model is present at
`C:\Users\admin\Desktop\BreedVision18\Breed-Vision-main\breed-ai-service`
(override with the `PASHU_AI_DIR` environment variable). It runs on port 8001;
the platform proxies it at `/api/ai/identify` and **degrades honestly** when
the sidecar is off ("AI service not running — register manually").
Manual start: `cd <that folder> && .venv\Scripts\python -m uvicorn app:app --port 8001`.

## ☁️ Deploying it live (Render + Postgres)

ngrok is for your laptop. For a permanently-live URL see **[DEPLOY.md](DEPLOY.md)** —
one Render web service (the backend already serves the frontend), a free Postgres so
records survive restarts, and the honest constraint on where the 235 MB breed model
can run. `render.yaml` at the repository root is a one-click Blueprint.

## 📱 Run it on a phone — from anywhere, no shared Wi-Fi

1. `run.bat` starts the platform **and a public HTTPS tunnel** (`tunnel.py`):
   ngrok with the reserved domain **https://onset-jasmine-eagle.ngrok-free.dev**
   (permanent), or a Cloudflare quick tunnel as fallback. Manual: `npm run tunnel`.
2. The login page QR switches to that public link automatically — scan it on
   **any** network, mobile data included. First visit shows ngrok's one-time
   "Visit Site" page; tap it.
3. In Chrome on the phone: menu → **"Add to Home screen"** → Install.
   It launches full-screen with the पशुआरोग्य icon, works offline, and
   queues reports for sync. HTTPS is also what unlocks the **microphone**
   (voice assistant), **camera** and PWA install on Android — a plain
   `http://192.168.x.x` LAN address never gets those.

Free-plan limits: one ngrok agent at a time (`tunnel.py` kills leftovers) and
the link only works while your laptop runs. For an always-on address, deploy the
backend to any host and point the domain at it — no code changes.

**Packaged APK path (post-hackathon):** the frontend is framework-free, so
wrapping is mechanical — Capacitor (`npx cap init && npx cap add android`
with `webDir: frontend`) or a Trusted Web Activity via
`bubblewrap init --manifest https://<host>/manifest.webmanifest` once hosted
on HTTPS. No code changes required either way.

## 🦠 Disease coverage (aligned to the Bharat Pashudhan "1962 Farmers App" / LHDCP scope)

| Category | Diseases in the knowledge base |
|---|---|
| Cattle & Buffalo | LSD, FMD, HS (घटसर्प), BQ (फऱ्या), Theileriosis, Babesiosis, Mastitis |
| Goat & Sheep | PPR, Sheep & Goat Pox, Enterotoxaemia |
| Poultry | Ranikhet (Newcastle), Avian Influenza |
| Pig | Classical Swine Fever |
| Zoonotic (One Health) | Anthrax, Brucellosis, Rabies, Avian Influenza |
| General | Mange |

All 17 live in `backend/rules/diseases.yaml` (hot-reloaded) with Marathi/Hindi
names, sign-weighted triage rules, seasonality and farmer action advisories.

One platform connecting **Farmer → Field Worker → Veterinarian → Laboratory →
Block / District / State authority**, turning field observations into risk
intelligence, alerts and coordinated response.

---

## Quick start

```
Double-click run.bat            (installs deps, starts server, opens browser)
```

or manually:

```
pip install -r requirements.txt
cd backend
python main.py
# open http://127.0.0.1:8000
```

**Every demo login uses OTP `123456`.**

| Role | Phone | Experience |
|---|---|---|
| Farmer (Ramesh Pawar) | 9000000001 | Marathi-first mobile app, voice reporting, offline queue |
| Field worker | 9000000002 | Same app, field channel |
| Veterinarian (Dr. Kulkarni) | 9000000003 | Triage-ranked case queue, samples, treatment |
| Lab technician | 9000000004 | Sample chain-of-custody, results |
| Block Veterinary Officer | 9000000005 | Command center scoped to block |
| District Veterinary Officer | 9000000006 | Full command center |
| State admin | 9000000007 | Full command center + all alerts |

## The 2-minute demo script (the full loop, including money)

1. **Farmer** (9000000001): press 📢, pick 🐄, tap 🎤 and *speak Marathi*
   ("तापाने आजारी आहे, अंगावर गाठी आल्या आहेत") — symptoms auto-tick. Submit.
   Triage banner responds in Marathi; vet is alerted. **Try it in airplane
   mode** — the report queues and syncs on reconnect. Note the home screen:
   live village weather + the upcoming vaccination camp banner.
2. **Vet** (9000000003): the case is at the top of the triage-ranked queue.
   Open → Collect sample → chain-of-custody code appears.
3. **Lab** (9000000004): walk the sample COLLECTED → … → TESTING → mark
   **Positive (LSD)** — the case auto-confirms; block & district are alerted.
4. **District** (9000000006), five tabs:
   - **Overview** — Outbreak Radar (observed vs expected, scan p-value),
     explainable risk (click any circle), One Health flag on the anthrax
     cluster. Press **▶ Simulate next day** to watch the radar respond live.
   - **Action Queue** — tasks auto-created from each detected cluster;
     mark the MVU dispatch done.
   - **Claims** — approve the farmer's compensation claim…
5. **Back to the farmer**: Services tab now shows the claim **APPROVED ✅**.
   *That closes the incentive loop: reporting pays.* Then in **Campaigns**,
   schedule a camp — the farmer's app shows it instantly, in Marathi.
6. **Judge demands we can satisfy live:**
   - *"Add a new disease"* → paste ~20 lines into
     `backend/rules/diseases.yaml`, press **Reload KB**. Done.
   - *"Aggregate at block level instead"* → it's a dropdown.
   - *"Does it work offline?"* → airplane mode, file a report.

## Architecture

```
frontend/  static PWA (no build step) — farmer / vet / gov / IVR + service worker
backend/   FastAPI + SQLAlchemy (SQLite default; set PASHU_DB_URL for Postgres)
  engine.py   triage rules · space-time scan (Kulldorff-style, Poisson p-values)
              · explainable 0-100 risk score (weights per PRD §8.1)
  rules/diseases.yaml   hot-reloadable disease knowledge base (FR-07)
  seed.py     Maharashtra geography + LSD-wave simulator (calibrated shape)
  weather.py  Open-Meteo live signal (keyless, graceful offline fallback)
```

**Safety rule (enforced in architecture):** triage outputs *suspected
categories + severity band + route* — never a diagnosis. Diagnosis and
treatment stay with the registered veterinarian (FR-06, PRD §14).

## PRD traceability

Every FR-01 … FR-20 requirement is implemented; see PRD §19 mapping — the
routes in `backend/main.py` are grouped in the same order.

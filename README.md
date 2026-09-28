# पशुआरोग्य · PashuAarogya AI

**Livestock disease early-warning, surveillance & coordinated-response platform**
Smart India Hackathon 2026 · Problem Statement **26128** · Government of Maharashtra
(Maharashtra State Innovation Society · Dept. of Skills, Employment, Entrepreneurship & Innovation)
Category: Software · Theme: MedTech / BioTech / HealthTech

> *The disease travels fast. Now the signal travels faster.*
> One platform connecting **farmer → field worker → veterinarian → laboratory → block / district / state**,
> turning village symptom reports into statistical outbreak detection, explainable risk, vaccination
> campaigns and compensation. Voice-first. Hindi/Marathi-first. Works offline.

---

## Repository layout

| Path | What it is |
|---|---|
| [`pashuraksha/`](pashuraksha/) | The application — FastAPI backend + framework-free PWA frontend. **Start here.** Full technical README inside. |
| [`SIH_PS_Teardown_Livestock_Disease.pdf`](SIH_PS_Teardown_Livestock_Disease.pdf) | 27-page strategic analysis of the problem statement: pain points, competitors (Bharat Pashudhan, NADRES, 1962 MVU…), feasibility, judge Q&A stress-test, verdict. |
| [`SIH_PS_Teardown_Livestock_Disease.html`](SIH_PS_Teardown_Livestock_Disease.html) | Source of the above (print to PDF with Chrome). |

---

## Quick start (Windows)

```bat
cd pashuraksha
run.bat            :: installs deps on first run, starts the platform + the AI sidecar
```
or `npm run dev` / `python backend\main.py`. Open **http://127.0.0.1:8000**.
The login page shows a QR to open the app on a phone on the same Wi-Fi and install it
as an Android app (PWA → *Add to Home screen*, works offline).

**Demo logins** (OTP for all: `123456`)

| Role | Phone |
|---|---|
| Farmer · पशुपालक | 9000000001 |
| Field worker · पशुमित्र | 9000000002 |
| Veterinarian | 9000000003 |
| Laboratory | 9000000004 |
| Block officer | 9000000005 |
| District / State command | 9000000006 · 9000000007 |

---

## What makes it different — six innovations

| # | Innovation | In one line |
|---|---|---|
| 📸 | **Pashu Lens** | Real EfficientNetV2 model (50 Indian cattle/buffalo breeds, subject + quality gates) identifies the animal from a photo → one-tap registration |
| 📡 | **Outbreak Radar** | Space-time scan statistics with Poisson p-values flag village clusters days before deaths pile up; zoonoses raise a One Health notice; every cluster auto-creates owned response tasks |
| 🔮 | **What-if Planner** | Transparent SEIR forecast on the village graph: *"ring-vaccinate today → how many cases prevented, how many doses?"* — animated map + recommendation |
| 🪪 | **Health Passport + Movement Permit** | Scannable QR per animal: vaccinations, treatments, milk-withdrawal countdown and a **live permit** computed from the Radar — a blocked village cannot sell into a clean one |
| 🗣️ | **Pashu Mitra** | Voice assistant on every screen: speak or type in Hindi/Marathi/English, it answers aloud and acts (start a report with symptoms pre-filled, read your claim status, camps, weather, disease guide). Rule-based → works offline |
| 💰 | **Reporting pays** | A death report becomes a one-tap compensation claim that officers approve in the portal — the incentive that turns hidden outbreaks into early reports |

Plus **📄 SITREP** — a one-page, printable morning Situation Report for the Collector's office, auto-generated with the forecast recommendation.

---

## How it maps to the problem statement

| PS requirement | Where it lives |
|---|---|
| Capture symptom & mortality reports (farmers + field workers) | Farmer app (voice/photo, offline queue) · Field worker mode · IVR 1962 simulator · SMS codec |
| Rule-based / AI-assisted triage to flag outbreaks | `backend/rules/diseases.yaml` (17 diseases, hot-reloaded) · `engine.py` scan statistic |
| Geospatial risk mapping, weather, historical trends | Portal Overview: explainable 0–100 risk with six weighted signals; live Open-Meteo weather |
| Animal / herd health, vaccination, treatment records | Bharat-Pashudhan-style 12-digit Tag ID · Health Passport |
| Multilingual advisories & alerts | Hindi · Marathi · English, spoken aloud |
| Sample collection, lab referral, escalation | Vet workspace: QR chain-of-custody, lab results auto-confirm cases, escalation state machine |
| Dashboards for veterinary officials | Portal: Overview · Forecast · Action Queue · Claims · Campaigns · Reports |
| Mobile / web / IVR / offline channels | Installable PWA, service worker, offline report queue, IVR & SMS paths |

---

## Architecture

```
backend/   FastAPI · SQLAlchemy (SQLite by default, PASHU_DB_URL → PostgreSQL/PostGIS)
           engine.py  triage · space-time scan · explainable risk · alerts & tasks
           forecast.py SEIR-lite what-if planner
           weather.py  Open-Meteo (keyless) signal
           rules/diseases.yaml  knowledge base (LHDCP / 1962 Farmers App scope)
frontend/  no build step · PWA · Leaflet · Chart.js · Web Speech API
           farmer.html / vet.html / gov.html / passport.html / sitrep.html / ivr.html
           js/assistant.js  पशु मित्र voice assistant (shared)
AI sidecar Pashu Lens = PashuPehchaan breed-recognition service (EfficientNetV2), port 8001,
           proxied at /api/ai/identify with honest degradation when absent
```

---

## Honest notes

- Surveillance data is a **calibrated simulation** (three concurrent disease storylines) because India has no public real-time outbreak feed — that gap *is* the problem statement.
- AI output is **decision support**; diagnosis and treatment remain with registered veterinarians (Indian Veterinary Council Act). Triage never names a disease as fact.
- Forecast parameters are literature-plausible defaults, visible in `forecast.py`, not calibrated to Maharashtra field data.
- Bharat Pashudhan has no public API; the platform keys on the same Tag ID format so integration is an adapter, not a rewrite.

---

Built for SIH 2026 · Team PashuAarogya · Government of Maharashtra

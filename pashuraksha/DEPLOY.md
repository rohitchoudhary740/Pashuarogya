# Deploying PashuAarogya

> **The plan in one line:** ngrok stays the primary demo link (it has the AI model
> and your laptop's speed). Render is the **backup** — the same app, minus Pashu
> Lens, on a URL that is live even if your laptop isn't. Set it up once now; it
> costs nothing and it's there if the venue Wi-Fi or your machine lets you down.
>
> Jump to [the backup recipe](#the-backup-recipe-render-without-the-ai-model).

## Read this first: don't split the frontend onto Vercel

It's a natural instinct, but in this project it costs you work and buys nothing.

The frontend here is **plain static HTML/CSS/JS that the FastAPI backend already
serves** (`app.mount("/", StaticFiles(...))`). Frontend and backend are one app on
one origin. Splitting them means:

| Splitting costs you | Why |
|---|---|
| A CORS preflight on every API call | Extra round-trip added to every single request, on mobile networks |
| Two deploys to keep in sync | A frontend change and a backend change now ship separately |
| An API-base config to manage | Wrong value = white screen with console errors |
| Service-worker scope headaches | Offline caching is scoped to an origin; the API is now on another |

And it fixes nothing, because **every page calls the API immediately on load** — a
CDN-fast frontend still waits on the backend. Vercel helps when you have a heavy
React bundle or server-rendered pages. This app's entire frontend is 960 KB.

> **Recommendation: deploy the whole app as one Render web service, with Postgres.**
> One URL, no CORS, one deploy. Steps below. The Vercel split is documented after,
> in case you want it anyway.

The three things that *actually* matter for going live are the database, the cold
start, and the AI model. All three are handled below.

---

## Option A (recommended) — one service on Render + Postgres

### 1. Push to GitHub
Already done — the repo is `kartikey1819/SIH_2026`, branch `feature/pashuaarogya-v2`.
Merge it to `main` first if you want Render's default branch to work out of the box.

### 2. Create the service
Render dashboard → **New → Blueprint** → pick this repo. It reads
[`render.yaml`](../render.yaml) and creates both the web service and a free
Postgres database, already wired together.

> `render.yaml` lives at the **repository root**, not in `pashuraksha/` — Render
> only looks at the root. `rootDir: pashuraksha` inside it points the build at
> the app.

Prefer clicking through manually? **New → Web Service**, then:

| Field | Value |
|---|---|
| Root directory | `pashuraksha` |
| Runtime | Python 3 |
| Build command | `pip install -r requirements.txt` |
| Start command | `cd backend && python main.py` |
| Health check path | `/healthz` |
| Region | Singapore (closest to India) |

### 3. Add the database — this is the step people skip
**Render's free disk is ephemeral.** If you leave it on SQLite, every record your
judges create is wiped on the next deploy *and* every time the service sleeps.

Create a free Postgres (Render's own, or [Neon](https://neon.tech) — Neon's free
tier doesn't expire, Render's free database is removed after 30 days), then set:

```
PASHU_DB_URL = postgresql://user:pass@host/dbname
```

No code changes needed — `database.py` already reads it, and also accepts
`DATABASE_URL`, which is what Render and Neon inject automatically. The old
`postgres://` scheme is rewritten for you.

### 4. Environment variables

| Key | Value |
|---|---|
| `PASHU_DB_URL` | your Postgres connection string (or let the blueprint wire it) |
| `PASHU_SECRET` | any long random string — signs session tokens |
| `GEMINI_API_KEY` | your key from `.env`, for पशु मित्र |
| `PASHU_AI_URL` | only if you deploy the breed model (step 6) |

### 5. Updating a deployment that already has data

`seed_all` refuses to touch a database that already holds records, which is
right — it must never re-seed over real reports. But that means a cloud
database seeded before a feature existed never gains it, and you cannot simply
wipe one that farmers have filed into.

So every boot also runs `seed_topup()`: it adds only what is **missing** and
leaves everything else alone. Verified against a pre-Indore backup — 87 → 113
locations, 39 health centres created, Indore and its 20 villages added, and all
1,027 existing cases untouched. Running it twice adds nothing the second time.

Watch for it in the deploy log:

```
[boot] topped up: health centres, Indore region (20 villages)
```

### 6. First boot
The demo world (87 locations, 784 animals, ~1,000 historical cases) seeds itself
on first start against the empty database. Seeding runs **in a background thread**
so the port opens immediately and Render's health check passes — watch progress at:

```
https://your-app.onrender.com/healthz
→ {"ok":true,"ready":false,"stage":"seeding", ...}
→ {"ok":true,"ready":true,"stage":"ready","locations":87, ...}
```

Give it 1–3 minutes on Postgres. Until `ready` is true, dashboards will look empty.

### 7. Pashu Lens (the breed model) — the honest constraint
<a id="the-backup-recipe-render-without-the-ai-model"></a>
**It will not run on Render's free tier.** TensorFlow plus the 235 MB
EfficientNetV2 model needs well over the 512 MB RAM free instances get; it will
OOM on load.

**For a backup instance, just turn it off** — `render.yaml` already sets:

```
PASHU_AI_DISABLED = 1
```

This is a first-class state, not a broken one. Verified behaviour with it set:

| | Without the model |
|---|---|
| Pashu Lens card | Camera/gallery buttons dim, **✍️ Register manually** appears in their place |
| Manual registration | Species → breed (Maharashtra breeds, or type your own) → sex → age → saved with a real Tag ID |
| `/api/ai/status` | Answers in **2 ms**, cached — no connect-timeout stall on page load |
| Message shown | *"Breed identification is not enabled on this deployment. You can still register the animal by hand."* |
| Everything else | Outbreak Radar, History, Forecast, passports, claims, camps, पशु मित्र — all unaffected |

So the backup demonstrates 5 of the 6 innovations; only Pashu Lens is absent, and
it says so in plain words rather than erroring.

**Want the model live too?** [HuggingFace Spaces](https://huggingface.co/spaces)
(Docker SDK, 16 GB RAM free CPU tier) fits it comfortably: push
`breed-ai-service/` there, then on Render set `PASHU_AI_DISABLED=0` and
`PASHU_AI_URL=https://<your-space>.hf.space`. A Render Standard instance (2 GB)
also works, for money.

### The backup recipe — Render without the AI model

The short version, assuming the repo is on GitHub:

1. Render → **New → Blueprint** → this repo. `render.yaml` creates the web
   service *and* a free Postgres, already wired, with `PASHU_AI_DISABLED=1`.
2. Paste `GEMINI_API_KEY` into the service's Environment tab (optional — without
   it पशु मित्र falls back to its rule-based skills).
3. Wait for `/healthz` to report `"ready": true` — 1–3 minutes while it seeds.
4. Point UptimeRobot at `/healthz` every 10 minutes so it never sleeps.
5. Keep the URL in your pocket. Demo from ngrok; switch if anything goes wrong.

Keep in mind the two instances have **separate databases** — a report filed on
ngrok will not appear on Render. That is fine for a backup; just don't present
from both at once.

### Troubleshooting: the service times out on *every* URL

Symptom: `/healthz`, `/api/...` and even `/` all hang until the client gives up,
and Render shows "SERVICE WAKING UP" forever or restarts in a loop.

That is not a cold start and not a crash — **the port never opened.** A web
server only starts accepting connections after its startup handler returns, so
any startup work that blocks keeps the whole service invisible. Here the culprit
was the database: `create_all()` ran inline, and an unreachable Postgres made it
wait on TCP for minutes. Render's health check timed out, Render restarted it,
and the loop repeated.

Fixed in the app, so it cannot happen again:

| | Before | Now |
|---|---|---|
| Table creation + seeding | inline in the startup handler | in a background thread |
| Postgres connect timeout | OS default (minutes) | **10 s** (`database.py`) |
| `/healthz` | took a DB session — hung when the DB hung | **no DB dependency**, always answers |
| A bad database looks like | the service never starting | `{"stage":"error","error":"OperationalError: ..."}` |

So if the database is wrong now, `/healthz` tells you in about ten seconds:

```json
{"ok":true,"ready":true,"stage":"error","db_host":"...singapore-postgres.render.com:5432",
 "error":"OperationalError: connection to server at ... failed: timeout expired"}
```

Read `stage` first — `connecting` → `seeding` → `computing risk` → `ready`, or
`error` with the reason. `db_host` confirms which database it actually reached,
which catches the most common mistake of all: `PASHU_DB_URL` never being set, or
pointing at a Postgres instance Render has since expired (the free database is
removed after 30 days — create a new one, or use Neon, and update the variable).

### 8. Keep it awake — now built in

Free Render services sleep after ~15 minutes idle and take ~50 s to wake, which
is fatal mid-presentation. Two guards ship with the repo, and they fail in
different ways on purpose:

| | What it does | When it saves you |
|---|---|---|
| `backend/keepalive.py` | The instance pings its own public URL every ~10 min (jittered). Render sees ordinary inbound traffic, so the idle clock never runs out. | While the service is **up** — it never goes to sleep in the first place |
| `.github/workflows/keepalive.yml` | GitHub Actions cron pings from outside every 10 min, retrying through a cold start | After a **deploy, crash or OOM** — once the instance is down, its own thread is down with it and only an outside request can wake it |

The self-ping needs no configuration on Render: it reads `RENDER_EXTERNAL_URL`,
which Render injects. Anywhere else, set `PASHU_PUBLIC_URL`. With neither set —
local development — the thread exits immediately and pings nothing.

Check it is working:

```
https://your-app.onrender.com/healthz
→ "keepalive": {"enabled": true, "last_ok": "…", "pings": 7, "failures": 0}
```

The GitHub workflow uses the repository variable `PASHU_URL` if you set one
(Settings → Secrets and variables → Actions → Variables), else
`https://pashuaarogya.onrender.com`. It also has a **Run workflow** button for
an instant wake-up before you present.

Two honest limits: GitHub disables scheduled workflows in a repo with no commits
for 60 days, and keeping one free service always awake uses roughly 730 of
Render's 750 free instance-hours a month — fine for one service, not two.
**Still open the URL yourself 5 minutes before you present.**

---

## Option B — frontend on Vercel, backend on Render

Only worth it if you specifically want a `*.vercel.app` domain or Vercel's CDN.

1. Deploy the backend on Render exactly as in Option A.
2. Tell the frontend where the API lives. Add this line to the `<head>` of every
   page in `frontend/`, **before** the `api.js` script tag:

   ```html
   <meta name="pashu-api" content="https://your-app.onrender.com">
   ```

   `api.js` already reads it (also accepts `window.PASHU_API`). With nothing set
   it stays same-origin, so local development is unaffected.
3. Deploy `pashuraksha/frontend` to Vercel as a static site — no build step, no
   framework preset.
4. CORS already allows all origins, and auth is a Bearer token rather than a
   cookie, so no credentialed-CORS configuration is needed.

Caveats specific to this split: the service worker caches the app shell on the
Vercel origin while API calls go to Render, so an offline farmer sees the UI but
no data — acceptable, since the offline report queue still works. And you must
remember to redeploy both sides together.

---

## Local development is unchanged

```bat
run.bat
```
still starts SQLite + the AI sidecar + the ngrok tunnel on `127.0.0.1:8000`.
None of the deployment changes affect it.

---

## Quick reference

| Env var | Purpose | Default |
|---|---|---|
| `PORT` | port to bind (platforms inject this) | `8000` |
| `PASHU_DB_URL` / `DATABASE_URL` | Postgres DSN | local SQLite file |
| `PASHU_SECRET` | session-token signing key | dev default — **set it in production** |
| `GEMINI_API_KEY` | Pashu Mitra assistant | assistant falls back to rule-based skills |
| `PASHU_AI_URL` | Pashu Lens sidecar | `http://127.0.0.1:8001` |
| `PASHU_TUNNEL_DOMAIN` | ngrok reserved domain (local only) | from `tunnel.json` |

| Endpoint | Use |
|---|---|
| `/healthz` | platform health check, keep-alive, seeding progress |
| `/api/db/health` | row counts and recent writes — proof the database is persisting |

"""PashuRaksha intelligence layer.

Three explainable components (PRD section 14):
  1. triage()          — rule-based symptom triage from the hot-reloaded YAML KB
  2. run_detection()   — Outbreak Radar: temporal anomaly + spatial cluster scan
                         using a Poisson space-time scan (Kulldorff-style,
                         simplified) that outputs a p-value, not a black box
  3. compute_risk()    — 0-100 explainable village risk score with reasons,
                         weights per PRD 8.1

Safety rule: triage NEVER outputs a definitive diagnosis — it outputs suspected
categories, a severity band and a route. Diagnosis is the vet's job.
"""
import os, json, math, random
from datetime import datetime, date, timedelta

import yaml
from sqlalchemy import func

from models import (Case, Animal, Location, Vaccination, RiskScore, Outbreak,
                    Alert, WeatherObservation, Task)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KB_PATH = os.path.join(BASE_DIR, "rules", "diseases.yaml")

_kb_cache = {"mtime": None, "data": None}


# --------------------------------------------------------------------- KB ---
def load_kb(force: bool = False):
    """Load the disease knowledge base, hot-reloading when the file changes."""
    mtime = os.path.getmtime(KB_PATH)
    if force or _kb_cache["data"] is None or _kb_cache["mtime"] != mtime:
        with open(KB_PATH, encoding="utf-8") as f:
            _kb_cache["data"] = yaml.safe_load(f)
        _kb_cache["mtime"] = mtime
    return _kb_cache["data"]


# ----------------------------------------------------------------- triage ---
def triage(species: str, symptoms: list, dead_count: int = 0,
           affected_count: int = 1, month: int | None = None):
    """Rule-based triage. Returns band, score, suspected disease keys, zoonotic
    flag and human-readable reasons. Never a diagnosis."""
    kb = load_kb()
    month = month or date.today().month
    matches = []
    for key, d in kb["diseases"].items():
        if species not in d.get("species", []):
            continue
        score = sum(w for s, w in d.get("signs", {}).items() if s in symptoms)
        if score >= d.get("min_score", 6):
            in_season = (not d.get("season_months")) or (month in d["season_months"])
            matches.append({
                "key": key, "score": score,
                "severity": d.get("severity", "medium"),
                "zoonotic": bool(d.get("zoonotic")),
                "notifiable": bool(d.get("notifiable")),
                "in_season": in_season,
            })
    matches.sort(key=lambda m: (m["score"], m["severity"] == "critical"), reverse=True)

    sev_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    top_sev = max((sev_rank[m["severity"]] for m in matches), default=0)
    zoonotic = any(m["zoonotic"] for m in matches)

    band = "low"
    if dead_count > 0 or "sudden_death" in symptoms or top_sev >= 3:
        band = "high"
    elif top_sev >= 2 or affected_count >= 3:
        band = "high" if any(m["notifiable"] for m in matches) else "medium"
    elif matches:
        band = "medium"

    reasons = []
    if dead_count:
        reasons.append(f"{dead_count} death(s) reported")
    for m in matches[:2]:
        kb_d = kb["diseases"][m["key"]]
        r = f"signs consistent with {kb_d['name']['en']} (match score {m['score']})"
        if m["in_season"]:
            r += ", currently in season"
        reasons.append(r)
    if zoonotic:
        reasons.append("possible ZOONOTIC condition — human-health notice required")
    if affected_count >= 3:
        reasons.append(f"{affected_count} animals affected — herd-level event")
    if not matches:
        reasons.append("no notifiable pattern matched — routine veterinary review")

    return {
        "band": band,
        "score": matches[0]["score"] if matches else 0,
        "suspected": ",".join(m["key"] for m in matches[:2]),
        "zoonotic": zoonotic,
        "reasons": reasons,
    }


# ------------------------------------------------------------ math helpers --
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def poisson_tail(k: int, lam: float) -> float:
    """P(X >= k) for X ~ Poisson(lam). Exact iterative sum, no scipy."""
    if k <= 0:
        return 1.0
    lam = max(lam, 1e-9)
    term = math.exp(-lam)          # P(X=0)
    cdf = term
    for i in range(1, k):
        term *= lam / i
        cdf += term
        if term < 1e-15 and i > lam:
            break
    return max(0.0, min(1.0, 1.0 - cdf))


# ------------------------------------------------------- detection (radar) --
SCAN_RADIUS_KM = 12.0
WINDOW_DAYS = 7
BASELINE_WEEKS = 3
MIN_CLUSTER_CASES = 4
P_THRESHOLD = 0.05


def _village_case_counts(db, since: datetime, until: datetime):
    rows = (db.query(Case.village_id, func.count(Case.id))
              .filter(Case.reported_at >= since, Case.reported_at < until)
              .group_by(Case.village_id).all())
    return {vid: n for vid, n in rows}


def run_detection(db, now: datetime | None = None):
    """Space-time scan over villages. For each village: zone = villages within
    SCAN_RADIUS_KM; observed = zone cases in last 7 days; expected = zone weekly
    average over the previous 3 weeks. Poisson tail p-value. Overlapping zones
    are merged keeping the most significant center."""
    now = now or datetime.utcnow()
    villages = db.query(Location).filter(Location.level == "village").all()
    recent = _village_case_counts(db, now - timedelta(days=WINDOW_DAYS), now)
    base = _village_case_counts(
        db, now - timedelta(days=WINDOW_DAYS * (1 + BASELINE_WEEKS)),
        now - timedelta(days=WINDOW_DAYS))

    candidates = []
    for v in villages:
        if recent.get(v.id, 0) == 0:
            continue
        zone = [w for w in villages
                if haversine_km(v.lat, v.lon, w.lat, w.lon) <= SCAN_RADIUS_KM]
        zone_ids = [w.id for w in zone]
        k = sum(recent.get(i, 0) for i in zone_ids)
        lam = max(0.5, sum(base.get(i, 0) for i in zone_ids) / BASELINE_WEEKS)
        p = poisson_tail(k, lam)
        if k >= MIN_CLUSTER_CASES and p < P_THRESHOLD:
            candidates.append({"center": v, "zone_ids": zone_ids, "k": k,
                               "lam": lam, "p": p})

    # merge overlapping candidates: greedy by significance
    candidates.sort(key=lambda c: c["p"])
    chosen, used = [], set()
    for c in candidates:
        if used & set(c["zone_ids"]):
            continue
        chosen.append(c)
        used |= set(c["zone_ids"])

    # suspected disease of a cluster = modal suspected among its recent cases
    db.query(Outbreak).filter(Outbreak.status == "ACTIVE").update(
        {"status": "MONITORING"})
    kb = load_kb()
    created = []
    for c in chosen:
        cases = (db.query(Case)
                   .filter(Case.village_id.in_(c["zone_ids"]),
                           Case.reported_at >= now - timedelta(days=WINDOW_DAYS))
                   .all())
        tally = {}
        for cs in cases:
            for key in (cs.suspected or "").split(","):
                if key:
                    tally[key] = tally.get(key, 0) + 1
        suspected = max(tally, key=tally.get) if tally else ""
        zoo = bool(suspected) and bool(kb["diseases"].get(suspected, {}).get("zoonotic"))

        existing = (db.query(Outbreak)
                      .filter(Outbreak.center_village_id == c["center"].id,
                              Outbreak.status.in_(["ACTIVE", "MONITORING"]))
                      .first())
        if existing:
            existing.status = "ACTIVE"
            existing.cases_7d, existing.expected = c["k"], round(c["lam"], 2)
            existing.p_value = round(c["p"], 5)
            existing.suspected, existing.zoonotic = suspected, zoo
            existing.zone_village_ids = json.dumps(c["zone_ids"])
            ob = existing
        else:
            ob = Outbreak(center_village_id=c["center"].id, suspected=suspected,
                          zone_village_ids=json.dumps(c["zone_ids"]),
                          cases_7d=c["k"], expected=round(c["lam"], 2),
                          p_value=round(c["p"], 5), radius_km=SCAN_RADIUS_KM,
                          zoonotic=zoo, status="ACTIVE")
            db.add(ob)
            db.flush()
            _emit_outbreak_alerts(db, ob, c["center"], suspected, zoo, kb)
        created.append(ob)
    db.commit()
    return created


def _emit_outbreak_alerts(db, ob, center, suspected, zoonotic, kb):
    dname = kb["diseases"].get(suspected, {}).get("name", {}).get("en", "unknown disease")
    body = (f"Space-time scan: {ob.cases_7d} cases vs {ob.expected} expected in "
            f"{SCAN_RADIUS_KM:.0f} km around {center.name} (p={ob.p_value}). "
            f"Suspected: {dname}. Recommended: dispatch field team, verify one "
            f"case, collect samples, check vaccination coverage in zone.")
    for role in ("block", "district", "vet"):
        db.add(Alert(kind="outbreak", severity="high",
                     title=f"Suspected {dname} cluster near {center.name}",
                     body=body, village_id=center.id, target_role=role))
    if zoonotic:
        db.add(Alert(kind="onehealth", severity="high",
                     title=f"ONE HEALTH: zoonotic risk ({dname}) near {center.name}",
                     body=(f"Cluster suspected of zoonotic disease {dname}. "
                           f"Parallel notice to district health authority (IDSP) "
                           f"advised for human surveillance in the same zone."),
                     village_id=center.id, target_role="health"))
    # Farmer advisory -- to EVERY village in the zone, not just the epicentre.
    # Warning only the village that reported leaves the neighbours, who are the
    # ones still able to prevent it, with no warning at all.
    act = kb["diseases"].get(suspected, {}).get("action", {})
    try:
        zone_ids = json.loads(ob.zone_village_ids or "[]")
    except ValueError:
        zone_ids = []
    if center.id not in zone_ids:
        zone_ids.append(center.id)
    for vid in zone_ids:
        at_centre = (vid == center.id)
        for lang in ("mr", "hi", "en"):
            if not act.get(lang):
                continue
            near = {"mr": f"जवळच्या {center.name} भागात",
                    "hi": f"पास के {center.name} क्षेत्र में",
                    "en": f"near {center.name}"}[lang]
            pre = {"mr": f"⚠ {dname} चा प्रादुर्भाव {near} आढळला आहे. ",
                   "hi": f"⚠ {near} {dname} का प्रकोप मिला है। ",
                   "en": f"⚠ A {dname} outbreak has been detected {near}. "}[lang]
            db.add(Alert(kind="advisory", severity="high" if at_centre else "medium",
                         title=f"[{lang}] {dname}",
                         body=("" if at_centre else pre) + act[lang],
                         village_id=vid, target_role="farmer", lang=lang))
    # action queue: every detected outbreak spawns owned, actionable tasks
    db.add(Task(kind="mvu_dispatch", assigned_role="vet", outbreak_id=ob.id,
                village_id=center.id,
                title=f"Dispatch MVU: verify one suspected {dname} case at {center.name}"))
    db.add(Task(kind="sample_collection", assigned_role="vet", outbreak_id=ob.id,
                village_id=center.id,
                title=f"Collect samples from 2 symptomatic animals at {center.name}"))
    db.add(Task(kind="ring_vaccination", assigned_role="block", outbreak_id=ob.id,
                village_id=center.id,
                title=f"Ring-vaccination coverage check within {SCAN_RADIUS_KM:.0f} km of {center.name}"))


# ---------------------------------------------------------------- risk ------
# PRD 8.1 weights: burden 30, growth 20, history 15, vacc gap 15, cluster 10, weather 10
def compute_risk(db, now: datetime | None = None):
    now = now or datetime.utcnow()
    month = now.month
    kb = load_kb()
    villages = db.query(Location).filter(Location.level == "village").all()
    recent = _village_case_counts(db, now - timedelta(days=7), now)
    prev = _village_case_counts(db, now - timedelta(days=14), now - timedelta(days=7))

    # active cluster membership
    cluster_map = {}
    for ob in db.query(Outbreak).filter(Outbreak.status == "ACTIVE").all():
        for vid in json.loads(ob.zone_village_ids or "[]"):
            cluster_map[vid] = min(cluster_map.get(vid, 1.0), ob.p_value)

    # seasonal history: any KB disease in season this month
    seasonal = [d["name"]["en"] for d in kb["diseases"].values()
                if d.get("season_months") and month in d["season_months"]]

    out = []
    for v in villages:
        c7, cp = recent.get(v.id, 0), prev.get(v.id, 0)
        reasons, br = [], {}

        br["burden"] = min(30, c7 * 6)
        if c7:
            reasons.append(f"{c7} case report(s) in the last 7 days")

        br["growth"] = min(20, max(0, (c7 - cp) * 5)) if c7 else 0
        if br["growth"] >= 10:
            reasons.append(f"cases rising fast ({cp} → {c7} week-on-week)")

        br["history"] = 15 if (seasonal and c7) else (8 if seasonal else 0)
        if seasonal:
            reasons.append("high-risk season for: " + ", ".join(seasonal[:3]))

        cov = _vacc_coverage(db, v.id)
        br["vacc_gap"] = round(15 * (1 - cov))
        if cov < 0.6:
            reasons.append(f"vaccination coverage only {cov:.0%}")

        if v.id in cluster_map:
            p = cluster_map[v.id]
            br["cluster"] = 10 if p < 0.01 else 6
            reasons.append(f"inside an active detected cluster (p={p:.3g})")
        else:
            br["cluster"] = 0

        w = (db.query(WeatherObservation)
               .filter(WeatherObservation.village_id == v.id)
               .order_by(WeatherObservation.observed_at.desc()).first())
        br["weather"] = 0
        if w and w.humidity is not None and w.temp_c is not None:
            if w.humidity >= 70 and 22 <= w.temp_c <= 35:
                br["weather"] = 10
                reasons.append(f"weather favours disease vectors "
                               f"({w.temp_c:.0f}°C, {w.humidity:.0f}% humidity)")
            elif w.humidity >= 55:
                br["weather"] = 5

        score = min(100, sum(br.values()))
        band = "high" if score >= 60 else ("moderate" if score >= 35 else "low")
        if not reasons:
            reasons.append("no adverse signals in current data")

        rs = db.query(RiskScore).filter(RiskScore.village_id == v.id).first()
        if not rs:
            rs = RiskScore(village_id=v.id)
            db.add(rs)
        rs.computed_at, rs.score, rs.band = now, score, band
        rs.reasons, rs.breakdown = json.dumps(reasons), json.dumps(br)
        out.append(rs)
    db.commit()
    return out


def _vacc_coverage(db, village_id: int) -> float:
    total = db.query(func.count(Animal.id)).filter(Animal.village_id == village_id).scalar() or 0
    if not total:
        return 1.0
    cutoff = date.today() - timedelta(days=365)
    done = (db.query(func.count(func.distinct(Vaccination.animal_id)))
              .filter(Vaccination.village_id == village_id,
                      Vaccination.given_on >= cutoff).scalar() or 0)
    return min(1.0, done / total)


def refresh_all(db):
    """Full intelligence pass: detection then risk (risk consumes clusters)."""
    obs = run_detection(db)
    compute_risk(db)
    return obs

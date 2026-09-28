"""PashuAarogya AI — FastAPI application (all routes).

Run:  python main.py        (from backend/)
Then open http://127.0.0.1:8000
"""
import os, json, hmac, base64, hashlib, random, time, traceback
from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import Base, engine, get_db, SessionLocal
from .models import (Location, User, Farmer, Animal, Case, Vaccination, HealthCentre,
                    Treatment, Sample, RiskScore, Outbreak, Alert, AuditLog,
                    WeatherObservation, Claim, Task, Camp)
from . import engine as intel
from . import seed as seeder
from . import weather as wx
from . import keepalive
from . import forecast as fc

AI_URL = os.environ.get("PASHU_AI_URL", "http://127.0.0.1:8001")

SECRET = os.environ.get("PASHU_SECRET", "pashuraksha-demo-secret")
DEMO_OTP = "123456"

app = FastAPI(title="PashuAarogya AI", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


# ------------------------------------------------------------------ startup --
@app.on_event("startup")
def startup():
    """Create tables, then seed in a background thread.

    On a managed Postgres every insert is a network round-trip, so seeding the
    demo world takes far longer than it does against local SQLite. Doing it
    inline would hold the port closed past a platform health-check timeout, so
    the app starts serving immediately and reports progress on /healthz.
    """
    _u = str(engine.url)
    print(f"[boot] database = {_u.split('@')[-1] if '@' in _u else _u}", flush=True)

    def _boot():
        # EVERY database call lives in here, table creation included. If the
        # database is unreachable this thread fails while the web server keeps
        # serving, so /healthz can report the reason -- instead of the platform
        # seeing a process that never opens its port and restarting it forever.
        try:
            BOOT["stage"] = "connecting"
            Base.metadata.create_all(bind=engine)
            # migrations for databases created before these columns existed
            for ddl in ("ALTER TABLE treatments ADD COLUMN withdrawal_days INTEGER DEFAULT 0",
                        "ALTER TABLE cases ADD COLUMN breed VARCHAR"):
                try:
                    with engine.begin() as conn:
                        conn.exec_driver_sql(ddl)
                except Exception:
                    pass
            db = SessionLocal()
            try:
                BOOT["stage"] = "seeding"
                if seeder.seed_all(db):
                    BOOT["stage"] = "computing risk"
                    intel.refresh_all(db)
                else:
                    # Already seeded (a cloud database holding real reports).
                    # Add only what is missing, never re-seed over live records.
                    BOOT["stage"] = "top-up"
                    added = seeder.seed_topup(db)
                    if added:
                        print(f"[boot] topped up: {', '.join(added)}", flush=True)
                        intel.refresh_all(db)
                BOOT["stage"] = "ready"
            finally:
                db.close()
        except Exception as e:                      # never kill the process
            BOOT["stage"] = "error"
            BOOT["error"] = f"{type(e).__name__}: {e}"[:400]
            traceback.print_exc()
        finally:
            BOOT["ready"] = True

    import threading
    threading.Thread(target=_boot, daemon=True).start()
    # keep the free-tier instance from idling out between demos
    keepalive.start()


# --------------------------------------------------------------------- auth --
def make_token(user_id: int) -> str:
    payload = f"{user_id}.{int(time.time())}"
    sig = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode()


def parse_token(token: str) -> Optional[int]:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        uid, ts, sig = raw.split(".")
        expect = hmac.new(SECRET.encode(), f"{uid}.{ts}".encode(),
                          hashlib.sha256).hexdigest()[:24]
        if hmac.compare_digest(sig, expect):
            return int(uid)
    except Exception:
        pass
    return None


def current_user(authorization: str = Header(default=""),
                 db: Session = Depends(get_db)) -> User:
    token = authorization.replace("Bearer ", "")
    uid = parse_token(token)
    if not uid:
        raise HTTPException(401, "Not authenticated")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(401, "Unknown user")
    return user


def audit(db, user_id, action, detail=""):
    db.add(AuditLog(user_id=user_id, action=action, detail=detail))


class OTPRequest(BaseModel):
    phone: str

class OTPVerify(BaseModel):
    phone: str
    otp: str


@app.post("/api/auth/request-otp")
def request_otp(body: OTPRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.phone == body.phone).first()
    if not user:
        raise HTTPException(404, "Phone not registered. Use a demo login from the list.")
    # In production: send SMS via gateway. Demo: fixed OTP.
    return {"sent": True, "demo_hint": DEMO_OTP}


@app.post("/api/auth/verify")
def verify_otp(body: OTPVerify, db: Session = Depends(get_db)):
    if body.otp != DEMO_OTP:
        raise HTTPException(401, "Invalid OTP")
    user = db.query(User).filter(User.phone == body.phone).first()
    if not user:
        raise HTTPException(404, "Phone not registered")
    audit(db, user.id, "login", user.role); db.commit()
    loc = db.get(Location, user.location_id) if user.location_id else None
    return {"token": make_token(user.id),
            "user": {"id": user.id, "name": user.name, "role": user.role,
                     "lang": user.lang, "location": loc.name if loc else None,
                     "location_id": user.location_id}}


@app.get("/api/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    loc = db.get(Location, user.location_id) if user.location_id else None
    return {"id": user.id, "name": user.name, "role": user.role,
            "lang": user.lang, "location": loc.name if loc else None,
            "location_id": user.location_id}


# ---------------------------------------------------------------- locations --
@app.get("/api/locations")
def locations(db: Session = Depends(get_db)):
    rows = db.query(Location).all()
    return [{"id": l.id, "name": l.name, "name_mr": l.name_mr, "level": l.level,
             "lgd": l.lgd_code, "parent_id": l.parent_id,
             "lat": l.lat, "lon": l.lon} for l in rows]


# ----------------------------------------------------------------------- KB --
@app.get("/api/kb")
def get_kb():
    return intel.load_kb()


@app.post("/api/kb/reload")
def reload_kb(user: User = Depends(current_user), db: Session = Depends(get_db)):
    kb = intel.load_kb(force=True)
    audit(db, user.id, "kb_reload", f"{len(kb['diseases'])} diseases"); db.commit()
    return {"reloaded": True, "diseases": list(kb["diseases"].keys())}


# ------------------------------------------------------------------ animals --
@app.get("/api/animals")
def my_animals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    fm = db.query(Farmer).filter(Farmer.user_id == user.id).first()
    if not fm:
        return []
    out = []
    for a in fm.animals:
        vaccs = (db.query(Vaccination).filter(Vaccination.animal_id == a.id)
                   .order_by(Vaccination.given_on.desc()).all())
        out.append({"id": a.id, "tag_id": a.tag_id, "species": a.species,
                    "breed": a.breed, "sex": a.sex, "age_months": a.age_months,
                    "vaccinations": [{"disease": v.disease_key,
                                      "given_on": str(v.given_on),
                                      "due_on": str(v.due_on)} for v in vaccs],
                    "withdrawal": _withdrawal_status(db, a.id),
                    "permit": _permit_status(db, a.village_id, a.id)})
    return out


# ------------------------------------------------ passport / permit helpers --
def _withdrawal_status(db, animal_id: int):
    """Milk/meat withdrawal countdown from the latest treatment on this animal."""
    tr = (db.query(Treatment).join(Case, Treatment.case_id == Case.id)
            .filter(Case.animal_id == animal_id)
            .order_by(Treatment.given_at.desc()).first())
    if not tr or not tr.withdrawal_days:
        return None
    until = tr.given_at + timedelta(days=tr.withdrawal_days)
    left = (until - datetime.utcnow()).days + 1
    if left <= 0:
        return None
    return {"until": until.date().isoformat(), "days_left": left,
            "diagnosis": tr.diagnosis, "treatment": tr.treatment}


def _permit_status(db, village_id: int, animal_id: int | None = None):
    """Movement permit: BLOCKED inside an active outbreak zone, HOLD if the
    animal itself has an open case, else ALLOWED. Enforced at checkposts/markets
    by scanning the passport QR."""
    kb = intel.load_kb()
    for ob in db.query(Outbreak).filter(Outbreak.status == "ACTIVE").all():
        zone = json.loads(ob.zone_village_ids or "[]")
        if village_id in zone:
            dn = kb["diseases"].get(ob.suspected or "", {}).get("name", {})
            until = (ob.detected_at + timedelta(days=21)).date().isoformat()
            return {"status": "BLOCKED",
                    "reason_en": f"Village inside active {dn.get('en', 'disease')} "
                                 f"containment zone (cluster #{ob.id})",
                    "reason_hi": f"गाँव सक्रिय {dn.get('hi', 'रोग')} नियंत्रण क्षेत्र में है",
                    "reason_mr": f"गाव सक्रिय {dn.get('mr', 'रोग')} नियंत्रण क्षेत्रात आहे",
                    "until": until, "outbreak_id": ob.id}
    if animal_id:
        open_case = (db.query(Case).filter(Case.animal_id == animal_id,
                                           Case.status.notin_(["CLOSED"])).first())
        if open_case:
            return {"status": "HOLD",
                    "reason_en": f"Animal has an open case #{open_case.id} ({open_case.status})",
                    "reason_hi": f"पशु का केस #{open_case.id} चल रहा है",
                    "reason_mr": f"जनावराची केस #{open_case.id} सुरू आहे",
                    "until": None}
    return {"status": "ALLOWED", "reason_en": "No restriction",
            "reason_hi": "कोई प्रतिबंध नहीं", "reason_mr": "कोणतेही निर्बंध नाहीत", "until": None}


class AnimalIn(BaseModel):
    species: str
    breed: str = ""
    sex: str = "F"
    age_months: int = 24


@app.post("/api/animals")
def add_animal(body: AnimalIn, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    fm = db.query(Farmer).filter(Farmer.user_id == user.id).first()
    if not fm:
        raise HTTPException(403, "Farmer profile required")
    tag = f"IN{random.randint(100000000000, 999999999999)}"
    a = Animal(tag_id=tag, species=body.species, breed=body.breed, sex=body.sex,
               age_months=body.age_months, farmer_id=fm.id, village_id=fm.village_id)
    db.add(a); audit(db, user.id, "animal_add", tag); db.commit()
    return {"id": a.id, "tag_id": tag}


def _resolve_onset(body) -> date:
    """When the animal actually fell ill, as the farmer reported it.

    Accepts an ISO date or a number of days ago, clamps to a sane window
    (not in the future, not more than a year back) and falls back to today.
    """
    today = date.today()
    try:
        if body.onset_date:
            d = date.fromisoformat(str(body.onset_date)[:10])
            return min(max(d, today - timedelta(days=365)), today)
        if body.onset_days_ago is not None:
            n = max(0, min(int(body.onset_days_ago), 365))
            return today - timedelta(days=n)
    except (ValueError, TypeError):
        pass
    return today


# ------------------------------------------------------------------ reports --
class ReportIn(BaseModel):
    client_uuid: Optional[str] = None
    species: str
    symptoms: list[str]
    affected_count: int = 1
    dead_count: int = 0
    animal_id: Optional[int] = None
    village_id: Optional[int] = None
    notes: str = ""
    photo: Optional[str] = None
    channel: str = "app"
    breed: Optional[str] = None
    # How long the animal has been ill. The PS's first expected outcome is
    # "reduced reporting time", which is unmeasurable without this: before, the
    # onset was silently stamped as today and every delay came out as zero.
    onset_date: Optional[str] = None        # ISO date from a picker
    onset_days_ago: Optional[int] = None    # or "3 days" from the voice interview


@app.post("/api/reports")
def create_report(body: ReportIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    # offline dedup
    if body.client_uuid:
        dup = db.query(Case).filter(Case.client_uuid == body.client_uuid).first()
        if dup:
            return _case_out(db, dup, dedup=True)

    fm = db.query(Farmer).filter(Farmer.user_id == user.id).first()
    village_id = body.village_id or (fm.village_id if fm else user.location_id)
    if not village_id:
        raise HTTPException(400, "No village context")
    v = db.get(Location, village_id)
    t = intel.triage(body.species, body.symptoms, body.dead_count,
                     body.affected_count)
    # breed: explicit, else inherited from the tagged animal (historical trends)
    breed = body.breed
    if not breed and body.animal_id:
        an = db.get(Animal, body.animal_id)
        breed = an.breed if an else None
    c = Case(client_uuid=body.client_uuid, village_id=village_id,
             farmer_id=fm.id if fm else None, animal_id=body.animal_id,
             species=body.species, breed=breed, symptoms=",".join(body.symptoms),
             affected_count=body.affected_count, dead_count=body.dead_count,
             onset_date=_resolve_onset(body), channel=body.channel,
             photo=body.photo, notes=body.notes, lat=v.lat, lon=v.lon,
             triage_band=t["band"], triage_score=t["score"],
             suspected=t["suspected"], zoonotic_flag=t["zoonotic"],
             status="TRIAGED")
    db.add(c); db.flush()
    audit(db, user.id, "report", f"case {c.id} {t['band']}")

    # high-band cases auto-escalate an alert to the vet queue
    if t["band"] == "high":
        db.add(Alert(kind="outbreak" if t["zoonotic"] else "advisory",
                     severity="high",
                     title=f"HIGH triage case #{c.id} in {v.name}",
                     body="; ".join(t["reasons"]), village_id=village_id,
                     target_role="vet"))
    db.commit()

    # re-run intelligence so the new report immediately affects clusters & risk
    intel.refresh_all(db)
    return _case_out(db, c, triage_reasons=t["reasons"])


def _case_out(db, c: Case, triage_reasons=None, dedup=False):
    v = db.get(Location, c.village_id)
    kb = intel.load_kb()
    sus_names = [kb["diseases"][k]["name"]["en"]
                 for k in (c.suspected or "").split(",") if k in kb["diseases"]]
    return {"id": c.id, "village": v.name if v else None,
            "village_id": c.village_id, "species": c.species, "breed": c.breed,
            "symptoms": (c.symptoms or "").split(","),
            "affected_count": c.affected_count, "dead_count": c.dead_count,
            "reported_at": c.reported_at.isoformat() if c.reported_at else None,
            "channel": c.channel, "status": c.status,
            "triage_band": c.triage_band, "triage_score": c.triage_score,
            "suspected": (c.suspected or "").split(",") if c.suspected else [],
            "suspected_names": sus_names, "zoonotic": bool(c.zoonotic_flag),
            "notes": c.notes, "deduplicated": dedup,
            "triage_reasons": triage_reasons,
            "samples": [{"id": s.id, "code": s.code, "status": s.status,
                         "lab_result": s.lab_result,
                         "result_disease": s.result_disease} for s in c.samples]}


@app.get("/api/reports/mine")
def my_reports(user: User = Depends(current_user), db: Session = Depends(get_db)):
    fm = db.query(Farmer).filter(Farmer.user_id == user.id).first()
    if not fm:
        return []
    rows = (db.query(Case).filter(Case.farmer_id == fm.id)
              .order_by(Case.reported_at.desc()).limit(20).all())
    return [_case_out(db, c) for c in rows]


# -------------------------------------------------------------------- cases --
@app.get("/api/cases")
def list_cases(status: Optional[str] = None, band: Optional[str] = None,
               days: int = 14, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    q = db.query(Case).filter(
        Case.reported_at >= datetime.utcnow() - timedelta(days=days))
    if status:
        q = q.filter(Case.status == status)
    if band:
        q = q.filter(Case.triage_band == band)
    # scope by role
    if user.role in ("block",) and user.location_id:
        vids = [l.id for l in db.query(Location)
                .filter(Location.parent_id == user.location_id).all()]
        q = q.filter(Case.village_id.in_(vids))
    rows = q.order_by(Case.reported_at.desc()).limit(200).all()
    order = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda c: (order.get(c.triage_band, 3),))
    return [_case_out(db, c) for c in rows]


class CaseAction(BaseModel):
    action: str            # assign|investigate|treat|escalate|close|confirm|negative
    diagnosis: str = ""
    treatment: str = ""
    escalate_to: str = ""
    withdrawal_days: int = 0   # milk/meat withdrawal after antibiotics


VALID_TRANSITIONS = {
    "assign": ("TRIAGED", "ASSIGNED"), "investigate": ("ASSIGNED", "UNDER_INVESTIGATION"),
    "treat": ("UNDER_INVESTIGATION", "TREATMENT"), "close": ("*", "CLOSED"),
    "escalate": ("*", None), "confirm": ("*", "CONFIRMED"),
}


@app.post("/api/cases/{case_id}/action")
def case_action(case_id: int, body: CaseAction,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Case, case_id)
    if not c:
        raise HTTPException(404, "Case not found")
    a = body.action
    if a == "assign":
        c.status, c.assigned_to = "ASSIGNED", user.id
    elif a == "investigate":
        c.status = "UNDER_INVESTIGATION"
    elif a == "treat":
        c.status = "TREATMENT"
        db.add(Treatment(case_id=c.id, vet_id=user.id,
                         diagnosis=body.diagnosis, treatment=body.treatment,
                         withdrawal_days=max(0, body.withdrawal_days)))
        if body.withdrawal_days > 0 and c.farmer_id:
            fm = db.get(Farmer, c.farmer_id)
            fu = db.get(User, fm.user_id) if fm else None
            for lg, ttl, bd in (
                ("hi", f"दूध बिक्री रोकें — {body.withdrawal_days} दिन",
                       f"केस #{c.id}: दवा के बाद {body.withdrawal_days} दिन दूध/मांस न बेचें "
                       f"(खाद्य सुरक्षा)। तारीख पशुआरोग्य पासपोर्ट में देखें।"),
                ("mr", f"दूध विक्री थांबवा — {body.withdrawal_days} दिवस",
                       f"केस #{c.id}: औषधोपचारानंतर {body.withdrawal_days} दिवस दूध/मांस विकू नका "
                       f"(अन्न सुरक्षा). पशुआरोग्य पासपोर्टमध्ये तारीख पहा."),
                ("en", f"Stop selling milk — {body.withdrawal_days} days",
                       f"Case #{c.id}: milk/meat withdrawal for {body.withdrawal_days} days after "
                       f"treatment (food safety). Date shown on the animal passport.")):
                db.add(Alert(kind="advisory", severity="high", title=f"[{lg}] {ttl}",
                             body=bd, village_id=c.village_id, target_role="farmer", lang=lg))
    elif a == "escalate":
        c.escalated_to = body.escalate_to or "block"
        v = db.get(Location, c.village_id)
        db.add(Alert(kind="outbreak", severity="high",
                     title=f"Case #{c.id} escalated to {c.escalated_to}",
                     body=f"{c.species} case in {v.name}: {c.symptoms}. "
                          f"Escalated by {user.name}.",
                     village_id=c.village_id, target_role=c.escalated_to))
    elif a == "close":
        c.status = "CLOSED"
    elif a == "confirm":
        c.status = "CONFIRMED"
    else:
        raise HTTPException(400, "Unknown action")
    audit(db, user.id, f"case_{a}", f"case {c.id}")
    db.commit()
    return _case_out(db, c)


# ------------------------------------------------------------------ samples --
@app.post("/api/cases/{case_id}/sample")
def collect_sample(case_id: int, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    c = db.get(Case, case_id)
    if not c:
        raise HTTPException(404, "Case not found")
    code = f"MH-{case_id:04d}-{random.randint(1000, 9999)}"
    s = Sample(code=code, case_id=case_id, collected_by=user.id)
    c.status = "SAMPLE_COLLECTED"
    db.add(s); audit(db, user.id, "sample_collect", code); db.commit()
    return {"id": s.id, "code": code, "status": s.status}


@app.get("/api/samples")
def list_samples(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Sample).order_by(Sample.collected_at.desc()).limit(100).all()
    out = []
    for s in rows:
        c = s.case
        v = db.get(Location, c.village_id) if c else None
        out.append({"id": s.id, "code": s.code, "status": s.status,
                    "case_id": s.case_id, "village": v.name if v else None,
                    "species": c.species if c else None,
                    "suspected": c.suspected if c else None,
                    "collected_at": s.collected_at.isoformat(),
                    "lab_result": s.lab_result,
                    "result_disease": s.result_disease})
    return out


class SampleUpdate(BaseModel):
    status: Optional[str] = None
    lab_result: Optional[str] = None
    result_disease: Optional[str] = None


@app.post("/api/samples/{sample_id}")
def update_sample(sample_id: int, body: SampleUpdate,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(Sample, sample_id)
    if not s:
        raise HTTPException(404, "Sample not found")
    if body.status:
        s.status = body.status
    if body.lab_result:
        s.status, s.lab_result = "RESULT", body.lab_result
        s.result_disease, s.result_at = body.result_disease, datetime.utcnow()
        c = s.case
        if body.lab_result == "positive" and c:
            c.status = "CONFIRMED"
            v = db.get(Location, c.village_id)
            kb = intel.load_kb()
            dn = kb["diseases"].get(body.result_disease or "", {}) \
                   .get("name", {}).get("en", body.result_disease)
            for role in ("block", "district"):
                db.add(Alert(kind="outbreak", severity="high",
                             title=f"LAB-CONFIRMED {dn} in {v.name}",
                             body=f"Sample {s.code} positive for {dn}. Containment "
                                  f"protocol: movement control + ring vaccination.",
                             village_id=c.village_id, target_role=role))
        elif body.lab_result == "negative" and c:
            c.status = "NEGATIVE"
    audit(db, user.id, "sample_update", f"{s.code} -> {s.status}")
    db.commit()
    return {"id": s.id, "code": s.code, "status": s.status,
            "lab_result": s.lab_result}


# ---------------------------------------------------------------- dashboard --
@app.get("/api/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    total_animals = db.query(func.count(Animal.id)).scalar()
    active_cases = db.query(func.count(Case.id)).filter(
        ~Case.status.in_(["CLOSED", "NEGATIVE"])).scalar()
    cases_7d = db.query(func.count(Case.id)).filter(
        Case.reported_at >= week_ago).scalar()
    deaths_7d = db.query(func.coalesce(func.sum(Case.dead_count), 0)).filter(
        Case.reported_at >= week_ago).scalar()
    high_villages = db.query(func.count(RiskScore.id)).filter(
        RiskScore.band == "high").scalar()
    outbreaks = db.query(func.count(Outbreak.id)).filter(
        Outbreak.status == "ACTIVE").scalar()
    pending_lab = db.query(func.count(Sample.id)).filter(
        Sample.status != "RESULT").scalar()
    # coverage overall
    total = db.query(func.count(Animal.id)).scalar() or 1
    vacc = db.query(func.count(func.distinct(Vaccination.animal_id))).filter(
        Vaccination.given_on >= date.today() - timedelta(days=365)).scalar()
    # median onset->report lag in hours: the PS's first expected outcome,
    # measurable now that the farmer is asked when the animal fell ill
    rows = db.query(Case.onset_date, Case.reported_at).filter(
        Case.reported_at >= now - timedelta(days=30),
        Case.onset_date.isnot(None), Case.reported_at.isnot(None)).all()
    lags = sorted(max(0.0, (rp - datetime.combine(on, datetime.min.time())).total_seconds() / 3600.0)
                  for on, rp in rows)
    median_lag = round(lags[len(lags) // 2], 1) if lags else None
    return {"total_animals": total_animals, "active_cases": active_cases,
            "cases_7d": cases_7d, "deaths_7d": int(deaths_7d),
            "high_risk_villages": high_villages, "active_outbreaks": outbreaks,
            "pending_lab": pending_lab,
            "vaccination_coverage": round(vacc / total, 3),
            "median_report_lag_h": median_lag, "lag_sample": len(lags)}


@app.get("/api/dashboard/map")
def dashboard_map(level: str = Query("village", pattern="^(village|block|district)$"),
                  db: Session = Depends(get_db)):
    """Risk map at any admin level — the aggregation unit is a parameter,
    not a hardcoded column (judge demand #2)."""
    risks = {r.village_id: r for r in db.query(RiskScore).all()}
    villages = db.query(Location).filter(Location.level == "village").all()

    def vrow(v):
        r = risks.get(v.id)
        return {"id": v.id, "name": v.name, "lat": v.lat, "lon": v.lon,
                "score": r.score if r else 0, "band": r.band if r else "low",
                "reasons": json.loads(r.reasons) if r else [],
                "breakdown": json.loads(r.breakdown) if r else {}}

    if level == "village":
        units = [vrow(v) for v in villages]
    else:
        groups = {}
        for v in villages:
            blk = db.get(Location, v.parent_id)
            key = blk.id if level == "block" else blk.parent_id
            groups.setdefault(key, []).append(vrow(v))
        units = []
        for gid, vs in groups.items():
            g = db.get(Location, gid)
            score = max(x["score"] for x in vs)
            worst = max(vs, key=lambda x: x["score"])
            units.append({"id": g.id, "name": g.name, "lat": g.lat, "lon": g.lon,
                          "score": score,
                          "band": "high" if score >= 60 else
                                  ("moderate" if score >= 35 else "low"),
                          "reasons": [f"worst village: {worst['name']}"] + worst["reasons"],
                          "breakdown": worst["breakdown"], "n_villages": len(vs)})

    clusters = []
    for ob in db.query(Outbreak).filter(Outbreak.status == "ACTIVE").all():
        c = db.get(Location, ob.center_village_id)
        kb = intel.load_kb()
        dn = kb["diseases"].get(ob.suspected or "", {}).get("name", {}).get("en", "?")
        clusters.append({"id": ob.id, "center": c.name, "lat": c.lat, "lon": c.lon,
                         "radius_km": ob.radius_km, "cases_7d": ob.cases_7d,
                         "expected": ob.expected, "p_value": ob.p_value,
                         "suspected": dn, "zoonotic": ob.zoonotic,
                         "detected_at": ob.detected_at.isoformat()})
    return {"level": level, "units": units, "clusters": clusters}


@app.get("/api/dashboard/trends")
def trends(days: int = 21, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    out = []
    for d in range(days, -1, -1):
        day0 = (now - timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
        day1 = day0 + timedelta(days=1)
        n = db.query(func.count(Case.id)).filter(
            Case.reported_at >= day0, Case.reported_at < day1).scalar()
        dead = db.query(func.coalesce(func.sum(Case.dead_count), 0)).filter(
            Case.reported_at >= day0, Case.reported_at < day1).scalar()
        out.append({"date": day0.strftime("%d %b"), "cases": n, "deaths": int(dead)})
    # species + disease distribution over the window
    since = now - timedelta(days=days)
    sp = dict(db.query(Case.species, func.count(Case.id))
                .filter(Case.reported_at >= since).group_by(Case.species).all())
    sus = {}
    for (s,) in db.query(Case.suspected).filter(Case.reported_at >= since,
                                                Case.suspected != "").all():
        k = s.split(",")[0]
        sus[k] = sus.get(k, 0) + 1
    kb = intel.load_kb()
    sus_named = {kb["diseases"].get(k, {}).get("name", {}).get("en", k): v
                 for k, v in sus.items()}
    channels = dict(db.query(Case.channel, func.count(Case.id))
                      .filter(Case.reported_at >= since)
                      .group_by(Case.channel).all())
    return {"daily": out, "species": sp, "suspected": sus_named,
            "channels": channels}


@app.get("/api/dashboard/vaccination")
def vaccination_coverage(db: Session = Depends(get_db)):
    out = []
    for blk in db.query(Location).filter(Location.level == "block").all():
        vids = [v.id for v in blk.children if v.level == "village"]
        total = db.query(func.count(Animal.id)).filter(
            Animal.village_id.in_(vids)).scalar() or 0
        done = db.query(func.count(func.distinct(Vaccination.animal_id))).filter(
            Vaccination.village_id.in_(vids),
            Vaccination.given_on >= date.today() - timedelta(days=365)).scalar() or 0
        dist = db.get(Location, blk.parent_id)
        out.append({"block": blk.name, "district": dist.name,
                    "animals": total, "vaccinated": done,
                    "coverage": round(done / total, 3) if total else 0})
    out.sort(key=lambda x: x["coverage"])
    return out


@app.get("/api/dashboard/timeline/{outbreak_id}")
def outbreak_timeline(outbreak_id: int, db: Session = Depends(get_db)):
    ob = db.get(Outbreak, outbreak_id)
    if not ob:
        raise HTTPException(404, "Outbreak not found")
    vids = json.loads(ob.zone_village_ids or "[]")
    cases = (db.query(Case).filter(Case.village_id.in_(vids))
               .order_by(Case.reported_at).limit(300).all())
    events = []
    for c in cases:
        v = db.get(Location, c.village_id)
        events.append({"at": c.reported_at.isoformat(), "kind": "report",
                       "text": f"{c.species} case in {v.name} "
                               f"({c.triage_band} triage, via {c.channel})"
                               + (f" — {c.dead_count} death(s)" if c.dead_count else "")})
        for s in c.samples:
            events.append({"at": s.collected_at.isoformat(), "kind": "sample",
                           "text": f"Sample {s.code} collected ({v.name})"})
            if s.result_at:
                events.append({"at": s.result_at.isoformat(), "kind": "lab",
                               "text": f"Lab result {s.code}: {s.lab_result} "
                                       f"({s.result_disease or ''})"})
    events.append({"at": ob.detected_at.isoformat(), "kind": "detect",
                   "text": f"Outbreak Radar flagged cluster "
                           f"(obs {ob.cases_7d} vs exp {ob.expected}, p={ob.p_value})"})
    events.sort(key=lambda e: e["at"])
    return {"outbreak": {"id": ob.id, "suspected": ob.suspected,
                         "status": ob.status}, "events": events}


# ------------------------------------------------------------------- alerts --
@app.get("/api/alerts")
def get_alerts(role: Optional[str] = None, lang: Optional[str] = None,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(Alert).order_by(Alert.created_at.desc())
    target = role or user.role
    if target == "district":
        q = q.filter(Alert.target_role.in_(["district", "block", "health"]))
    elif target == "state":
        pass  # state sees everything
    else:
        q = q.filter(Alert.target_role == target)
    if lang and target == "farmer":
        q = q.filter(Alert.lang.in_([lang, "en"]))
    rows = q.limit(60).all()
    out = []
    for a in rows:
        v = db.get(Location, a.village_id) if a.village_id else None
        out.append({"id": a.id, "kind": a.kind, "severity": a.severity,
                    "title": a.title, "body": a.body, "lang": a.lang,
                    "village": v.name if v else None,
                    "target_role": a.target_role,
                    "created_at": a.created_at.isoformat(),
                    "acknowledged": a.acknowledged})
    return out


@app.post("/api/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if a:
        a.acknowledged = True
        audit(db, user.id, "alert_ack", str(alert_id)); db.commit()
    return {"ok": True}


# ------------------------------------------------------------- intelligence --
@app.post("/api/detect/run")
def detect_run(user: User = Depends(current_user), db: Session = Depends(get_db)):
    obs = intel.refresh_all(db)
    audit(db, user.id, "detect_run", f"{len(obs)} clusters"); db.commit()
    return {"clusters": len(obs)}


@app.get("/api/risk/{village_id}")
def village_risk(village_id: int, db: Session = Depends(get_db)):
    r = db.query(RiskScore).filter(RiskScore.village_id == village_id).first()
    v = db.get(Location, village_id)
    if not r or not v:
        raise HTTPException(404, "No risk computed")
    return {"village": v.name, "score": r.score, "band": r.band,
            "reasons": json.loads(r.reasons), "breakdown": json.loads(r.breakdown),
            "computed_at": r.computed_at.isoformat()}


@app.post("/api/weather/refresh")
def weather_refresh(user: User = Depends(current_user), db: Session = Depends(get_db)):
    res = wx.refresh_district_sample(db)
    intel.compute_risk(db)
    return {"blocks_updated": list(res.keys()),
            "note": "risk recomputed with fresh weather signal"}


# ---------------------------------------------------------- claims (farmer) --
# Govt compensation schedule (demo figures aligned to NDRF/state norms)
CLAIM_AMOUNTS = {"cattle": 37500, "buffalo": 37500, "goat": 4000,
                 "sheep": 4000, "poultry": 100}


class ClaimIn(BaseModel):
    case_id: int


@app.post("/api/claims")
def file_claim(body: ClaimIn, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    fm = db.query(Farmer).filter(Farmer.user_id == user.id).first()
    if not fm:
        raise HTTPException(403, "Farmer profile required")
    c = db.get(Case, body.case_id)
    if not c or c.farmer_id != fm.id:
        raise HTTPException(404, "Case not found for this farmer")
    if not c.dead_count and c.status != "CONFIRMED":
        raise HTTPException(400, "Claim requires a reported death or a confirmed case")
    dup = db.query(Claim).filter(Claim.case_id == c.id).first()
    if dup:
        return _claim_out(db, dup)
    animal = db.get(Animal, c.animal_id) if c.animal_id else None
    cl = Claim(case_id=c.id, farmer_id=fm.id,
               animal_tag=animal.tag_id if animal else None,
               species=c.species, amount=CLAIM_AMOUNTS.get(c.species, 4000))
    db.add(cl); db.flush()
    v = db.get(Location, c.village_id)
    db.add(Alert(kind="advisory", severity="medium",
                 title=f"Compensation claim #{cl.id} filed — {v.name}",
                 body=f"{user.name}: {c.species} death, case #{c.id}, "
                      f"₹{cl.amount:,}. Verify against case record & lab status.",
                 village_id=c.village_id, target_role="district"))
    audit(db, user.id, "claim_filed", f"claim {cl.id} case {c.id}")
    db.commit()
    return _claim_out(db, cl)


def _claim_out(db, cl: Claim):
    c = db.get(Case, cl.case_id)
    v = db.get(Location, c.village_id) if c else None
    fu = db.get(User, cl.farmer.user_id) if cl.farmer else None
    return {"id": cl.id, "case_id": cl.case_id, "species": cl.species,
            "animal_tag": cl.animal_tag, "amount": cl.amount,
            "status": cl.status, "filed_at": cl.filed_at.isoformat(),
            "decided_at": cl.decided_at.isoformat() if cl.decided_at else None,
            "note": cl.note, "village": v.name if v else None,
            "farmer": fu.name if fu else None,
            "case_status": c.status if c else None}


@app.get("/api/claims/mine")
def my_claims(user: User = Depends(current_user), db: Session = Depends(get_db)):
    fm = db.query(Farmer).filter(Farmer.user_id == user.id).first()
    if not fm:
        return []
    rows = (db.query(Claim).filter(Claim.farmer_id == fm.id)
              .order_by(Claim.filed_at.desc()).all())
    return [_claim_out(db, cl) for cl in rows]


@app.get("/api/claims")
def all_claims(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in ("block", "district", "state"):
        raise HTTPException(403, "Officials only")
    rows = db.query(Claim).order_by(Claim.filed_at.desc()).limit(200).all()
    return [_claim_out(db, cl) for cl in rows]


class ClaimDecision(BaseModel):
    decision: str          # UNDER_REVIEW|APPROVED|PAID|REJECTED
    note: str = ""


@app.post("/api/claims/{claim_id}/decide")
def decide_claim(claim_id: int, body: ClaimDecision,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in ("block", "district", "state"):
        raise HTTPException(403, "Officials only")
    cl = db.get(Claim, claim_id)
    if not cl:
        raise HTTPException(404, "Claim not found")
    if body.decision not in ("UNDER_REVIEW", "APPROVED", "PAID", "REJECTED"):
        raise HTTPException(400, "Bad decision")
    cl.status, cl.note = body.decision, body.note
    cl.decided_at = datetime.utcnow()
    audit(db, user.id, "claim_decide", f"claim {cl.id} -> {body.decision}")
    db.commit()
    return _claim_out(db, cl)


# ------------------------------------------------------------- action queue --
@app.get("/api/tasks")
def list_tasks(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(Task).order_by(Task.status.desc(), Task.created_at.desc())
    rows = q.limit(100).all()
    out = []
    for t in rows:
        v = db.get(Location, t.village_id) if t.village_id else None
        out.append({"id": t.id, "kind": t.kind, "title": t.title,
                    "village": v.name if v else None,
                    "assigned_role": t.assigned_role, "status": t.status,
                    "created_at": t.created_at.isoformat(),
                    "done_at": t.done_at.isoformat() if t.done_at else None})
    order = {"OPEN": 0, "IN_PROGRESS": 1, "DONE": 2}
    out.sort(key=lambda x: (order.get(x["status"], 3), x["created_at"]))
    return out


class TaskUpdate(BaseModel):
    status: str


@app.post("/api/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    if body.status not in ("OPEN", "IN_PROGRESS", "DONE"):
        raise HTTPException(400, "Bad status")
    t.status = body.status
    t.done_at = datetime.utcnow() if body.status == "DONE" else None
    audit(db, user.id, "task_update", f"task {t.id} -> {body.status}")
    db.commit()
    return {"id": t.id, "status": t.status}


# -------------------------------------------------------- vaccination camps --
@app.get("/api/camps")
def list_camps(mine: bool = False, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    q = db.query(Camp).filter(Camp.camp_date >= date.today() - timedelta(days=2))
    if mine:
        fm = db.query(Farmer).filter(Farmer.user_id == user.id).first()
        if fm:
            v = db.get(Location, fm.village_id)
            sibling_ids = [x.id for x in db.query(Location)
                           .filter(Location.parent_id == v.parent_id).all()]
            q = q.filter(Camp.village_id.in_(sibling_ids))
    rows = q.order_by(Camp.camp_date).limit(50).all()
    kb = intel.load_kb()
    out = []
    for cp in rows:
        v = db.get(Location, cp.village_id)
        blk = db.get(Location, v.parent_id) if v else None
        dn = kb["diseases"].get(cp.disease_key or "", {}).get("name", {})
        out.append({"id": cp.id, "village": v.name if v else None,
                    "block": blk.name if blk else None,
                    "disease": cp.disease_key,
                    "disease_name": dn.get("en", cp.disease_key),
                    "disease_name_mr": dn.get("mr", ""),
                    "date": str(cp.camp_date), "name": cp.name,
                    "status": cp.status})
    return out


class CampIn(BaseModel):
    village_id: int
    disease_key: str
    camp_date: str          # YYYY-MM-DD
    name: str = ""


@app.post("/api/camps")
def create_camp(body: CampIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    if user.role not in ("block", "district", "state"):
        raise HTTPException(403, "Officials only")
    v = db.get(Location, body.village_id)
    if not v:
        raise HTTPException(404, "Village not found")
    kb = intel.load_kb()
    dn = kb["diseases"].get(body.disease_key, {}).get("name", {}).get("en",
                                                                     body.disease_key)
    cp = Camp(village_id=body.village_id, disease_key=body.disease_key,
              camp_date=date.fromisoformat(body.camp_date),
              name=body.name or f"{dn} vaccination camp — {v.name}")
    db.add(cp); db.flush()
    act = kb["diseases"].get(body.disease_key, {})
    for lang, txt in (("hi", f"टीकाकरण शिविर: {v.name} में {cp.camp_date:%d/%m/%Y} को "
                             f"{act.get('name', {}).get('hi', dn)} टीका मुफ़्त। अपने पशु लेकर आएं।"),
                      ("mr", f"लसीकरण शिबिर: {v.name} येथे {cp.camp_date:%d/%m/%Y} रोजी "
                             f"{act.get('name', {}).get('mr', dn)} लस मोफत. आपली जनावरे घेऊन या."),
                      ("en", f"Vaccination camp at {v.name} on {cp.camp_date:%d %b %Y} — "
                             f"free {dn} vaccine. Bring your animals.")):
        db.add(Alert(kind="vaccination", severity="medium",
                     title=f"[{lang}] {dn} camp — {v.name}",
                     body=txt, village_id=v.id, target_role="farmer", lang=lang))
    audit(db, user.id, "camp_create", f"camp {cp.id} {v.name}")
    db.commit()
    return {"id": cp.id, "name": cp.name, "date": str(cp.camp_date)}


# ---------------------------------------------------------- farmer weather --
@app.get("/api/myweather")
def my_weather(user: User = Depends(current_user), db: Session = Depends(get_db)):
    fm = db.query(Farmer).filter(Farmer.user_id == user.id).first()
    vid = fm.village_id if fm else user.location_id
    if not vid:
        raise HTTPException(400, "No village context")
    v = db.get(Location, vid)
    w = wx.refresh_village_weather(db, v)
    return {"village": v.name, "weather": w}


# -------------------------------------------------------------- CSV exports --
from fastapi.responses import Response


@app.get("/api/export/{what}.csv")
def export_csv(what: str, db: Session = Depends(get_db)):
    import io, csv
    buf = io.StringIO()
    w = csv.writer(buf)
    if what == "cases":
        w.writerow(["id", "village", "species", "symptoms", "affected", "dead",
                    "triage", "suspected", "status", "channel", "reported_at"])
        for c in db.query(Case).order_by(Case.reported_at.desc()).limit(2000):
            v = db.get(Location, c.village_id)
            w.writerow([c.id, v.name if v else "", c.species, c.symptoms,
                        c.affected_count, c.dead_count, c.triage_band,
                        c.suspected, c.status, c.channel, c.reported_at])
    elif what == "claims":
        w.writerow(["id", "case_id", "species", "amount", "status", "filed_at"])
        for cl in db.query(Claim).all():
            w.writerow([cl.id, cl.case_id, cl.species, cl.amount, cl.status,
                        cl.filed_at])
    elif what == "vaccination":
        w.writerow(["block", "district", "animals", "vaccinated", "coverage"])
        for r in vaccination_coverage(db):
            w.writerow([r["block"], r["district"], r["animals"],
                        r["vaccinated"], r["coverage"]])
    else:
        raise HTTPException(404, "Unknown export")
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename=pashuraksha_{what}.csv"})



BOOT = {"ready": False, "stage": "starting", "error": None,
        "started": datetime.utcnow().isoformat()}


@app.get("/healthz")
def healthz():
    """Platform health check + keep-alive target.

    Deliberately takes NO database dependency: if it did, a bad database would
    make the health check hang, the platform would restart the service, and the
    real cause would never be visible. Always 200 once the process is up;
    `stage`/`error` say what the database is doing.
    """
    n = None
    if BOOT["ready"] and BOOT["stage"] == "ready":
        try:
            db = SessionLocal()
            n = db.query(func.count(Location.id)).scalar() or 0
            db.close()
        except Exception:
            n = -1
    url = str(engine.url)
    return {"ok": True, "ready": BOOT["ready"], "stage": BOOT["stage"],
            "error": BOOT["error"], "locations": n,
            "keepalive": {k: keepalive.STATE[k] for k in
                          ("enabled", "last_ok", "pings", "failures", "last_error")},
            "db": "postgres" if "postgres" in url else "sqlite",
            "db_host": url.split("@")[-1].split("/")[0] if "@" in url else "local",
            "started": BOOT["started"], "now": datetime.utcnow().isoformat()}


@app.get("/api/hostinfo")
def hostinfo():
    """Addresses a phone can use: the public HTTPS tunnel (any network —
    started by tunnel.py) and, as a fallback, the LAN address."""
    import socket, urllib.request as _ur
    urls = []
    try:
        s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s_.connect(("8.8.8.8", 80))
        urls.append(f"http://{s_.getsockname()[0]}:8000")
        s_.close()
    except Exception:
        pass
    public = None
    now_ = time.time()
    if _PUB["url"] and now_ - _PUB["ts"] < 120:          # cached (ngrok's API is slow)
        public = _PUB["url"]
    if not public:   # tunnel.py writes the URL here — instant
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public_url.txt")
        try:
            if now_ - os.path.getmtime(p) < 12 * 3600:
                public = open(p, encoding="utf-8").read().strip() or None
        except OSError:
            pass
    if not public:   # live ngrok agent API (can take several seconds on Windows)
        try:
            with _ur.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=6) as r:
                t = json.loads(r.read().decode()).get("tunnels", [])
            https = [x["public_url"] for x in t if x.get("public_url", "").startswith("https")]
            public = (https or [x["public_url"] for x in t] or [None])[0]
        except Exception:
            pass
    if public:
        _PUB.update(url=public, ts=now_)
    return {"urls": urls, "public_url": public}


_PUB = {"url": None, "ts": 0.0}


# ------------------------------------------ Pashu Lens: AI identification --
# Proxies to the PashuPehchaan breed-recognition sidecar (EfficientNetV2,
# 50 Indian cattle/buffalo breeds, subject + quality gates). Degrades honestly.
import urllib.request, urllib.error

BREED_MR = {
    "Gir_Cow": "गीर", "GirCross": "गीर संकर", "Khillari": "खिल्लार", "Deoni": "देवणी",
    "Dangi": "डांगी", "Red_sindhi": "लाल सिंधी", "Sahiwal": "साहिवाल",
    "SahiwalCross": "साहिवाल संकर", "HFCross": "एच.एफ. संकर", "Holstein_friesian": "होल्स्टिन फ्रिजियन",
    "JerseyCross": "जर्सी संकर", "jersey": "जर्सी", "Kankrej": "कांकरेज", "Tharparkar": "थारपारकर",
    "Ongole": "ओंगोल", "hariana": "हरियाणा", "Rathi": "राठी", "Hallikar": "हल्लीकर",
    "amritmahal": "अमृतमहल", "Murrah": "मुऱ्हा", "Pandharpuri": "पंढरपुरी", "Nagpuri": "नागपुरी",
    "Jafrabadi": "जाफराबादी", "Surti": "सुरती", "Mehsana": "मेहसाणा", "Nili_Ravi": "नीली रावी",
    "Banni": "बन्नी", "Bhadwari": "भदावरी", "Toda": "तोडा", "Red_Dane": "रेड डेन",
    "Brown_Swiss": "ब्राउन स्विस", "Gurnesey": "ग्वेर्न्सी", "Aryshire": "आयरशायर",
    "Kenkatha": "केनकथा", "Kherigarh": "खेरीगढ", "Gangatiri": "गंगातिरी", "Malnad_gidda": "मलनाड गिड्डा",
    "vechur": "वेचूर", "kangyam": "कांगायम", "pulikulam": "पुलिकुलम", "Umblachery": "उंबलाचेरी",
    "krishna_valley": "कृष्णा व्हॅली", "nagori": "नागोरी", "nimari": "निमारी", "bargur_cow": "बारगूर",
    "Binjharpuri": "बिंझारपुरी", "Badri_cow": "बद्री", "Ladakhi_cow": "लडाखी", "Kasargod": "कासरगोड",
    "Girlando": "गिरलांडो",
}


def _pretty_breed(label: str):
    return label.replace("_", " ").replace(" cow", "").replace(" Cow", "").strip().title()


def _ai_get(path, timeout=2):
    with urllib.request.urlopen(AI_URL + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


# Probing a sidecar that isn't there costs a connect timeout on every page load,
# so the answer is cached: briefly when up, longer when it is simply not deployed
# (the usual case on a cloud backup instance without the 235 MB model).
_AI_CACHE = {"at": 0.0, "val": None}
AI_DISABLED = os.environ.get("PASHU_AI_DISABLED", "").lower() in ("1", "true", "yes")
_AI_ABSENT_MSG = ("Breed identification is not enabled on this deployment. "
                  "You can still register the animal by hand.")


@app.get("/api/ai/status")
def ai_status():
    now = time.time()
    ttl = 20 if (_AI_CACHE["val"] or {}).get("available") else 120
    if _AI_CACHE["val"] is not None and now - _AI_CACHE["at"] < ttl:
        return _AI_CACHE["val"]
    if AI_DISABLED:
        out = {"available": False, "model_loaded": False, "disabled": True,
               "error": _AI_ABSENT_MSG}
    else:
        try:
            h = _ai_get("/health", timeout=2)
            out = {"available": True, "model_loaded": h.get("model_loaded"),
                   "model_version": h.get("model_version"), "labels": h.get("labels"),
                   "gate": (h.get("subject_gate") or {}).get("loaded")}
        except Exception:
            out = {"available": False, "model_loaded": False, "error": _AI_ABSENT_MSG}
    _AI_CACHE.update(at=now, val=out)
    return out


class IdentifyIn(BaseModel):
    image: str


@app.post("/api/ai/identify")
def ai_identify(body: IdentifyIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    if AI_DISABLED:
        return {"success": False, "available": False, "error": _AI_ABSENT_MSG}
    try:
        req = urllib.request.Request(
            AI_URL + "/predict", data=json.dumps({"image": body.image}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode())
    except Exception:
        return {"success": False, "available": False, "error": _AI_ABSENT_MSG}
    res["available"] = True
    if res.get("success"):
        sp = {"cow": "cattle", "buffalo": "buffalo"}.get(res.get("species"), "cattle")
        conf = float(res.get("best_confidence") or 0)
        res["species_app"] = sp
        res["band"] = "high" if conf >= 0.7 else ("medium" if conf >= 0.45 else "low")
        for c in res.get("top3", []):
            c["label"] = _pretty_breed(c["breed"])
            c["label_mr"] = BREED_MR.get(c["breed"], _pretty_breed(c["breed"]))
            c["species_app"] = {"cow": "cattle", "buffalo": "buffalo"}.get(c.get("species"), "cattle")
        res["best_label"] = _pretty_breed(res.get("best_breed") or "")
        res["best_label_mr"] = BREED_MR.get(res.get("best_breed"), res["best_label"])
        audit(db, user.id, "ai_identify",
              f"{res.get('best_breed')} {round(conf, 2)}"); db.commit()
    return res


# ---------------------------------------------- forecast / what-if planner --
@app.get("/api/forecast")
def forecast_api(days: int = 7, ring_km: float = 12.0,
                 outbreak_id: Optional[int] = None,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    days = max(3, min(14, days))
    return fc.compare(db, days=days, ring_km=ring_km, outbreak_id=outbreak_id)


# --------------------------------------------- animal health passport (public)
@app.get("/api/passport/{tag}")
def passport(tag: str, db: Session = Depends(get_db)):
    a = db.query(Animal).filter(Animal.tag_id == tag).first()
    if not a:
        raise HTTPException(404, "No animal with this tag")
    v = db.get(Location, a.village_id)
    blk = db.get(Location, v.parent_id) if v else None
    dist = db.get(Location, blk.parent_id) if blk else None
    fm = db.get(Farmer, a.farmer_id) if a.farmer_id else None
    owner = db.get(User, fm.user_id) if fm else None
    kb = intel.load_kb()
    vaccs = (db.query(Vaccination).filter(Vaccination.animal_id == a.id)
               .order_by(Vaccination.given_on.desc()).all())
    cases = (db.query(Case).filter(Case.animal_id == a.id)
               .order_by(Case.reported_at.desc()).all())
    treatments = []
    for c in cases:
        for tr in db.query(Treatment).filter(Treatment.case_id == c.id).all():
            treatments.append({"case_id": c.id, "diagnosis": tr.diagnosis,
                               "treatment": tr.treatment,
                               "given_at": tr.given_at.isoformat(),
                               "withdrawal_days": tr.withdrawal_days or 0})
    return {
        "tag_id": a.tag_id, "species": a.species, "breed": a.breed, "sex": a.sex,
        "age_months": a.age_months,
        "owner": (owner.name.split(" ")[0] + " " + owner.name.split(" ")[-1][:1] + ".")
                 if owner and " " in owner.name else (owner.name if owner else None),
        "village": v.name if v else None, "block": blk.name if blk else None,
        "district": dist.name if dist else None,
        "vaccinations": [{"disease": x.disease_key,
                          "disease_name": kb["diseases"].get(x.disease_key, {})
                                            .get("name", {}).get("en", x.disease_key),
                          "disease_name_mr": kb["diseases"].get(x.disease_key, {})
                                            .get("name", {}).get("mr", ""),
                          "disease_name_hi": kb["diseases"].get(x.disease_key, {})
                                            .get("name", {}).get("hi", ""),
                          "given_on": str(x.given_on), "due_on": str(x.due_on),
                          "campaign": x.campaign} for x in vaccs],
        "cases": [{"id": c.id, "status": c.status, "symptoms": c.symptoms,
                   "reported_at": c.reported_at.isoformat(),
                   "suspected": c.suspected} for c in cases[:5]],
        "treatments": treatments[:5],
        "withdrawal": _withdrawal_status(db, a.id),
        "permit": _permit_status(db, a.village_id, a.id),
        "verified_at": datetime.utcnow().isoformat(),
    }


# ------------------------------------------------------------------ SITREP --
@app.get("/api/sitrep")
def sitrep(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in ("block", "district", "state"):
        raise HTTPException(403, "Officials only")
    summ = dashboard_summary(db)
    mp = dashboard_map("village", db)
    tasks_ = list_tasks(user, db)
    claims_ = all_claims(user, db)
    vacc = vaccination_coverage(db)
    alerts_ = get_alerts(None, None, user, db)
    fcst = fc.compare(db, days=7, ring_km=12.0)["summary"]
    return {"generated_at": datetime.utcnow().isoformat(), "by": user.name,
            "role": user.role, "summary": summ, "clusters": mp["clusters"],
            "high_risk": [u for u in mp["units"] if u["band"] == "high"][:15],
            "tasks_open": [t for t in tasks_ if t["status"] != "DONE"][:20],
            "claims": {"pending": sum(1 for c in claims_ if c["status"] in ("FILED", "UNDER_REVIEW")),
                       "approved": sum(1 for c in claims_ if c["status"] in ("APPROVED", "PAID")),
                       "amount_approved": sum(c["amount"] for c in claims_
                                              if c["status"] in ("APPROVED", "PAID"))},
            "vaccination": vacc, "alerts": alerts_[:10], "forecast": fcst}


# ------------------------------------------ पशु मित्र · Gemini-powered brain --
# Rule-based skills answer first (fast, offline). Anything free-form goes to
# Gemini with live context from the platform. Keys come from a .env file
# (repo root / pashuraksha / backend) — never committed.
def _load_env():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "..", "..", ".env"), os.path.join(here, "..", ".env"),
              os.path.join(here, ".env")):
        try:
            if os.path.exists(p):
                with open(p, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        val = v.strip().strip('"').strip("'")
                        if val:
                            os.environ[k.strip()] = val
        except OSError:
            pass


def _get_gemini_key():
    _load_env()
    return os.environ.get("GEMINI_API_KEY", "").strip()


_load_env()
GEMINI_MODELS = ([os.environ["GEMINI_MODEL"]] if os.environ.get("GEMINI_MODEL")
                 else ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-flash-latest", "gemini-3.8-flash"])
_GEMINI_OK = {"model": None}

SYMPTOM_CODES = ["fever", "nodules", "lameness", "oral_lesions", "hoof_lesions", "salivation",
                 "nasal_discharge", "ocular_discharge", "cough", "diarrhoea", "bloat", "swelling",
                 "sudden_death", "abortion", "low_milk", "anorexia", "itching", "red_urine",
                 "udder_swelling", "aggression", "twisted_neck", "egg_drop", "ticks"]
LANG_NAME = {"hi": "Hindi", "mr": "Marathi", "en": "English"}


@app.get("/api/assistant/status")
def assistant_status():
    key = _get_gemini_key()
    return {"llm": bool(key), "model": _GEMINI_OK["model"] or GEMINI_MODELS[0],
            "provider": "Google Gemini" if key else None}


def _assistant_context(db, user, page: str) -> str:
    """Live facts the model may use — it must not invent anything else."""
    kb = intel.load_kb()
    lines = [f"User: {user.name}, role={user.role}"]
    if page == "farmer":
        fm = db.query(Farmer).filter(Farmer.user_id == user.id).first()
        if fm:
            v = db.get(Location, fm.village_id)
            lines.append(f"Village: {v.name if v else '?'}")
            animals = db.query(Animal).filter(Animal.farmer_id == fm.id).all()
            by_sp = {}
            for a in animals:
                by_sp[a.species] = by_sp.get(a.species, 0) + 1
            lines.append("Animals: " + ", ".join(f"{n} {sp}" for sp, n in by_sp.items()) or "none")
            due = sum(1 for a in animals if not db.query(Vaccination)
                      .filter(Vaccination.animal_id == a.id).first())
            lines.append(f"Animals without any vaccination record: {due}")
            blocked = sum(1 for a in animals
                          if _permit_status(db, a.village_id, a.id)["status"] == "BLOCKED")
            if blocked:
                lines.append(f"Movement BLOCKED for {blocked} animal(s): village inside an active "
                             f"outbreak containment zone")
            for a in animals:
                wd = _withdrawal_status(db, a.id)
                if wd:
                    lines.append(f"FOOD SAFETY: {a.species} {a.tag_id} is under treatment "
                                 f"({wd['treatment']}); milk/meat withdrawal — must NOT be sold "
                                 f"for {wd['days_left']} more day(s), until {wd['until']}")
            cl = (db.query(Claim).filter(Claim.farmer_id == fm.id)
                    .order_by(Claim.filed_at.desc()).first())
            if cl:
                lines.append(f"Latest compensation claim: #{cl.id} Rs {cl.amount} status {cl.status}")
            camps = list_camps(True, user, db)[:2]
            for c in camps:
                lines.append(f"Vaccination camp: {c['disease_name']} at {c['village']} on {c['date']} (free)")
            try:
                w = wx.refresh_village_weather(db, v) if v else None
                if w and w.get("temp_c") is not None:
                    lines.append(f"Weather today: {round(w['temp_c'])}C, humidity {round(w['humidity'])}%, "
                                 f"rain {w.get('rain_mm', 0)} mm")
            except Exception:
                pass
            for a in get_alerts("farmer", user.lang or "hi", user, db)[:2]:
                lines.append(f"Recent advisory: {a['title']} — {a['body'][:140]}")
    else:
        s = dashboard_summary(db)
        lines.append(f"State summary: {s['active_outbreaks']} active clusters, {s['cases_7d']} reports "
                     f"and {s['deaths_7d']} deaths in 7 days, {s['high_risk_villages']} high-risk villages, "
                     f"vaccination coverage {round(s['vaccination_coverage'] * 100)}%, "
                     f"{s['pending_lab']} samples in lab")
        for c in dashboard_map("village", db)["clusters"]:
            lines.append(f"Cluster #{c['id']}: {c['suspected']} near {c['center']}, {c['cases_7d']} obs vs "
                         f"{c['expected']} expected, p={c['p_value']}{', ZOONOTIC' if c['zoonotic'] else ''}")
        tasks_ = list_tasks(user, db)
        lines.append(f"Open response tasks: {sum(1 for t in tasks_ if t['status'] != 'DONE')}")
        try:
            f = fc.compare(db, days=7, ring_km=12.0)["summary"]
            lines.append(f"7-day forecast: {f['baseline_cases']} cases with no action vs "
                         f"{f['scenario_cases']} with 12 km ring vaccination ({f['prevented']} prevented, "
                         f"{f['doses_needed']} doses)")
        except Exception:
            pass
    lines.append("Diseases in knowledge base: " + ", ".join(
        f"{k}={d['name']['en']}" for k, d in kb["diseases"].items()))
    lg = user.lang if user.lang in ("hi", "mr", "en") else "hi"
    lines.append("HOME CARE GUIDE (safe, non-prescription — quote from here when a sick animal is described):")
    for k, d in kb["diseases"].items():
        hc = (d.get("home_care") or {}).get(lg) or (d.get("home_care") or {}).get("en")
        if hc:
            lines.append(f"  {d['name']['en']}: {hc}")
    fa = kb.get("symptom_first_aid") or {}
    if fa:
        lines.append("FIRST AID BY SYMPTOM: " + "; ".join(
            f"{k}: {v.get(lg) or v.get('en')}" for k, v in fa.items()))
    return "\n".join(lines)


class ChatIn(BaseModel):
    query: str
    lang: str = "hi"
    page: str = "farmer"
    history: list = []       # [{"role": "user"|"assistant", "text": "..."}]


def _gemini_call(model: str, payload: dict):
    key = _get_gemini_key()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


@app.post("/api/assistant/chat")
def assistant_chat(body: ChatIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    key = _get_gemini_key()
    if not key:
        raise HTTPException(503, "Gemini is not configured (GEMINI_API_KEY missing in .env)")
    lang = body.lang if body.lang in LANG_NAME else "hi"
    page = "gov" if body.page == "gov" else "farmer"
    actions = ('{"type":"tab","tab":"home|report|animals|services|alerts"} | '
               '{"type":"report","species":"cattle|buffalo|goat|sheep|poultry|null","symptoms":[codes]}'
               if page == "farmer" else
               '{"type":"section","section":"overview|forecast|tasks|claims|campaigns|reports"}')
    system = (
        "You are पशु मित्र (Pashu Mitra), the voice assistant inside PashuAarogya, the Government of "
        "Maharashtra's livestock disease early-warning and response platform. "
        f"Reply in {LANG_NAME[lang]}" + (" using Devanagari script" if lang != "en" else "") +
        ", in simple spoken words a village farmer understands, maximum 90 words — it will be read aloud. "
        "Be warm and practical. Never give a definitive diagnosis or drug doses: say signs are 'consistent with' "
        "a disease and route serious cases to the veterinarian / toll-free 1962. Use ONLY the CONTEXT for facts "
        "about this user (animals, camps, claims, weather, clusters); never invent numbers, dates or camps. "
        "When a sick animal is described, ALWAYS answer in this order: (1) 2–4 concrete things the farmer can "
        "do at home RIGHT NOW, taken from the HOME CARE GUIDE / FIRST AID for the matching disease or symptoms "
        "(isolation, shade, water, jaggery-salt or ORS, wound washing with neem/turmeric, fly or tick control, "
        "feed changes, milk not to be sold); (2) when to call the vet / 1962; (3) then say the app will file the "
        "report. Only safe home measures — no antibiotics, injections or doses. "
        "Set action type 'report' with the species and symptom codes you recognised so the app pre-fills the "
        "report. If they ask to see something, set a navigation action. "
        "Output STRICT JSON only: {\"reply\": string, \"action\": null | " + actions + "}. "
        f"Symptom codes: {', '.join(SYMPTOM_CODES)}.\n\nCONTEXT:\n" + _assistant_context(db, user, page))
    contents = []
    for h in body.history[-8:]:
        role = "model" if h.get("role") == "assistant" else "user"
        if h.get("text"):
            contents.append({"role": role, "parts": [{"text": str(h["text"])[:600]}]})
    contents.append({"role": "user", "parts": [{"text": body.query[:600]}]})
    # thinking tokens count against maxOutputTokens on 2.5-series models — a
    # 60-word spoken reply needs no chain-of-thought, so turn it off
    payload = {"system_instruction": {"parts": [{"text": system}]}, "contents": contents,
               "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1500,
                                    "responseMimeType": "application/json",
                                    "thinkingConfig": {"thinkingBudget": 0}}}
    models = ([_GEMINI_OK["model"]] if _GEMINI_OK["model"] else []) + \
             [m for m in GEMINI_MODELS if m != _GEMINI_OK["model"]]
    last_err = None
    for model in models:
        try:
            try:
                res = _gemini_call(model, payload)
            except urllib.error.HTTPError as e:
                body_ = e.read().decode()[:300]
                if e.code == 400 and "thinking" in body_.lower():
                    # model without a thinking budget: retry once without it
                    p2 = json.loads(json.dumps(payload))
                    p2["generationConfig"].pop("thinkingConfig", None)
                    res = _gemini_call(model, p2)
                else:
                    raise urllib.error.HTTPError(e.url, e.code, body_, e.headers, None)
            _GEMINI_OK["model"] = model
            break
        except urllib.error.HTTPError as e:
            msg = e.msg if isinstance(e.msg, str) else str(e)
            last_err = f"{model}: HTTP {e.code} {msg[:200]}"
            if e.code in (404, 400, 429, 500, 502, 503):
                continue
            raise HTTPException(502, last_err)
        except Exception as e:
            last_err = f"{model}: {e}"
            continue
    else:
        raise HTTPException(502, f"Gemini unavailable — {last_err}")
    text = ""
    try:
        text = res["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        pass
    text = text.strip()
    if text.startswith("`"):
        text = text.strip("`").replace("json\n", "", 1)
    try:
        out = json.loads(text)
        reply, action = str(out.get("reply", "")).strip(), out.get("action")
    except Exception:
        import re as _re
        # truncated / malformed JSON: salvage the reply string, drop the action
        m = _re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)', text)
        reply = json.loads('"' + m.group(1) + '"') if m else (text or "…")
        if len(reply) > 700:
            reply = reply[:700].rsplit(" ", 1)[0] + "…"
        action = None
    if isinstance(action, dict) and action.get("type") == "report":
        action["symptoms"] = [s for s in (action.get("symptoms") or []) if s in SYMPTOM_CODES]
        if action.get("species") not in ("cattle", "buffalo", "goat", "sheep", "poultry"):
            action["species"] = None
    audit(db, user.id, "assistant_llm", f"{_GEMINI_OK['model']} q={body.query[:60]}"); db.commit()
    return {"reply": reply, "action": action, "model": _GEMINI_OK["model"], "provider": "Google Gemini"}


# ------------------------------------------------- historical disease trends --
# "which areas, which disease, which animals, which breeds" — the evidence base
# the PS asks for ("integrate ... historical disease trends", "stronger
# evidence-based planning").
def _area_of(db, village_id, level):
    v = db.get(Location, village_id)
    if not v:
        return None
    if level == "village":
        return v
    blk = db.get(Location, v.parent_id) if v.parent_id else None
    if level == "block":
        return blk
    return db.get(Location, blk.parent_id) if blk and blk.parent_id else None


@app.get("/api/history")
def history(months: int = 12, level: str = "block", district: Optional[str] = None,
            disease: Optional[str] = None, species: Optional[str] = None,
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Historical disease records aggregated by area / disease / species / breed."""
    months = max(1, min(36, months))
    since = datetime.utcnow() - timedelta(days=months * 30)
    level = level if level in ("village", "block", "district") else "block"
    kb = intel.load_kb()

    q = db.query(Case).filter(Case.reported_at >= since)
    if species:
        q = q.filter(Case.species == species)
    rows = q.order_by(Case.reported_at.desc()).all()

    def dname(key):
        d = kb["diseases"].get(key or "", {})
        return d.get("name", {}).get("en", key or "Undiagnosed")

    by_area, by_disease, by_species, by_breed, by_month = {}, {}, {}, {}, {}
    detail, confirmed_total, deaths_total = [], 0, 0
    for c in rows:
        key = (c.suspected or "").split(",")[0] if c.suspected else ""
        if disease and key != disease:
            continue
        area = _area_of(db, c.village_id, level)
        dist = _area_of(db, c.village_id, "district")
        if district and (not dist or dist.name != district):
            continue
        aname = area.name if area else "—"
        dn = dname(key)
        mon = c.reported_at.strftime("%Y-%m")
        n = c.affected_count or 1

        a = by_area.setdefault(aname, {"area": aname, "cases": 0, "animals": 0,
                                       "deaths": 0, "diseases": {}, "breeds": {},
                                       "district": dist.name if dist else None})
        a["cases"] += 1; a["animals"] += n; a["deaths"] += c.dead_count or 0
        a["diseases"][dn] = a["diseases"].get(dn, 0) + 1
        if c.breed:
            a["breeds"][c.breed] = a["breeds"].get(c.breed, 0) + 1

        d = by_disease.setdefault(dn, {"disease": dn, "key": key, "cases": 0,
                                       "animals": 0, "deaths": 0, "areas": {},
                                       "species": {}, "breeds": {},
                                       "zoonotic": bool(kb["diseases"].get(key, {}).get("zoonotic"))})
        d["cases"] += 1; d["animals"] += n; d["deaths"] += c.dead_count or 0
        d["areas"][aname] = d["areas"].get(aname, 0) + 1
        d["species"][c.species] = d["species"].get(c.species, 0) + 1
        if c.breed:
            d["breeds"][c.breed] = d["breeds"].get(c.breed, 0) + 1

        s = by_species.setdefault(c.species, {"species": c.species, "cases": 0,
                                              "animals": 0, "deaths": 0, "breeds": {}})
        s["cases"] += 1; s["animals"] += n; s["deaths"] += c.dead_count or 0
        if c.breed:
            s["breeds"][c.breed] = s["breeds"].get(c.breed, 0) + 1
            b = by_breed.setdefault(c.breed, {"breed": c.breed, "species": c.species,
                                              "cases": 0, "animals": 0, "deaths": 0,
                                              "diseases": {}})
            b["cases"] += 1; b["animals"] += n; b["deaths"] += c.dead_count or 0
            b["diseases"][dn] = b["diseases"].get(dn, 0) + 1

        m = by_month.setdefault(mon, {"month": mon, "cases": 0, "deaths": 0, "diseases": {}})
        m["cases"] += 1; m["deaths"] += c.dead_count or 0
        m["diseases"][dn] = m["diseases"].get(dn, 0) + 1

        if c.status == "CONFIRMED":
            confirmed_total += 1
        deaths_total += c.dead_count or 0
        if len(detail) < 300:
            v = db.get(Location, c.village_id)
            detail.append({"id": c.id, "date": c.reported_at.strftime("%Y-%m-%d"),
                           "village": v.name if v else None, "area": aname,
                           "district": dist.name if dist else None,
                           "disease": dn, "species": c.species, "breed": c.breed,
                           "affected": n, "deaths": c.dead_count or 0,
                           "status": c.status, "triage": c.triage_band,
                           "zoonotic": bool(c.zoonotic_flag)})

    def top(d):
        return sorted(d.items(), key=lambda x: -x[1])[:3]

    for a in by_area.values():
        a["top_disease"] = top(a["diseases"])[0][0] if a["diseases"] else "—"
        a["top_breeds"] = [{"breed": k, "cases": v} for k, v in top(a["breeds"])]
    for d in by_disease.values():
        d["top_area"] = top(d["areas"])[0][0] if d["areas"] else "—"
        d["top_breeds"] = [{"breed": k, "cases": v} for k, v in top(d["breeds"])]
        d["species_list"] = [{"species": k, "cases": v} for k, v in top(d["species"])]
    for s in by_species.values():
        s["top_breeds"] = [{"breed": k, "cases": v} for k, v in top(s["breeds"])]
    for b in by_breed.values():
        b["top_disease"] = top(b["diseases"])[0][0] if b["diseases"] else "—"

    districts = sorted({l.name for l in db.query(Location).filter(Location.level == "district")})
    return {
        "months": months, "level": level,
        "filters": {"district": district, "disease": disease, "species": species},
        "options": {"districts": districts,
                    "diseases": [{"key": k, "name": v["name"]["en"]} for k, v in kb["diseases"].items()],
                    "species": ["cattle", "buffalo", "goat", "sheep", "poultry", "pig"]},
        "totals": {"cases": sum(a["cases"] for a in by_area.values()),
                   "animals": sum(a["animals"] for a in by_area.values()),
                   "deaths": deaths_total, "confirmed": confirmed_total,
                   "areas": len(by_area), "diseases": len(by_disease),
                   "breeds": len(by_breed)},
        "by_area": sorted(by_area.values(), key=lambda x: -x["cases"])[:40],
        "by_disease": sorted(by_disease.values(), key=lambda x: -x["cases"]),
        "by_species": sorted(by_species.values(), key=lambda x: -x["cases"]),
        "by_breed": sorted(by_breed.values(), key=lambda x: -x["cases"])[:25],
        "by_month": sorted(by_month.values(), key=lambda x: x["month"]),
        "detail": detail,
    }


@app.get("/api/history/village")
def village_history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Past disease record of the farmer's own village — what hit here before."""
    fm = db.query(Farmer).filter(Farmer.user_id == user.id).first()
    vid = fm.village_id if fm else user.location_id
    if not vid:
        return {"village": None, "years": [], "diseases": []}
    v = db.get(Location, vid)
    kb = intel.load_kb()
    since = datetime.utcnow() - timedelta(days=365 * 3)
    rows = db.query(Case).filter(Case.village_id == vid, Case.reported_at >= since).all()
    dis, seasons = {}, {}
    for c in rows:
        key = (c.suspected or "").split(",")[0] if c.suspected else ""
        d = kb["diseases"].get(key, {})
        nm = d.get("name", {})
        label = nm.get(user.lang or "hi") or nm.get("en") or "—"
        if not key:
            continue
        e = dis.setdefault(key, {"key": key, "name": label, "name_en": nm.get("en", key),
                                 "cases": 0, "deaths": 0, "breeds": {},
                                 "zoonotic": bool(d.get("zoonotic")), "last": None})
        e["cases"] += 1; e["deaths"] += c.dead_count or 0
        if c.breed:
            e["breeds"][c.breed] = e["breeds"].get(c.breed, 0) + 1
        ds = c.reported_at.strftime("%Y-%m-%d")
        if not e["last"] or ds > e["last"]:
            e["last"] = ds
        seasons.setdefault(c.reported_at.month, 0)
        seasons[c.reported_at.month] += 1
    for e in dis.values():
        e["top_breeds"] = [k for k, _ in sorted(e["breeds"].items(), key=lambda x: -x[1])[:2]]
    return {"village": v.name if v else None,
            "diseases": sorted(dis.values(), key=lambda x: -x["cases"])[:8],
            "peak_months": sorted(seasons, key=lambda m: -seasons[m])[:3],
            "total_cases": len(rows)}


# ------------------------------------- animal-level health / vaccination record
@app.get("/api/animals/{animal_id}/health")
def animal_health(animal_id: int, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Complete animal-level health, vaccination and treatment record (PS)."""
    a = db.get(Animal, animal_id)
    if not a:
        raise HTTPException(404, "Animal not found")
    fm = db.query(Farmer).filter(Farmer.user_id == user.id).first()
    if user.role == "farmer" and (not fm or a.farmer_id != fm.id):
        raise HTTPException(403, "Not your animal")
    kb = intel.load_kb()
    lg = user.lang if user.lang in ("hi", "mr", "en") else "hi"

    def dn(key):
        nm = kb["diseases"].get(key or "", {}).get("name", {})
        return nm.get(lg) or nm.get("en") or key

    vaccs = (db.query(Vaccination).filter(Vaccination.animal_id == animal_id)
               .order_by(Vaccination.given_on.desc()).all())
    cases = (db.query(Case).filter(Case.animal_id == animal_id)
               .order_by(Case.reported_at.desc()).all())
    timeline = []
    for v in vaccs:
        timeline.append({"kind": "vaccination", "at": str(v.given_on),
                         "title": dn(v.disease_key), "detail": v.vaccine or "",
                         "extra": f"due {v.due_on}", "campaign": v.campaign})
    for c in cases:
        timeline.append({"kind": "case", "at": c.reported_at.strftime("%Y-%m-%d"),
                         "title": f"#{c.id} " + (dn((c.suspected or '').split(',')[0])
                                                 if c.suspected else "Case"),
                         "detail": c.symptoms or "", "extra": c.status,
                         "band": c.triage_band})
        for tr in db.query(Treatment).filter(Treatment.case_id == c.id).all():
            timeline.append({"kind": "treatment", "at": tr.given_at.strftime("%Y-%m-%d"),
                             "title": tr.diagnosis or "Treatment",
                             "detail": tr.treatment or "",
                             "extra": (f"{tr.withdrawal_days}d withdrawal"
                                       if tr.withdrawal_days else ""),
                             "vet": (db.get(User, tr.vet_id).name if tr.vet_id else None)})
        for s in db.query(Sample).filter(Sample.case_id == c.id).all():
            timeline.append({"kind": "sample", "at": s.collected_at.strftime("%Y-%m-%d"),
                             "title": f"Sample {s.code}",
                             "detail": s.lab_result or s.status,
                             "extra": dn(s.result_disease) if s.result_disease else ""})
    timeline.sort(key=lambda x: x["at"], reverse=True)
    due = []
    for key, d in kb["diseases"].items():
        if a.species not in (d.get("species") or []):
            continue
        last = next((v for v in vaccs if v.disease_key == key), None)
        if not last:
            due.append({"disease": key, "name": dn(key), "status": "never"})
        elif last.due_on and last.due_on <= date.today():
            due.append({"disease": key, "name": dn(key), "status": "overdue",
                        "due_on": str(last.due_on)})
    v = db.get(Location, a.village_id)
    return {"id": a.id, "tag_id": a.tag_id, "species": a.species, "breed": a.breed,
            "sex": a.sex, "age_months": a.age_months,
            "village": v.name if v else None,
            "vaccinations": [{"id": x.id, "disease": x.disease_key, "name": dn(x.disease_key),
                              "vaccine": x.vaccine, "given_on": str(x.given_on),
                              "due_on": str(x.due_on), "campaign": x.campaign} for x in vaccs],
            "cases": [_case_out(db, c) for c in cases[:10]],
            "timeline": timeline[:40], "due": due[:6],
            "withdrawal": _withdrawal_status(db, a.id),
            "permit": _permit_status(db, a.village_id, a.id)}


class VaccIn(BaseModel):
    disease_key: str
    vaccine: str = ""
    given_on: Optional[str] = None
    campaign: str = ""


@app.post("/api/animals/{animal_id}/vaccination")
def add_vaccination(animal_id: int, body: VaccIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Record a vaccination — farmer (own animal), field worker or vet."""
    a = db.get(Animal, animal_id)
    if not a:
        raise HTTPException(404, "Animal not found")
    fm = db.query(Farmer).filter(Farmer.user_id == user.id).first()
    if user.role == "farmer" and (not fm or a.farmer_id != fm.id):
        raise HTTPException(403, "Not your animal")
    given = date.fromisoformat(body.given_on) if body.given_on else date.today()
    v = Vaccination(animal_id=a.id, village_id=a.village_id,
                    disease_key=body.disease_key, vaccine=body.vaccine or "Govt supply",
                    given_on=given, due_on=given + timedelta(days=365),
                    campaign=body.campaign or "Self-reported")
    db.add(v)
    audit(db, user.id, "vaccination_add", f"animal {a.tag_id} {body.disease_key}")
    db.commit()
    return {"id": v.id, "disease": v.disease_key, "given_on": str(v.given_on),
            "due_on": str(v.due_on)}


# ------------------------------------------------- live cross-dashboard sync --
# Every dashboard polls this tiny endpoint; when a counter moves, that dashboard
# refreshes. One officer's action shows up on every other officer's screen.
@app.get("/api/sync/state")
def sync_state(user: User = Depends(current_user), db: Session = Depends(get_db)):
    def last_id(model):
        row = db.query(func.max(model.id)).scalar()
        return int(row or 0)
    counts = {
        "cases": db.query(func.count(Case.id)).scalar() or 0,
        "alerts": db.query(func.count(Alert.id)).scalar() or 0,
        "tasks_open": db.query(func.count(Task.id)).filter(Task.status != "DONE").scalar() or 0,
        "tasks_done": db.query(func.count(Task.id)).filter(Task.status == "DONE").scalar() or 0,
        "claims": db.query(func.count(Claim.id)).scalar() or 0,
        "claims_pending": db.query(func.count(Claim.id))
                            .filter(Claim.status.in_(["FILED", "UNDER_REVIEW"])).scalar() or 0,
        "samples": db.query(func.count(Sample.id)).scalar() or 0,
        "samples_result": db.query(func.count(Sample.id))
                            .filter(Sample.status == "RESULT").scalar() or 0,
        "outbreaks": db.query(func.count(Outbreak.id))
                       .filter(Outbreak.status == "ACTIVE").scalar() or 0,
        "camps": db.query(func.count(Camp.id)).scalar() or 0,
        "vaccinations": db.query(func.count(Vaccination.id)).scalar() or 0,
        "treatments": db.query(func.count(Treatment.id)).scalar() or 0,
        "animals": db.query(func.count(Animal.id)).scalar() or 0,
        # live enrolment: lets every open dashboard show a new farmer within
        # one poll, which is the whole point of registering people on stage
        "registrations": db.query(func.count(AuditLog.id))
                           .filter(AuditLog.action == "register").scalar() or 0,
    }
    # a single version string: any change anywhere flips it
    version = "-".join(str(v) for v in counts.values()) + f"-{last_id(Case)}-{last_id(Alert)}"
    last = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    return {"version": version, "counts": counts,
            "server_time": datetime.utcnow().isoformat(),
            "last_action": ({"action": last.action, "detail": last.detail,
                             "at": last.at.isoformat(),
                             "by": (db.get(User, last.user_id).name
                                    if last.user_id and db.get(User, last.user_id) else None)}
                            if last else None)}


@app.get("/api/db/health")
def db_health(db: Session = Depends(get_db)):
    """Proof the database is persisting: file, size, row counts, last writes."""
    url = str(engine.url)
    path, size = None, None
    if url.startswith("sqlite"):
        path = engine.url.database
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
    tables = {}
    for name, model in (("locations", Location), ("users", User), ("farmers", Farmer),
                        ("animals", Animal), ("cases", Case), ("vaccinations", Vaccination),
                        ("treatments", Treatment), ("samples", Sample),
                        ("outbreaks", Outbreak), ("alerts", Alert), ("claims", Claim),
                        ("tasks", Task), ("camps", Camp), ("risk_scores", RiskScore),
                        ("weather_obs", WeatherObservation), ("audit_log", AuditLog)):
        tables[name] = db.query(func.count(model.id)).scalar() or 0
    recent = (db.query(AuditLog).order_by(AuditLog.id.desc()).limit(8).all())
    return {"engine": url.split("://")[0], "path": path,
            "size_kb": round(size / 1024, 1) if size else None,
            "persistent": bool(path) or not url.startswith("sqlite"),
            "tables": tables, "total_rows": sum(tables.values()),
            "recent_writes": [{"at": r.at.isoformat(), "action": r.action,
                               "detail": r.detail} for r in recent]}


# --------------------------------------------------------------------- demo --
@app.post("/api/demo/advance")
def demo_advance(user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = seeder.advance_outbreak_day(db)
    intel.refresh_all(db)
    audit(db, user.id, "demo_advance", f"+{n} cases"); db.commit()
    return {"new_cases": n}


@app.get("/api/audit")
def audit_log(db: Session = Depends(get_db)):
    rows = db.query(AuditLog).order_by(AuditLog.at.desc()).limit(50).all()
    users = {u.id: u.name for u in db.query(User).all()}
    return [{"at": r.at.isoformat(), "user": users.get(r.user_id, "?"),
             "action": r.action, "detail": r.detail} for r in rows]


# ------------------------------------------------- nearby health centres --
@app.get("/api/health-centres")
def health_centres(village_id: Optional[int] = None, limit: int = 8,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Where a farmer can take the animal, nearest first.

    The PS names distant diagnostic facilities as a pain point, so the farmer
    gets the real ladder -- block dispensary, district polyclinic, district lab
    -- plus the 1962 mobile unit that comes to the door.
    """
    vid = village_id or user.location_id
    v = db.get(Location, vid) if vid else None
    if v is not None and v.level != "village":          # officials sit on a block/district
        child = db.query(Location).filter(Location.parent_id == v.id).first()
        v = child or v
    rows = db.query(HealthCentre).all()
    out = []
    for h in rows:
        d = None
        if v is not None and v.lat is not None and h.lat is not None:
            d = round(intel.haversine_km(v.lat, v.lon, h.lat, h.lon), 1)
        out.append({"id": h.id, "name": h.name, "name_local": h.name_local,
                    "kind": h.kind, "phone": h.phone or "1962",
                    "timings": h.timings, "is_24x7": bool(h.is_24x7),
                    "services": (h.services or "").split(","),
                    "lat": h.lat, "lon": h.lon, "distance_km": d,
                    "maps": f"https://www.google.com/maps/search/?api=1&query={h.lat},{h.lon}"
                            if h.lat is not None else None})
    out.sort(key=lambda r: (r["distance_km"] is None, r["distance_km"] or 0))
    return {"village": v.name if v is not None else None,
            "helpline": "1962", "centres": out[:limit]}


# ------------------------------------------- outbreak awareness for farmers --
@app.get("/api/my/outbreak")
def my_outbreak(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Is the farmer's own village inside a live outbreak zone?

    Every farmer in the zone must be warned, not only the one who reported --
    this is what turns detection into village-wide awareness.
    """
    v = db.get(Location, user.location_id) if user.location_id else None
    if v is None:
        return {"in_zone": False}
    kb = intel.load_kb()
    for ob in db.query(Outbreak).filter(Outbreak.status == "ACTIVE").all():
        try:
            zone = json.loads(ob.zone_village_ids or "[]")
        except ValueError:
            zone = []
        centre = db.get(Location, ob.center_village_id)
        dist = None
        if centre is not None and v.lat is not None and centre.lat is not None:
            dist = round(intel.haversine_km(v.lat, v.lon, centre.lat, centre.lon), 1)
        inside = v.id in zone or (dist is not None and dist <= (ob.radius_km or 0))
        if not inside:
            continue
        d = kb["diseases"].get(ob.suspected, {})
        lang = user.lang or "hi"
        return {
            "in_zone": True, "outbreak_id": ob.id,
            "disease_key": ob.suspected,
            "disease": (d.get("name", {}) or {}).get(lang)
                       or (d.get("name", {}) or {}).get("en") or ob.suspected,
            "zoonotic": bool(ob.zoonotic),
            "centre": centre.name if centre is not None else None,
            "distance_km": dist, "radius_km": ob.radius_km,
            "cases_7d": ob.cases_7d, "detected_at": ob.detected_at.isoformat(),
            "advice": (d.get("action", {}) or {}).get(lang)
                      or (d.get("action", {}) or {}).get("en"),
            "is_my_village": v.id == ob.center_village_id,
        }
    return {"in_zone": False}


# -------------------------------------------- live farmer registration ------
LIVE_TARGET = int(os.environ.get("PASHU_LIVE_TARGET", "20"))


class RegisterIn(BaseModel):
    phone: str
    name: str
    village_id: Optional[int] = None
    lang: str = "hi"


@app.post("/api/auth/register")
def register_farmer(body: RegisterIn, db: Session = Depends(get_db)):
    """Self sign-up for a farmer, so people can be enrolled on the spot.

    Returns a token as well, so registering and signing in is one step at a
    desk or on stage.
    """
    phone = "".join(ch for ch in body.phone if ch.isdigit())[-10:]
    name = (body.name or "").strip()
    if len(phone) != 10:
        raise HTTPException(400, "Enter a 10-digit mobile number")
    if len(name) < 2:
        raise HTTPException(400, "Enter the farmer's name")
    existing = db.query(User).filter(User.phone == phone).first()
    if existing:
        return {"already": True, "token": make_token(existing.id),
                "user": {"id": existing.id, "name": existing.name,
                         "role": existing.role, "lang": existing.lang}}
    v = db.get(Location, body.village_id) if body.village_id else None
    if v is None or v.level != "village":
        v = db.query(Location).filter(Location.level == "village").first()
    u = User(phone=phone, name=name, role="farmer", location_id=v.id,
             lang=body.lang if body.lang in ("hi", "mr", "en") else "hi")
    db.add(u); db.flush()
    db.add(Farmer(user_id=u.id, village_id=v.id))
    audit(db, u.id, "register", f"{name} · {v.name}")
    db.commit()
    return {"already": False, "token": make_token(u.id),
            "user": {"id": u.id, "name": u.name, "role": "farmer",
                     "lang": u.lang, "location": v.name, "location_id": v.id}}


@app.get("/api/live/registrations")
def live_registrations(limit: int = 25, db: Session = Depends(get_db)):
    """The on-stage enrolment wall: who signed up, just now, and from where."""
    rows = (db.query(AuditLog).filter(AuditLog.action == "register")
              .order_by(AuditLog.at.desc()).limit(limit).all())
    recent = []
    for r in rows:
        u = db.get(User, r.user_id)
        if u is None:
            continue
        loc = db.get(Location, u.location_id) if u.location_id else None
        fm = db.query(Farmer).filter(Farmer.user_id == u.id).first()
        n_animals = (db.query(func.count(Animal.id))
                       .filter(Animal.farmer_id == fm.id).scalar() if fm else 0)
        recent.append({"name": u.name, "phone": "••••" + (u.phone or "")[-4:],
                       "village": loc.name if loc else None,
                       "village_local": loc.name_mr if loc else None,
                       "animals": n_animals, "at": r.at.isoformat()})
    total = db.query(func.count(AuditLog.id)).filter(AuditLog.action == "register").scalar() or 0
    return {"count": total, "target": LIVE_TARGET, "recent": recent}


# ----------------------------------------------------------------- frontend --
FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "frontend")
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    # Render / Railway / Fly inject the port to bind. Local default stays 8000.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))

"""Seed data + synthetic outbreak simulator — statewide demo edition.

Five real Maharashtra districts, ~70 villages, and THREE concurrent
disease storylines so every screen is alive on first load:

  1. LSD wave        — Ahmednagar (Shevgaon origin), 10 days in, growing.
                       Vaccination gap in Shevgaon/Pathardi explains it.
  2. FMD cluster     — Jalgaon (Chalisgaon), 6 days in, market-linked.
  3. Anthrax event   — Nashik (Sinnar), 4 days, ZOONOTIC → One Health flag.
  + PPR background in Solapur goats, routine noise statewide.

Pre-seeded workflow artefacts: samples across the whole chain
(COLLECTED→TESTING→RESULT), one lab-confirmed LSD case, treatments,
closed cases — so vet & lab screens are populated before the demo starts.
`advance_outbreak_day()` injects one more day of spread on demand.
"""
import os
import random
from datetime import datetime, date, timedelta

from models import (Location, User, Farmer, Animal, Case, Vaccination,
                    Treatment, Sample, Alert, Claim, Camp, HealthCentre)
from engine import triage, haversine_km

rng = random.Random(2026)

# ---------------------------------------------------------------- geography --
GEO = {
    "Ahmednagar": {"mr": "अहमदनगर", "lat": 19.09, "lon": 74.74, "blocks": {
        "Shevgaon":  {"mr": "शेवगाव",  "lat": 19.35, "lon": 75.23},
        "Pathardi":  {"mr": "पाथर्डी",  "lat": 19.17, "lon": 75.18},
        "Nevasa":    {"mr": "नेवासा",   "lat": 19.55, "lon": 74.93},
        "Rahuri":    {"mr": "राहुरी",   "lat": 19.39, "lon": 74.65},
        "Sangamner": {"mr": "संगमनेर", "lat": 19.57, "lon": 74.21},
    }},
    "Jalgaon": {"mr": "जळगाव", "lat": 21.00, "lon": 75.57, "blocks": {
        "Chalisgaon": {"mr": "चाळीसगाव", "lat": 20.46, "lon": 75.01},
        "Bhusawal":   {"mr": "भुसावळ",   "lat": 21.05, "lon": 75.79},
        "Erandol":    {"mr": "एरंडोल",   "lat": 20.92, "lon": 75.33},
    }},
    "Nashik": {"mr": "नाशिक", "lat": 20.00, "lon": 73.79, "blocks": {
        "Sinnar":   {"mr": "सिन्नर",   "lat": 19.85, "lon": 74.00},
        "Niphad":   {"mr": "निफाड",   "lat": 20.08, "lon": 74.11},
        "Malegaon": {"mr": "मालेगाव", "lat": 20.55, "lon": 74.53},
    }},
    "Pune": {"mr": "पुणे", "lat": 18.52, "lon": 73.86, "blocks": {
        "Junnar":   {"mr": "जुन्नर",   "lat": 19.20, "lon": 73.88},
        "Shirur":   {"mr": "शिरूर",   "lat": 18.83, "lon": 74.37},
        "Baramati": {"mr": "बारामती", "lat": 18.15, "lon": 74.58},
    }},
    "Solapur": {"mr": "सोलापूर", "lat": 17.66, "lon": 75.90, "blocks": {
        "Barshi":      {"mr": "बार्शी",     "lat": 18.23, "lon": 75.69},
        "Pandharpur":  {"mr": "पंढरपूर",  "lat": 17.68, "lon": 75.33},
    }},
}

# ---------------------------------------------------- second region: M.P. ----
# Indore district (Madhya Pradesh). The problem statement is Maharashtra's, so
# Maharashtra stays the primary dataset and keeps every outbreak storyline.
# Indore is seeded alongside it so the team can demo — and register real farmers
# live — in the geography they actually stand in. Set PASHU_REGION=mh to drop it.
#
# Tehsil names and coordinates are real; village names are illustrative and must
# be replaced with LGD-verified names before any real deployment.
GEO_MP = {
    "Indore": {"mr": "इंदौर", "lat": 22.72, "lon": 75.86, "blocks": {
        "Depalpur": {"mr": "देपालपुर", "lat": 22.85, "lon": 75.54},
        "Sanwer":   {"mr": "सांवेर",   "lat": 22.97, "lon": 75.83},
        "Mhow":     {"mr": "महू",      "lat": 22.55, "lon": 75.76},
        "Hatod":    {"mr": "हातोद",    "lat": 22.78, "lon": 75.71},
        "Rau":      {"mr": "राऊ",      "lat": 22.63, "lon": 75.80},
    }},
}

MP_VILLAGE_NAMES = [
    "Betma", "Gautampura", "Kampel", "Harsola", "Palia", "Simrol", "Manpur",
    "Machal", "Kshipra", "Chandravatiganj", "Tillore Khurd", "Rangwasa",
    "Bicholi Mardana", "Arandia", "Jamli", "Nihalpur Mundi", "Ajnod",
    "Bagoda", "Kalaria", "Silotiya",
]

MP_FARMER_NAMES = [
    "Ramesh Patidar", "Mukesh Yadav", "Kailash Chouhan", "Sunita Verma",
    "Dinesh Solanki", "Radheshyam Sharma", "Mangilal Patel", "Sitabai Thakur",
    "Jagdish Rathore", "Pooja Malviya", "Narendra Gurjar", "Shivnarayan Dangi",
    "Anita Bhilala", "Om Prakash Joshi", "Lakhan Sisodiya", "Devilal Mandloi",
]

# Malwa-region breeds — Malvi and Nimari cattle, Bhadawari buffalo and
# Kadaknath poultry are all native to Madhya Pradesh.
BREEDS_MP = {
    "cattle": ["Malvi", "Nimari", "Gir", "Sahiwal", "HF cross"],
    "buffalo": ["Bhadawari", "Murrah", "Nagpuri"],
    "goat": ["Jamunapari", "Barbari", "Sirohi"],
    "sheep": ["Malpura", "Deccani"],
    "poultry": ["Kadaknath", "Desi"],
}

VILLAGE_NAMES = [
    "Amrapur", "Bodhegaon", "Chapadgaon", "Dahigaon", "Erandgaon", "Ghotan",
    "Hingangaon", "Jategaon", "Kharadgaon", "Ladjalgaon", "Malegaon Kh.",
    "Nimbodi", "Palshi", "Ranjani", "Sonai", "Talegaon", "Ukkadgaon",
    "Vambori", "Warkhed", "Yesgaon", "Belapur", "Chincholi", "Deolali",
    "Fattepur", "Gondegaon", "Hiwargaon", "Jambhali", "Kolgaon", "Loni Bk.",
    "Mirajgaon", "Nandur", "Owe", "Pimpalgaon", "Rui", "Shirasgaon",
    "Takli", "Undirgaon", "Vadgaon", "Wakadi", "Yeola Kh.", "Ambegaon",
    "Bhalwani", "Chikhali", "Dhamori", "Ekalahare", "Ghodegaon", "Hivare",
    "Jawala", "Kandhar", "Limbodi", "Mhasrul", "Nagapur", "Ozar",
    "Pargaon", "Rajur", "Sawargaon", "Tandulwadi", "Umbraj", "Velapur",
    "Wadner", "Yenere", "Ashti Kh.", "Borgaon", "Chandgaon", "Daund Kh.",
    "Eklara", "Gunjalwadi", "Hatgaon", "Jamgaon", "Kasari", "Lohgaon",
]

FARMER_NAMES = [
    "Ramesh Pawar", "Suresh Jadhav", "Vithal Shinde", "Bhaskar More",
    "Kailas Gaikwad", "Dattatray Kale", "Sanjay Thorat", "Prakash Deshmukh",
    "Nanda Patil", "Savita Kharat", "Ashok Chavan", "Baban Shelar",
    "Ganesh Wagh", "Popat Kadam", "Shantabai Jagtap", "Uttam Bhosale",
    "Maruti Salunkhe", "Vandana Ghule", "Tukaram Dhole", "Sopan Zende",
    "Lata Nikam", "Eknath Raut", "Chhaya Sable", "Dnyaneshwar Lokhande",
]

SPECIES_MIX = [("cattle", 0.42), ("buffalo", 0.2), ("goat", 0.24),
               ("sheep", 0.09), ("poultry", 0.05)]
BREEDS = {"cattle": ["Gir", "Khillar", "HF cross", "Jersey cross", "Deoni", "Red Kandhari"],
          "buffalo": ["Murrah", "Pandharpuri", "Jaffarabadi", "Nagpuri"],
          "goat": ["Osmanabadi", "Sangamneri", "Boer cross", "Berari"],
          "sheep": ["Deccani", "Madgyal"], "poultry": ["Desi", "Giriraja"]}


def _pick_species():
    r = rng.random(); acc = 0
    for sp, w in SPECIES_MIX:
        acc += w
        if r <= acc:
            return sp
    return "cattle"


def _report_lag_days(when: datetime) -> int:
    """How long the farmer waited before reporting, in the synthetic history.

    Real under-reporting looks like this: before a surveillance channel exists a
    farmer waits for the animal to get worse, and once reporting is easy (and
    pays, through the compensation loop) the wait collapses. Older cases
    therefore carry a 3-7 day lag and recent ones 0-2, so the "reduced reporting
    time" KPI has a real trend to show instead of a flat line.

    This is simulated demo data and must be presented as such.
    """
    age_days = (datetime.utcnow() - when).days
    if age_days > 300:
        return rng.randint(4, 8)
    if age_days > 150:
        return rng.randint(3, 6)
    if age_days > 45:
        return rng.randint(1, 4)
    return rng.randint(0, 2)


def _seed_health_centres(db):
    """The places a farmer can actually go to, on the real institution ladder:
    village/block dispensary -> district polyclinic -> district lab, plus the
    1962 mobile units that come to the door.

    No phone number is invented. Everything routes through 1962, the genuine
    state helpline; `phone` is left for a department to fill from its directory.
    """
    for dist in db.query(Location).filter(Location.level == "district").all():
        db.add(HealthCentre(
            name=f"Veterinary Polyclinic, {dist.name}",
            name_local=f"पशु चिकित्सा पॉलीक्लिनिक, {dist.name_mr or dist.name}",
            kind="polyclinic", block_id=dist.id, lat=dist.lat, lon=dist.lon,
            timings="09:00-17:00", is_24x7=False,
            services="treatment,surgery,referral,vaccination,ai"))
        db.add(HealthCentre(
            name=f"District Disease Investigation Lab, {dist.name}",
            name_local=f"जिला रोग अन्वेषण प्रयोगशाला, {dist.name_mr or dist.name}",
            kind="lab", block_id=dist.id, lat=dist.lat, lon=dist.lon,
            timings="10:00-17:00", services="sample_testing,post_mortem"))
        db.add(HealthCentre(
            name=f"1962 Mobile Veterinary Unit — {dist.name}",
            name_local=f"१९६२ फिरता पशुवैद्यकीय दवाखाना — {dist.name_mr or dist.name}",
            kind="mvu", block_id=dist.id, lat=dist.lat, lon=dist.lon,
            timings="24x7 on call", is_24x7=True,
            services="doorstep_treatment,emergency,sample_collection"))

    for blk in db.query(Location).filter(Location.level == "block").all():
        db.add(HealthCentre(
            name=f"Veterinary Dispensary, {blk.name}",
            name_local=f"पशु चिकित्सालय, {blk.name_mr or blk.name}",
            kind="dispensary", block_id=blk.id, lat=blk.lat, lon=blk.lon,
            timings="09:00-13:00, 14:00-17:00",
            services="treatment,vaccination,deworming,ai"))
    db.flush()


def seed_all(db):
    if db.query(Location).count():
        return False

    lgd = 500000
    villages, by_block = [], {}
    vname = iter(VILLAGE_NAMES * 3)
    for dname, d in GEO.items():
        dist = Location(name=dname, name_mr=d["mr"], level="district",
                        lgd_code=str(lgd := lgd + 1), lat=d["lat"], lon=d["lon"])
        db.add(dist); db.flush()
        for bname, b in d["blocks"].items():
            blk = Location(name=bname, name_mr=b["mr"], level="block",
                           lgd_code=str(lgd := lgd + 1), parent_id=dist.id,
                           lat=b["lat"], lon=b["lon"])
            db.add(blk); db.flush()
            by_block[bname] = []
            for i in range(4 if bname not in ("Shevgaon", "Chalisgaon") else 5):
                v = Location(name=next(vname), level="village",
                             lgd_code=str(lgd := lgd + 1), parent_id=blk.id,
                             lat=b["lat"] + rng.uniform(-0.085, 0.085),
                             lon=b["lon"] + rng.uniform(-0.085, 0.085))
                db.add(v); villages.append(v); by_block[bname].append(v)

    # second region (Indore, M.P.) — same shape, its own village/breed pools
    mp_village_ids = set()
    if os.environ.get("PASHU_REGION", "both").lower() != "mh":
        mp_vname = iter(MP_VILLAGE_NAMES * 2)
        for dname, d in GEO_MP.items():
            dist = Location(name=dname, name_mr=d["mr"], level="district",
                            lgd_code=str(lgd := lgd + 1), lat=d["lat"], lon=d["lon"])
            db.add(dist); db.flush()
            for bname, b in d["blocks"].items():
                blk = Location(name=bname, name_mr=b["mr"], level="block",
                               lgd_code=str(lgd := lgd + 1), parent_id=dist.id,
                               lat=b["lat"], lon=b["lon"])
                db.add(blk); db.flush()
                by_block[bname] = []
                for i in range(4):
                    v = Location(name=next(mp_vname), level="village",
                                 lgd_code=str(lgd := lgd + 1), parent_id=blk.id,
                                 lat=b["lat"] + rng.uniform(-0.07, 0.07),
                                 lon=b["lon"] + rng.uniform(-0.07, 0.07))
                    db.add(v); db.flush()
                    villages.append(v); by_block[bname].append(v)
                    mp_village_ids.add(v.id)
    db.flush()

    # ------------------------------------------------------------- users -----
    home = by_block["Shevgaon"][0]
    ahm = db.query(Location).filter_by(name="Ahmednagar").first()
    demo_users = [
        ("9000000001", "Ramesh Pawar", "farmer", home.id, "hi"),
        ("9000000002", "Sunil Kamble", "field", home.parent_id, "hi"),
        ("9000000003", "Dr. Meera Kulkarni", "vet", home.parent_id, "en"),
        ("9000000004", "Anil Sathe", "lab", None, "en"),
        ("9000000005", "B.V.O. Shevgaon", "block", home.parent_id, "en"),
        ("9000000006", "D.V.O. Ahmednagar", "district", ahm.id, "en"),
        ("9000000007", "State Admin", "state", None, "en"),
    ]
    ind_v = next((v for v in villages if v.id in mp_village_ids), None)
    if ind_v is not None:
        ind_d = db.get(Location, db.get(Location, ind_v.parent_id).parent_id)
        demo_users += [
            ("9000000011", "Ramesh Patidar", "farmer", ind_v.id, "hi"),
            ("9000000012", "D.V.O. Indore", "district", ind_d.id, "en"),
        ]
    for phone, name, role, loc, lang in demo_users:
        db.add(User(phone=phone, name=name, role=role, location_id=loc, lang=lang))
    db.flush()
    demo_farmer_user = db.query(User).filter_by(phone="9000000001").first()

    # ------------------------------------------------- farmers & animals -----
    tag_seq = 100000000001
    for idx, v in enumerate(villages):
        for j in range(rng.randint(2, 4)):
            if idx == 0 and j == 0:
                u = demo_farmer_user
            else:
                names = MP_FARMER_NAMES if v.id in mp_village_ids else FARMER_NAMES
                u = User(phone=f"98{rng.randint(10000000, 99999999)}",
                         name=rng.choice(names), role="farmer",
                         location_id=v.id, lang="hi")
                db.add(u); db.flush()
            fm = Farmer(user_id=u.id, village_id=v.id)
            db.add(fm); db.flush()
            for _ in range(rng.randint(2, 6)):
                sp = _pick_species()
                breeds = BREEDS_MP if v.id in mp_village_ids else BREEDS
                db.add(Animal(tag_id=f"IN{tag_seq}", species=sp,
                              breed=rng.choice(breeds[sp]),
                              sex=rng.choice(["F", "F", "F", "M"]),
                              age_months=rng.randint(8, 110),
                              farmer_id=fm.id, village_id=v.id))
                tag_seq += 1
    db.flush()

    # ------------------------------------------------------ vaccinations -----
    today = date.today()
    LOW_COV = {"Shevgaon": 0.34, "Pathardi": 0.38, "Chalisgaon": 0.46}
    for v in villages:
        blk = db.get(Location, v.parent_id)
        cov = LOW_COV.get(blk.name, rng.uniform(0.62, 0.92))
        for a in db.query(Animal).filter(Animal.village_id == v.id).all():
            if rng.random() < cov:
                given = today - timedelta(days=rng.randint(25, 330))
                db.add(Vaccination(animal_id=a.id, village_id=v.id,
                                   disease_key=rng.choice(["fmd", "lsd", "hs", "ppr"]),
                                   vaccine="Govt campaign",
                                   given_on=given, due_on=given + timedelta(days=365),
                                   campaign="LHDCP 2026"))
    db.flush()

    # -------------------------------------------- veterinary institutions ----
    _seed_health_centres(db)

    # ------------------------------------------------------- storylines ------
    now = datetime.utcnow()
    _historical_backfill(db, by_block, months=24)
    _background_noise(db, villages, days=28)

    # 1. LSD wave in Ahmednagar — 10 days, biggest story
    for day in range(10):
        _wave_day(db, by_block["Shevgaon"] + by_block["Pathardi"] +
                  by_block["Nevasa"] + by_block["Rahuri"],
                  origin=by_block["Shevgaon"][0], day=day,
                  when=now - timedelta(days=10 - day),
                  syndromes=["fever", "nodules", "low_milk", "anorexia"],
                  species=["cattle", "cattle", "buffalo"], horizon_km=28,
                  growth=0.13, base=0.16, death_after=5, death_p=0.12,
                  key_sym="nodules")

    # 2. FMD cluster in Jalgaon (Chalisgaon) — 6 days, market-linked
    for day in range(6):
        _wave_day(db, by_block["Chalisgaon"] + by_block["Erandol"],
                  origin=by_block["Chalisgaon"][0], day=day,
                  when=now - timedelta(days=6 - day),
                  syndromes=["oral_lesions", "hoof_lesions", "salivation",
                             "fever", "lameness"],
                  species=["cattle", "buffalo", "cattle"], horizon_km=20,
                  growth=0.15, base=0.2, death_after=99, death_p=0,
                  key_sym="oral_lesions")

    # 3. Anthrax — Nashik (Sinnar): 6 sudden-death cases in 2 NEARBY villages
    sinnar = by_block["Sinnar"]
    origin = sinnar[0]
    nearest = min(sinnar[1:], key=lambda w: haversine_km(origin.lat, origin.lon,
                                                         w.lat, w.lon))
    pair = [origin, nearest]
    for i in range(6):
        v = pair[i % 2]
        when = now - timedelta(days=rng.uniform(0.3, 4), hours=rng.randint(0, 8))
        _mk_case(db, v, "cattle", ["sudden_death", "bloat", "fever"][:rng.randint(2, 3)],
                 dead=1, when=when, channel=rng.choice(["field", "ivr", "app"]))

    # 4. PPR whisper in Solapur goats (below cluster threshold — background)
    for i in range(3):
        v = rng.choice(by_block["Barshi"] + by_block["Pandharpur"])
        _mk_case(db, v, "goat", ["diarrhoea", "fever", "oral_lesions"], 0,
                 now - timedelta(days=rng.uniform(1, 6)))

    db.flush()

    # ------------------------------------- pre-seeded workflow artefacts -----
    vet = db.query(User).filter_by(role="vet").first()
    lab = db.query(User).filter_by(role="lab").first()
    lsd_cases = (db.query(Case).filter(Case.suspected.like("lsd%"))
                   .order_by(Case.reported_at).limit(8).all())
    stages = ["RESULT", "TESTING", "RECEIVED", "DISPATCHED", "COLLECTED"]
    for i, c in enumerate(lsd_cases[:5]):
        code = f"MH-{c.id:04d}-{rng.randint(1000, 9999)}"
        st = stages[i]
        s = Sample(code=code, case_id=c.id, collected_by=vet.id,
                   collected_at=c.reported_at + timedelta(hours=rng.randint(4, 20)),
                   status=st)
        if st == "RESULT":
            s.lab_result, s.result_disease = "positive", "lsd"
            s.result_at = s.collected_at + timedelta(hours=30)
            c.status = "CONFIRMED"
            vv = db.get(Location, c.village_id)
            for role in ("block", "district"):
                db.add(Alert(kind="outbreak", severity="high",
                             title=f"LAB-CONFIRMED Lumpy Skin Disease in {vv.name}",
                             body=f"Sample {code} positive (ELISA). Containment active: "
                                  f"movement control + ring vaccination of 3-km zone.",
                             village_id=c.village_id, target_role=role))
        else:
            c.status = "SAMPLE_COLLECTED"
        db.add(s)
    # a treated + closed pair for history
    for c in lsd_cases[5:7]:
        # link the case to one of the farmer's animals so the health passport
        # shows a real treatment + milk-withdrawal countdown
        if c.farmer_id and not c.animal_id:
            an = db.query(Animal).filter(Animal.farmer_id == c.farmer_id).first()
            if an:
                c.animal_id = an.id
        db.add(Treatment(case_id=c.id, vet_id=vet.id,
                         diagnosis="LSD — clinical", treatment="Supportive: NSAID, "
                         "oxytetracycline LA, antiseptic dressing, fly control advised",
                         withdrawal_days=5,
                         given_at=datetime.utcnow() - timedelta(days=1)))
        c.status = "TREATMENT" if c is lsd_cases[5] else "CLOSED"
    # demo farmer: give him one treated animal too (passport demo)
    demo_fm = db.query(Farmer).filter(Farmer.user_id == demo_farmer_user.id).first()
    if demo_fm:
        my_case = (db.query(Case).filter(Case.farmer_id == demo_fm.id)
                     .order_by(Case.reported_at.desc()).first())
        my_animal = db.query(Animal).filter(Animal.farmer_id == demo_fm.id).first()
        if my_case and my_animal:
            my_case.animal_id = my_animal.id
            my_case.status = "TREATMENT"
            db.add(Treatment(case_id=my_case.id, vet_id=vet.id,
                             diagnosis="Suspected LSD — clinical",
                             treatment="Oxytetracycline LA + meloxicam; isolate; fly control",
                             withdrawal_days=7,
                             given_at=datetime.utcnow() - timedelta(days=2)))

    # -------------------------------------------------- claims (the loop) ---
    # Farmer with a death files a claim; three stages visible on first load
    demo_fm = db.query(Farmer).filter(Farmer.user_id == demo_farmer_user.id).first()
    death_cases = (db.query(Case).filter(Case.dead_count > 0)
                     .order_by(Case.reported_at).limit(4).all())
    statuses = ["APPROVED", "UNDER_REVIEW", "FILED"]
    for i, dc in enumerate(death_cases[:3]):
        if i == 2 and demo_fm:               # make the newest claim the demo farmer's
            dc.farmer_id = demo_fm.id
        amt = {"cattle": 37500, "buffalo": 37500, "goat": 4000,
               "sheep": 4000}.get(dc.species, 4000)
        cl = Claim(case_id=dc.id, farmer_id=dc.farmer_id, species=dc.species,
                   amount=amt, status=statuses[i],
                   filed_at=dc.reported_at + timedelta(hours=6))
        if statuses[i] == "APPROVED":
            cl.decided_at = cl.filed_at + timedelta(days=1)
            cl.note = "Verified against case record + para-vet confirmation"
        db.add(cl)

    # ---------------------------------------------------- camps upcoming ----
    home_v = db.get(Location, demo_fm.village_id) if demo_fm else None
    if home_v:
        db.add(Camp(village_id=home_v.id, disease_key="lsd",
                    camp_date=today + timedelta(days=3),
                    name=f"LSD ring-vaccination camp — {home_v.name}"))
        sib = [x for x in db.query(Location)
               .filter(Location.parent_id == home_v.parent_id).all()
               if x.id != home_v.id]
        if sib:
            db.add(Camp(village_id=sib[0].id, disease_key="fmd",
                        camp_date=today + timedelta(days=6),
                        name=f"FMD booster camp — {sib[0].name}"))
    ch = db.query(Location).filter_by(name="Chalisgaon", level="block").first()
    if ch and ch.children:
        db.add(Camp(village_id=ch.children[0].id, disease_key="fmd",
                    camp_date=today + timedelta(days=2),
                    name=f"FMD emergency camp — {ch.children[0].name}"))

    db.add(Alert(kind="vaccination", severity="medium",
                 title="LHDCP round due: FMD booster (Q3)",
                 body="Coverage gaps: Shevgaon 34%, Pathardi 38%, Chalisgaon 46%. "
                      "Ring-vaccination teams should prioritise these blocks this week.",
                 target_role="district"))
    db.add(Alert(kind="advisory", severity="medium",
                 title="Monsoon vector surge — statewide",
                 body="High humidity favours LSD vectors. Advise farmers: fly control, "
                      "neem-smoke in sheds, isolate any animal with skin nodules.",
                 target_role="block"))
    db.commit()
    return True


# ------------------------------------------------------------- simulator ----
NOISE = [
    ("cattle", ["itching"], 0), ("goat", ["diarrhoea", "anorexia"], 0),
    ("cattle", ["lameness"], 0), ("buffalo", ["low_milk", "anorexia"], 0),
    ("sheep", ["cough", "nasal_discharge"], 0), ("cattle", ["bloat"], 0),
    ("goat", ["itching"], 0), ("buffalo", ["anorexia"], 0),
]


def _mk_case(db, village, species, symptoms, dead, when, channel=None):
    t = triage(species, symptoms, dead_count=dead, month=when.month)
    fm = db.query(Farmer).filter(Farmer.village_id == village.id).first()
    # attach a real breed from this village's stock so historical trends can
    # answer "which breeds were affected"
    breed = None
    herd = (db.query(Animal)
              .filter(Animal.village_id == village.id, Animal.species == species)
              .all())
    if herd:
        breed = rng.choice(herd).breed
    elif species in BREEDS:
        breed = rng.choice(BREEDS[species])
    c = Case(village_id=village.id, farmer_id=fm.id if fm else None,
             species=species, breed=breed, symptoms=",".join(symptoms),
             affected_count=rng.randint(1, 4), dead_count=dead,
             onset_date=(when - timedelta(days=_report_lag_days(when))).date(),
             reported_at=when,
             channel=channel or rng.choice(["app", "app", "field", "ivr", "sms"]),
             lat=village.lat + rng.uniform(-0.012, 0.012),
             lon=village.lon + rng.uniform(-0.012, 0.012),
             triage_band=t["band"], triage_score=t["score"],
             suspected=t["suspected"], zoonotic_flag=t["zoonotic"],
             status="TRIAGED")
    db.add(c)
    return c


def _historical_backfill(db, by_block, months=24):
    """Two years of seasonal disease history so 'historical disease trends' is
    real data, not a stub: monsoon LSD, winter FMD, summer anthrax, PPR in the
    kidding season — each in the blocks where that disease actually recurs."""
    now = datetime.utcnow()
    # (disease signs, species, peak months, blocks, cases per peak month, death rate)
    WAVES = [
        (["nodules", "fever", "low_milk"], ["cattle", "buffalo"], [7, 8, 9],
         ["Shevgaon", "Pathardi", "Nevasa", "Rahuri", "Malegaon"], 9, 0.10),
        (["oral_lesions", "hoof_lesions", "salivation", "fever"], ["cattle", "buffalo"],
         [12, 1, 2], ["Chalisgaon", "Erandol", "Bhusawal", "Shirur"], 8, 0.04),
        (["swelling", "fever", "sudden_death"], ["cattle", "buffalo"], [6, 7, 8],
         ["Sinnar", "Niphad", "Junnar"], 4, 0.30),
        (["diarrhoea", "fever", "oral_lesions", "nasal_discharge"], ["goat", "sheep"],
         [3, 4, 5], ["Barshi", "Pandharpur", "Baramati"], 6, 0.12),
        (["lameness", "swelling", "fever"], ["cattle"], [6, 7],
         ["Sangamner", "Rahuri", "Niphad"], 3, 0.22),
        (["sudden_death", "bloat"], ["cattle", "goat"], [4, 5],
         ["Sinnar", "Barshi"], 2, 0.55),
    ]
    for m in range(months, 0, -1):
        when = now - timedelta(days=m * 30)
        for signs, species, peak, blocks, base, death_p in WAVES:
            season = 1.0 if when.month in peak else 0.12
            for bname in blocks:
                pool = by_block.get(bname) or []
                if not pool:
                    continue
                n = int(rng.gauss(base * season, max(1, base * season * 0.4)))
                for _ in range(max(0, n)):
                    v = rng.choice(pool)
                    syms = rng.sample(signs, k=min(len(signs), rng.randint(2, 3)))
                    dead = 1 if rng.random() < death_p else 0
                    _mk_case(db, v, rng.choice(species), syms, dead,
                             when + timedelta(days=rng.randint(0, 27),
                                              hours=rng.randint(0, 23)))
    db.flush()


def _background_noise(db, villages, days=28):
    now = datetime.utcnow()
    for d in range(days, 0, -1):
        for _ in range(rng.randint(2, 5)):
            v = rng.choice(villages)
            sp, sym, dead = rng.choice(NOISE)
            _mk_case(db, v, sp, sym, dead,
                     now - timedelta(days=d, hours=rng.randint(0, 20)))


def _wave_day(db, zone_villages, origin, day, when, syndromes, species,
              horizon_km, growth, base, death_after, death_p, key_sym):
    """Epidemic wave: distance-decayed transmission + ~40% under-reporting."""
    intensity = min(1.0, base + day * growth)
    for v in zone_villages:
        dist = haversine_km(origin.lat, origin.lon, v.lat, v.lon)
        p = intensity * max(0.0, 1.0 - dist / horizon_km)
        n = rng.randint(1, 3 if dist < 10 else 2) if rng.random() < p else 0
        for _ in range(n):
            if rng.random() < 0.4:          # under-reporting
                continue
            dead = 1 if (day > death_after and rng.random() < death_p) else 0
            syms = rng.sample(syndromes, k=min(len(syndromes), rng.randint(2, 4)))
            if key_sym not in syms:
                syms.append(key_sym)
            _mk_case(db, v, rng.choice(species), syms, dead,
                     when + timedelta(hours=rng.randint(0, 20)))


_counter = {"n": 0}


def advance_outbreak_day(db):
    """Demo control: one more day of LSD + FMD spread 'today'."""
    _counter["n"] += 1
    day_lsd = min(15, 10 + _counter["n"])
    day_fmd = min(12, 6 + _counter["n"])
    now = datetime.utcnow() - timedelta(hours=2)
    n0 = db.query(Case).count()

    def block_villages(bname):
        blk = db.query(Location).filter_by(name=bname, level="block").first()
        return [c for c in blk.children if c.level == "village"]

    lsd_zone = sum((block_villages(b) for b in
                    ("Shevgaon", "Pathardi", "Nevasa", "Rahuri")), [])
    _wave_day(db, lsd_zone, origin=lsd_zone[0], day=day_lsd, when=now,
              syndromes=["fever", "nodules", "low_milk", "anorexia"],
              species=["cattle", "cattle", "buffalo"], horizon_km=32,
              growth=0.13, base=0.16, death_after=5, death_p=0.14,
              key_sym="nodules")
    fmd_zone = block_villages("Chalisgaon") + block_villages("Erandol")
    _wave_day(db, fmd_zone, origin=fmd_zone[0], day=day_fmd, when=now,
              syndromes=["oral_lesions", "hoof_lesions", "salivation", "fever"],
              species=["cattle", "buffalo"], horizon_km=24,
              growth=0.15, base=0.2, death_after=99, death_p=0,
              key_sym="oral_lesions")
    db.commit()
    return db.query(Case).count() - n0


# ---------------------------------------------------------------- top-up ----
def seed_topup(db):
    """Additively bring an ALREADY-seeded database up to date.

    `seed_all` bails out the moment it sees a Location, which is right — it must
    never re-seed over live records. But a database seeded before a feature
    existed then never gains it, and a cloud deployment cannot simply be wiped
    because farmers have filed real reports into it.

    So each block below adds one missing thing and is safe to run on every boot:
    it checks first, writes only what is absent, and touches nothing that exists.
    """
    added = []

    # veterinary institutions — the farmer's "where do I take this animal?"
    if db.query(HealthCentre).count() == 0 and db.query(Location).count():
        _seed_health_centres(db)
        added.append("health centres")

    # second region (Indore, M.P.)
    if (os.environ.get("PASHU_REGION", "both").lower() != "mh"
            and not db.query(Location).filter(Location.name == "Indore").first()
            and db.query(Location).count()):
        n = _add_mp_region(db)
        added.append(f"Indore region ({n} villages)")

    if added:
        db.commit()
    return added


def _add_mp_region(db):
    """Create the Indore district tree, then populate it like any other region.

    Kept separate from seed_all so it can run against a database that already
    holds Maharashtra data and live farmer reports.
    """
    # continue the LGD sequence rather than colliding with existing codes
    try:
        top = max(int(c[0]) for c in db.query(Location.lgd_code).all()
                  if c[0] and str(c[0]).isdigit())
    except ValueError:
        top = 500000
    lgd = top

    new_villages = []
    mp_vname = iter(MP_VILLAGE_NAMES * 2)
    for dname, d in GEO_MP.items():
        dist = Location(name=dname, name_mr=d["mr"], level="district",
                        lgd_code=str(lgd := lgd + 1), lat=d["lat"], lon=d["lon"])
        db.add(dist); db.flush()
        for bname, b in d["blocks"].items():
            blk = Location(name=bname, name_mr=b["mr"], level="block",
                           lgd_code=str(lgd := lgd + 1), parent_id=dist.id,
                           lat=b["lat"], lon=b["lon"])
            db.add(blk); db.flush()
            for _ in range(4):
                v = Location(name=next(mp_vname), level="village",
                             lgd_code=str(lgd := lgd + 1), parent_id=blk.id,
                             lat=b["lat"] + rng.uniform(-0.07, 0.07),
                             lon=b["lon"] + rng.uniform(-0.07, 0.07))
                db.add(v); db.flush()
                new_villages.append(v)
            # the block dispensary for the new block
            db.add(HealthCentre(
                name=f"Veterinary Dispensary, {blk.name}",
                name_local=f"पशु चिकित्सालय, {blk.name_mr or blk.name}",
                kind="dispensary", block_id=blk.id, lat=blk.lat, lon=blk.lon,
                timings="09:00-13:00, 14:00-17:00",
                services="treatment,vaccination,deworming,ai"))
        # district-level institutions
        db.add(HealthCentre(
            name=f"Veterinary Polyclinic, {dist.name}",
            name_local=f"पशु चिकित्सा पॉलीक्लिनिक, {dist.name_mr or dist.name}",
            kind="polyclinic", block_id=dist.id, lat=dist.lat, lon=dist.lon,
            timings="09:00-17:00", services="treatment,surgery,referral,vaccination,ai"))
        db.add(HealthCentre(
            name=f"District Disease Investigation Lab, {dist.name}",
            name_local=f"जिला रोग अन्वेषण प्रयोगशाला, {dist.name_mr or dist.name}",
            kind="lab", block_id=dist.id, lat=dist.lat, lon=dist.lon,
            timings="10:00-17:00", services="sample_testing,post_mortem"))
        db.add(HealthCentre(
            name=f"1962 Mobile Veterinary Unit — {dist.name}",
            name_local=f"१९६२ फिरता पशुवैद्यकीय दवाखाना — {dist.name_mr or dist.name}",
            kind="mvu", block_id=dist.id, lat=dist.lat, lon=dist.lon,
            timings="24x7 on call", is_24x7=True,
            services="doorstep_treatment,emergency,sample_collection"))
    db.flush()

    # farmers, animals and vaccination history for the new villages only
    tag_seq = 900000000001
    today = date.today()
    for v in new_villages:
        for _ in range(rng.randint(2, 4)):
            u = User(phone=f"97{rng.randint(10000000, 99999999)}",
                     name=rng.choice(MP_FARMER_NAMES), role="farmer",
                     location_id=v.id, lang="hi")
            db.add(u); db.flush()
            fm = Farmer(user_id=u.id, village_id=v.id)
            db.add(fm); db.flush()
            for _ in range(rng.randint(2, 6)):
                sp = _pick_species()
                a = Animal(tag_id=f"IN{tag_seq}", species=sp,
                           breed=rng.choice(BREEDS_MP[sp]),
                           sex=rng.choice(["F", "F", "F", "M"]),
                           age_months=rng.randint(8, 110),
                           farmer_id=fm.id, village_id=v.id)
                db.add(a); db.flush()
                tag_seq += 1
                if rng.random() < rng.uniform(0.55, 0.9):
                    given = today - timedelta(days=rng.randint(25, 330))
                    db.add(Vaccination(animal_id=a.id, village_id=v.id,
                                       disease_key=rng.choice(["fmd", "lsd", "hs", "ppr"]),
                                       vaccine="Govt campaign", given_on=given,
                                       due_on=given + timedelta(days=365),
                                       campaign="LHDCP 2026"))
    # a demo login that lands in Indore
    if new_villages and not db.query(User).filter(User.phone == "9000000011").first():
        db.add(User(phone="9000000011", name="Ramesh Patidar", role="farmer",
                    location_id=new_villages[0].id, lang="hi"))
        db.flush()
        u = db.query(User).filter(User.phone == "9000000011").first()
        db.add(Farmer(user_id=u.id, village_id=new_villages[0].id))
    ind = db.query(Location).filter(Location.name == "Indore",
                                    Location.level == "district").first()
    if ind and not db.query(User).filter(User.phone == "9000000012").first():
        db.add(User(phone="9000000012", name="D.V.O. Indore", role="district",
                    location_id=ind.id, lang="en"))
    db.flush()
    return len(new_villages)

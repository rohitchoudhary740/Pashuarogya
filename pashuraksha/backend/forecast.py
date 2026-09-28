"""Spread forecast + what-if intervention planner.

A deliberately transparent SEIR-lite model on the village graph:

  * State per village: S (susceptible = unvaccinated animals), I (currently
    infectious ~ cases reported in the last 7 days), R (removed).
  * Force of infection on village v = beta * sum_w K(d_vw) * I_w / N_w,
    with a distance kernel K(d) = exp(-d / KERNEL_KM) cut at MAX_KM.
  * Daily new infections = S_v * (1 - exp(-lambda_v)); infectious animals
    are removed at rate GAMMA per day.
  * Scenario: ring vaccination within `ring_km` of each active outbreak
    centre removes VACC_EFFECT of the susceptibles after a LAG_DAYS
    immunity lag.

It is a planning aid, not a prediction: the point is the *difference*
between "do nothing" and "ring-vaccinate now", shown as cases prevented.
Parameters are documented so a veterinary epidemiologist can tune them.
"""
import json
import math
from datetime import datetime, timedelta

from models import Location, Animal, Vaccination, Outbreak
from engine import haversine_km, _village_case_counts, WINDOW_DAYS

BETA = 0.42          # transmission intensity per day (LSD-like, vector season)
GAMMA = 0.14         # removal rate (recovery/death) per day
KERNEL_KM = 8.0      # spatial contact kernel scale
MAX_KM = 35.0        # ignore villages further than this
VACC_EFFECT = 0.75   # share of susceptibles protected by ring vaccination
LAG_DAYS = 2         # days before vaccine immunity counts
BASE_ATTACK = 0.06   # share of unvaccinated herd a village's own reported
                     # cases imply as currently infectious (under-reporting)


def _coverage(db, vid, animal_ids):
    if not animal_ids:
        return 0.0
    vacc = (db.query(Vaccination.animal_id)
              .filter(Vaccination.animal_id.in_(animal_ids)).distinct().count())
    return vacc / len(animal_ids)


def run(db, days: int = 7, ring_km: float = 0.0, outbreak_id: int | None = None,
        now: datetime | None = None):
    now = now or datetime.utcnow()
    villages = db.query(Location).filter(Location.level == "village").all()
    recent = _village_case_counts(db, now - timedelta(days=WINDOW_DAYS), now)

    q = db.query(Outbreak).filter(Outbreak.status == "ACTIVE")
    if outbreak_id:
        q = q.filter(Outbreak.id == outbreak_id)
    outbreaks = q.all()
    centers = []
    for ob in outbreaks:
        c = db.get(Location, ob.center_village_id)
        if c:
            centers.append({"id": ob.id, "name": c.name, "lat": c.lat, "lon": c.lon,
                            "suspected": ob.suspected})

    # per-village population + susceptibles
    animals = db.query(Animal.village_id, Animal.id).all()
    by_v = {}
    for vid, aid in animals:
        by_v.setdefault(vid, []).append(aid)

    idx = {v.id: i for i, v in enumerate(villages)}
    n = len(villages)
    N = [max(1, len(by_v.get(v.id, []))) for v in villages]
    cov = [_coverage(db, v.id, by_v.get(v.id, [])) for v in villages]
    I0 = [min(N[i], recent.get(v.id, 0) * (1 + BASE_ATTACK * N[i]) / 3.0)
          for i, v in enumerate(villages)]
    S0 = [max(0.0, N[i] * (1 - cov[i]) - I0[i]) for i in range(n)]

    # kernel matrix (small n → fine)
    K = [[0.0] * n for _ in range(n)]
    for i, a in enumerate(villages):
        for j, b in enumerate(villages):
            d = 0.0 if i == j else haversine_km(a.lat, a.lon, b.lat, b.lon)
            if d <= MAX_KM:
                K[i][j] = math.exp(-d / KERNEL_KM)

    # ring-vaccination mask
    ring = [False] * n
    if ring_km > 0:
        for i, v in enumerate(villages):
            for c in centers:
                if haversine_km(v.lat, v.lon, c["lat"], c["lon"]) <= ring_km:
                    ring[i] = True
                    break

    S, I = S0[:], I0[:]
    out_days, cum = [], 0.0
    cum_v = [0.0] * n
    for day in range(1, days + 1):
        if ring_km > 0 and day == LAG_DAYS + 1:
            S = [s * (1 - VACC_EFFECT) if ring[i] else s for i, s in enumerate(S)]
        new = [0.0] * n
        for i in range(n):
            lam = BETA * sum(K[i][j] * I[j] / N[j] for j in range(n) if I[j] > 0)
            new[i] = S[i] * (1 - math.exp(-lam))
        for i in range(n):
            S[i] -= new[i]
            I[i] = I[i] * (1 - GAMMA) + new[i]
            cum_v[i] += new[i]
        total = sum(new)
        cum += total
        out_days.append({
            "day": day,
            "date": (now + timedelta(days=day)).date().isoformat(),
            "total_new": round(total, 1),
            "cum": round(cum, 1),
            "village_cum": {villages[i].id: round(cum_v[i], 1)
                            for i in range(n) if cum_v[i] >= 0.05},
        })

    return {
        "days": out_days,
        "total": round(cum, 1),
        "villages": [{"id": v.id, "name": v.name, "lat": v.lat, "lon": v.lon,
                      "animals": N[i], "coverage": round(cov[i], 2),
                      "in_ring": ring[i]} for i, v in enumerate(villages)],
        "centers": centers,
        "ring_km": ring_km,
        "params": {"beta": BETA, "gamma": GAMMA, "kernel_km": KERNEL_KM,
                   "vacc_effect": VACC_EFFECT, "lag_days": LAG_DAYS},
    }


def compare(db, days: int = 7, ring_km: float = 12.0, outbreak_id: int | None = None):
    base = run(db, days, 0.0, outbreak_id)
    scen = run(db, days, ring_km, outbreak_id)
    prevented = max(0.0, base["total"] - scen["total"])
    pct = round(prevented / base["total"] * 100) if base["total"] > 0 else 0
    ring_villages = sum(1 for v in scen["villages"] if v["in_ring"])
    return {"baseline": base, "scenario": scen,
            "summary": {"days": days, "ring_km": ring_km,
                        "baseline_cases": base["total"],
                        "scenario_cases": scen["total"],
                        "prevented": round(prevented, 1), "prevented_pct": pct,
                        "ring_villages": ring_villages,
                        "doses_needed": sum(v["animals"] for v in scen["villages"]
                                            if v["in_ring"])}}

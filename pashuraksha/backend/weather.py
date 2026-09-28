"""Open-Meteo integration (free, keyless). Graceful fallback: if the network is
unavailable the risk engine simply drops the weather signal — the platform must
never depend on an external API to function (offline-first principle)."""
import time
import urllib.request, urllib.parse, json
from datetime import datetime

from models import Location, WeatherObservation

_cache: dict[int, tuple[float, dict]] = {}
TTL = 1800  # 30 min


def fetch_weather(lat: float, lon: float):
    url = ("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": round(lat, 3), "longitude": round(lon, 3),
        "current": "temperature_2m,relative_humidity_2m,precipitation",
        "timezone": "Asia/Kolkata",
    }))
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            data = json.loads(r.read().decode())
        cur = data.get("current", {})
        return {"temp_c": cur.get("temperature_2m"),
                "humidity": cur.get("relative_humidity_2m"),
                "rain_mm": cur.get("precipitation")}
    except Exception:
        return None


def refresh_village_weather(db, village: Location):
    now = time.time()
    hit = _cache.get(village.id)
    if hit and now - hit[0] < TTL:
        return hit[1]
    w = fetch_weather(village.lat, village.lon)
    if w and w["temp_c"] is not None:
        db.add(WeatherObservation(village_id=village.id,
                                  observed_at=datetime.utcnow(),
                                  temp_c=w["temp_c"], humidity=w["humidity"],
                                  rain_mm=w["rain_mm"]))
        db.commit()
        _cache[village.id] = (now, w)
    return w


def refresh_district_sample(db):
    """Fetch weather for one representative village per block (keeps API calls
    tiny) and copy the observation to sibling villages."""
    blocks = db.query(Location).filter(Location.level == "block").all()
    results = {}
    for b in blocks:
        vills = [c for c in b.children if c.level == "village"]
        if not vills:
            continue
        w = refresh_village_weather(db, vills[0])
        if w and w.get("temp_c") is not None:
            for v in vills[1:]:
                db.add(WeatherObservation(village_id=v.id,
                                          temp_c=w["temp_c"],
                                          humidity=w["humidity"],
                                          rain_mm=w["rain_mm"]))
            results[b.name] = w
    db.commit()
    return results

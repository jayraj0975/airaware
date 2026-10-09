"""API smoke test on the committed data, with the network calls stubbed out."""

import os

import pandas as pd
import pytest
from fastapi.testclient import TestClient

os.environ["AIRAWARE_REFRESH"] = "0"

from airaware import live, web  # noqa: E402


@pytest.fixture(scope="module")
def client():
    weather = {"current": {"time": "2026-10-09T21:00", "temperature_2m": 27.0, "relative_humidity_2m": 50, "apparent_temperature": 28.0,
                           "precipitation": 0, "weather_code": 0, "wind_speed_10m": 4.0, "wind_direction_10m": 270, "surface_pressure": 950},
               "hourly": {"time": ["2026-10-09T21:00"], "temperature_2m": [27.0]}}
    mp = pytest.MonkeyPatch()
    mp.setattr(live, "weather_now", lambda lat, lon: weather)
    mp.setattr(live, "place_name", lambda lat, lon: "Test Nagar, Pune")
    with TestClient(web.app) as c:
        yield c
    mp.undo()


def test_pages_and_api(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    status = client.get("/api/status").json()
    assert set(status["cities"]) == {"Pune", "Mumbai"} and status["live_readings"] is False

    o = client.get("/api/overview?city=Pune").json()
    assert o["forecast"] and o["measured"]["aqi"] > 0 and o["weather"]["current"]["temperature_2m"] == 27.0
    assert client.get("/api/overview?city=Delhi").status_code == 404

    s = client.get("/api/stations?city=Pune").json()
    assert s["source"] == "archive" and all(st["category"]["name"] for st in s["stations"])

    a = client.get("/api/area?lat=18.507&lon=73.807").json()
    assert a["city"] == "Pune" and a["place"] == "Test Nagar, Pune" and a["measured"]["used"] >= 1 and a["forecast"]
    assert client.get("/api/area?lat=28.6&lon=77.2").status_code == 404  # Delhi is outside the coverage

    m = client.get("/api/model").json()
    assert m["dm"]["p"] < 0.05 and len(m["horizons"]) == 14
    i = client.get("/api/insights?city=Mumbai").json()
    assert len(i["hourly"]) == 12 * 24 and i["cigarettes_year"] > 0


def test_live_readings_start_the_forecast_today():
    st = pd.DataFrame({"station": ["A", "B"], "city": "Pune"})
    today = pd.Timestamp.today().normalize()
    daily = pd.DataFrame({"date": [today], "city": ["Pune"], "aqi": [float("nan")], "pm25": [float("nan")], "pm10": [float("nan")], "stations": [0.0]})
    readings = pd.DataFrame({"station": ["A", "B"], "aqi": [100.0, 120.0], "pm25": [40.0, 50.0], "pm10": [100.0, 120.0]})
    d = web.with_live_day(daily, readings, st)
    assert d.loc[0, "aqi"] == 110 and d.loc[0, "stations"] == 2


def test_openaq_parsing(monkeypatch):
    hours = [{"value": v, "period": {"datetimeTo": {"local": f"2026-10-09T{h:02d}:00:00+05:30"}}} for h, v in enumerate([45.0] * 20 + [999.0])]
    def fake(url, params, headers=None):
        if url.endswith("/locations/1"):
            return {"results": [{"coordinates": {"latitude": 18.5, "longitude": 73.8},
                                 "sensors": [{"id": 11, "parameter": {"name": "pm25"}}, {"id": 12, "parameter": {"name": "no2"}}]}]}
        return {"results": hours}
    monkeypatch.setattr(live, "_json", fake)
    df = live.openaq_latest({1: "Test"}, key="k", pause=0)
    assert len(df) == 1 and df.loc[0, "pm25"] == 45 and df.loc[0, "aqi"] == 75  # 999 error code dropped


def test_outbound_calls_are_throttled_and_cache_is_bounded(monkeypatch):
    calls = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b"{}"

    monkeypatch.setattr(live.urllib.request, "urlopen", lambda req, timeout: calls.append(req.full_url) or Resp())
    monkeypatch.setattr(live, "_last_call", {})
    live._json(live.GEOCODE, {"lat": 1})
    with pytest.raises(live.Throttled):  # a second lookup within a second never leaves the machine
        live._json(live.GEOCODE, {"lat": 2})
    assert len(calls) == 1

    monkeypatch.setattr(live, "_cache", {})
    monkeypatch.setattr(live, "CACHE_SIZE", 3)
    for i in range(5):
        live.cached(("k", i), 60, lambda i=i: i)
    assert list(live._cache) == [("k", 2), ("k", 3), ("k", 4)]


def test_area_lookups_are_limited_per_visitor(monkeypatch):
    monkeypatch.setattr(web, "_area_hits", {})
    assert all(web.allow_area("1.2.3.4") for _ in range(web.AREA_PER_MINUTE))
    assert not web.allow_area("1.2.3.4")
    assert web.allow_area("5.6.7.8")  # other visitors are unaffected


def test_area_limit_groups_ipv6_and_caps_memory(monkeypatch):
    monkeypatch.setattr(web, "_area_hits", {})
    assert all(web.allow_area(f"2001:db8::{i:x}") for i in range(web.AREA_PER_MINUTE))
    assert not web.allow_area("2001:db8::ffff")  # same /64, same visitor
    monkeypatch.setattr(web, "MAX_VISITORS", 5)
    for i in range(20):
        web.allow_area(f"10.0.0.{i}")
    assert len(web._area_hits) == 5 and "10.0.0.19" in web._area_hits

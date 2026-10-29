import tempfile
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import engine
from app.main import app
from app.sync import upsert_activities


def garmin_run(activity_id: int, days_ago: int, miles: float, avg_hr: float) -> dict:
    start = datetime.combine(date.today() - timedelta(days=days_ago), datetime.min.time()).replace(hour=7)
    return {
        "activityId": activity_id,
        "startTimeLocal": start.strftime("%Y-%m-%d %H:%M:%S"),
        "activityName": "Morning Run",
        "activityType": {"typeKey": "running"},
        "distance": miles * 1609.344,
        "duration": miles * 540,  # 9:00/mi
        "averageHR": avg_hr,
    }


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        with Session(engine) as s:
            upsert_activities(s, [garmin_run(1, 10, 3, 140), garmin_run(2, 3, 4, 145), garmin_run(3, 1, 5, 150)])
        yield c


def test_starts_with_no_races_and_default_profile(client):
    assert client.get("/api/races").json() == []
    assert client.get("/api/profile").json()["max_hr"] == 185


def test_activities_have_load_and_manual_edits_stick(client):
    acts = [a for a in client.get("/api/activities").json() if a["id"] in (1, 2, 3)]
    assert [a["id"] for a in acts] == [3, 2, 1]
    assert all(a["load"] > 0 and a["load_source"] == "hr" for a in acts)

    r = client.patch("/api/activities/3", json={"rpe": 8, "pain": 2, "notes": "legs tight last mile"})
    assert r.json()["load_source"] == "hr+rpe"

    # Re-sync must not wipe manual fields.
    with Session(engine) as s:
        upsert_activities(s, [garmin_run(3, 1, 5, 150)])
    a3 = next(a for a in client.get("/api/activities").json() if a["id"] == 3)
    assert (a3["rpe"], a3["pain"], a3["notes"]) == (8, 2, "legs tight last mile")


def test_metrics(client):
    series = client.get("/api/metrics/load?days=30").json()
    assert series[-1]["day"] == date.today().isoformat()
    assert series[-1]["fitness"] > 0
    weeks = client.get("/api/metrics/weekly?weeks=4").json()
    assert sum(w["miles"] for w in weeks) == pytest.approx(12, abs=0.1)
    assert sum(w["runs"] for w in weeks) == 3


def test_race_dates_save(client):
    race = client.post("/api/races", json={"name": "Spring 10K", "distance_m": 10000}).json()
    r = client.put(f"/api/races/{race['id']}", json={**race, "race_date": "2027-03-21", "goal_time_s": 1800})
    assert r.status_code == 200 and r.json()["race_date"] == "2027-03-21"

    r = client.post("/api/races", json={"name": "Fall Marathon", "race_date": "2025-10-26", "distance_m": 42195, "result_time_s": 12600})
    assert r.status_code == 200 and r.json()["id"]


def test_daily_log_upsert(client):
    day = date.today().isoformat()
    client.put(f"/api/daily/{day}", json={"day": day, "pain_morning": 3, "calf_raises_left": 18, "calf_raises_right": 25})
    client.put(f"/api/daily/{day}", json={"day": day, "pain_morning": 2, "calf_raises_left": 20, "calf_raises_right": 25})
    logs = client.get("/api/daily").json()
    assert len(logs) == 1 and logs[0]["pain_morning"] == 2


def test_sync_without_login_is_401(client, monkeypatch):
    monkeypatch.setattr("app.garmin_client.TOKEN_DIR", __import__("pathlib").Path(tempfile.mkdtemp()) / "none")
    assert client.post("/api/sync").status_code == 401

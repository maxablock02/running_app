from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import engine
from app.main import app
from app.models import Activity, Lap

MI = 1609.344
RACE_DAY = date(2025, 10, 26)


def run(id_, day, miles, secs_per_mi, hr, name="Morning Run"):
    return Activity(
        id=id_, start_time=datetime.combine(day, datetime.min.time()).replace(hour=7), name=name,
        activity_type="running", distance_m=miles * MI, duration_s=miles * secs_per_mi, avg_hr=hr,
    )


def race_practice(id_, day, mp_secs, mp_hr):
    """4 easy miles (step 0) then 12 at marathon effort (step 1), with laps cached."""
    a = run(id_, day, 16, 470, 158, name="Build - W8 Sat Long Run - 16mi Race Practice")
    a.laps_fetched = True
    laps = [Lap(activity_id=id_, lap_index=i, distance_m=MI, duration_s=520, avg_hr=145, intensity="ACTIVE", step_index=0) for i in range(4)]
    laps += [Lap(activity_id=id_, lap_index=4 + i, distance_m=MI, duration_s=mp_secs, avg_hr=mp_hr, intensity="ACTIVE", step_index=1) for i in range(12)]
    return a, laps


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        profile = c.get("/api/profile").json()
        c.put("/api/profile", json={**profile, "lthr": 183, "resting_hr": 53, "marathon_hr": 170})
        with Session(engine) as s:
            start = RACE_DAY - timedelta(weeks=4) + timedelta(days=1)
            for i in range(28):
                s.add(run(100 + i, start + timedelta(days=i), 6, 520, 145))
            a, laps = race_practice(200, RACE_DAY - timedelta(days=14), 450, 165)
            s.add(a)
            s.add_all(laps)
            s.add(run(300, RACE_DAY, 26.4, 443, 170, name="Morning Run"))
            # A later block with no race result yet: same workout, faster.
            a2, laps2 = race_practice(400, date(2026, 9, 1), 435, 165)
            s.add(a2)
            s.add_all(laps2)
            s.commit()
        yield c


def test_block_detail(client):
    race = client.post("/api/races", json={"name": "Fall Marathon", "race_date": str(RACE_DAY), "distance_m": 42195, "result_time_s": 3 * 3600 + 15 * 60}).json()
    b = client.post("/api/blocks", json={"name": "Build 1", "start_date": str(RACE_DAY - timedelta(weeks=4) + timedelta(days=1)), "end_date": str(RACE_DAY), "race_id": race["id"]}).json()

    d = client.get(f"/api/blocks/{b['id']}").json()
    assert len(d["weeks"]) == 4
    assert d["weeks"][-1]["weeks_out"] == 0
    # Race-day run is excluded from training stats; the 16-miler is the longest.
    assert d["stats"]["longest_mi"] == 16
    assert d["stats"]["long_runs"] == 1
    assert d["result"]["vdot"] == pytest.approx(48.7, abs=0.5)
    assert d["race_run"]["id"] == 300

    key = {k["id"]: k for k in d["key_runs"]}
    assert key[200]["workout_type"] == "race_practice"
    assert key[200]["work"]["reps"] == 12  # only the marathon-pace step

    est = d["mp_estimate"]
    assert est["used"] == [200]
    # Easy daily runs (HR 145, far from marathon HR 170) never feed the estimate.
    assert [s["activity_id"] for s in est["samples"]] == [200]
    # MP segment 7:30/mi at HR 165 scaled up to HR 170 is faster than 7:30.
    assert est["speed"] > MI / 450
    assert 0.9 < est["calibration"] < 1.0  # the race came in slower than the HR model predicted


def test_later_block_borrows_calibration(client):
    client.post("/api/blocks", json={"name": "Build 2", "start_date": "2026-08-01", "end_date": "2026-10-11"})
    blocks = {b["name"]: b for b in client.get("/api/blocks").json()}
    est = blocks["Build 2"]["mp_estimate"]
    assert est["calibrated_from"] == "Build 1"
    assert est["calibrated_speed"] < est["speed"]


def test_unnamed_run_with_lap_button_reps_is_intervals(client):
    with Session(engine) as s:
        a = run(500, date(2026, 6, 2), 6, 500, 150)
        a.laps_fetched = True
        s.add(a)
        laps = [Lap(activity_id=500, lap_index=0, distance_m=1.5 * MI, duration_s=780, avg_hr=140)]
        for i in range(6):
            laps += [Lap(activity_id=500, lap_index=1 + 2 * i, distance_m=800, duration_s=180, avg_hr=168),
                     Lap(activity_id=500, lap_index=2 + 2 * i, distance_m=30, duration_s=90, avg_hr=130)]
        s.add_all(laps)
        s.commit()
    a = next(x for x in client.get("/api/activities?limit=500").json() if x["id"] == 500)
    assert a["workout_type"] == "intervals" and a["key"]
    detail = client.get("/api/activities/500/laps").json()
    assert detail["inferred"] and detail["work"]["reps"] == 6
    assert [l["role"] for l in detail["laps"][:3]] == ["WARMUP", "ACTIVE", "REST"]


def test_key_override_and_type_override(client):
    r = client.patch("/api/activities/100", json={"key_override": True, "workout_type_override": "tempo"}).json()
    assert r["key"] is True and r["workout_type"] == "tempo"

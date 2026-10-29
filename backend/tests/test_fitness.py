from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session

from app.db import engine
from app.engine.fitness import DEFAULT_SLOPE, LapPoint, detraining_loss, fit_hr_slope, steady_marker
from app.engine.workouts import speed_at_hr
from app.models import Activity, Lap

MI = 1609.344


def test_detraining_matches_literature_without_training():
    assert detraining_loss(0, 0) == 0
    assert detraining_loss(21, 0) == pytest.approx(0.067, abs=0.01)  # ~7% at 3 weeks
    assert detraining_loss(56, 0) == pytest.approx(0.13, abs=0.03)  # mid-teens by 8 weeks
    assert detraining_loss(365, 0) < 0.18  # levels off


def test_cross_training_slows_detraining():
    assert detraining_loss(28, 0.5) < detraining_loss(28, 0.0)
    assert detraining_loss(28, 5.0) == detraining_loss(28, 1.0)  # retention is capped


def test_fit_hr_slope_recovers_linear_relation_and_falls_back():
    points = [LapPoint(3.0 + 0.02 * (hr - 150), hr) for hr in range(130, 175)] * 2
    assert fit_hr_slope(points) == pytest.approx(0.02)
    assert fit_hr_slope(points[:10]) == DEFAULT_SLOPE  # too few laps
    assert fit_hr_slope([LapPoint(3.0, hr) for hr in range(100, 200)]) == DEFAULT_SLOPE  # flat = implausible


def test_linear_slope_shift_is_gentler_than_hr_reserve():
    hrr = speed_at_hr(3.3, 160, 170, 53)
    linear = speed_at_hr(3.3, 160, 170, 53, slope=0.02)
    assert linear == pytest.approx(3.5)
    assert 3.3 < linear < hrr


def test_steady_marker_shifts_laps_along_slope():
    points = [LapPoint(MI / 480, 156)] * 6 + [LapPoint(MI / 480 + 0.08, 160)] * 6 + [LapPoint(MI / 300, 185)]  # last is out of window
    m = steady_marker(points, 156, 0.02)
    assert m.laps == 12
    assert MI / m.speed == pytest.approx(480, abs=2)
    assert steady_marker(points[:5], 156, 0.02) is None


def add_run(s: Session, id_, day, miles, secs_per_mi, hr, name="Morning Run"):
    """A run with auto mile laps (first lap a bit slower, as warm-ups are)."""
    s.add(Activity(id=id_, start_time=datetime.combine(day, datetime.min.time()).replace(hour=7), name=name,
                   activity_type="running", distance_m=miles * MI, duration_s=miles * secs_per_mi, avg_hr=hr, laps_fetched=True))
    for i in range(int(miles)):
        s.add(Lap(activity_id=id_, lap_index=i, distance_m=MI, duration_s=secs_per_mi + (20 if i == 0 else 0), avg_hr=hr - (10 if i == 0 else 0)))


def add_800s(s: Session, id_, day, reps, rep_secs, hr):
    s.add(Activity(id=id_, start_time=datetime.combine(day, datetime.min.time()).replace(hour=18), name="Morning Run",
                   activity_type="running", distance_m=(2 + reps * 0.55) * MI, duration_s=3000, avg_hr=hr - 10, laps_fetched=True))
    laps = [Lap(activity_id=id_, lap_index=0, distance_m=1.5 * MI, duration_s=800, avg_hr=140)]
    for i in range(reps):
        # HR lags on 800s: modest average, peaks ~18 bpm higher.
        laps += [Lap(activity_id=id_, lap_index=1 + 2 * i, distance_m=800, duration_s=rep_secs, avg_hr=hr, max_hr=hr + 18),
                 Lap(activity_id=id_, lap_index=2 + 2 * i, distance_m=40, duration_s=90, avg_hr=hr - 15)]
    laps.append(Lap(activity_id=id_, lap_index=99, distance_m=0.5 * MI, duration_s=280, avg_hr=140))
    s.add_all(laps)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        profile = c.get("/api/profile").json()
        c.put("/api/profile", json={**profile, "lthr": 183, "resting_hr": 53})  # steady reference HR = 156
        # Early 2026 for the reference: later than test_blocks' race block and clear of other modules' runs.
        ref_end = date(2026, 3, 1)
        inj_end = date.today() - timedelta(days=10)
        injured = inj_end - timedelta(days=21)
        with Session(engine) as s:
            # Reference build: steady miles at 8:00 / HR 156, then a 3:10 marathon.
            for i in range(30):
                add_run(s, 9000 + i, ref_end - timedelta(days=50 - i), 7, 480, 156)
            add_800s(s, 9050, ref_end - timedelta(days=30), 8, 182, 158)  # 8 x 800 @ ~5:50
            # Injured build: same HR but 2% slower, injury 3 weeks out, DNF on race day.
            for i in range(30):
                add_run(s, 9100 + i, injured - timedelta(days=45 - i), 7, 490, 156)
            add_800s(s, 9150, injured - timedelta(days=20), 5, 180, 150)  # 5 x 800, faster and lower HR
            add_run(s, 9200, inj_end, 13, 470, 159)
            s.commit()
        r1 = c.post("/api/races", json={"name": "Ref Marathon", "race_date": str(ref_end), "distance_m": 42195, "result_time_s": 11400}).json()
        c.post("/api/blocks", json={"name": "Ref", "start_date": str(ref_end - timedelta(weeks=10)), "end_date": str(ref_end), "race_id": r1["id"]})
        r2 = c.post("/api/races", json={"name": "Injured Marathon", "race_date": str(inj_end), "distance_m": 42195, "status": "dnf"}).json()
        c.post("/api/blocks", json={"name": "Injured", "start_date": str(inj_end - timedelta(weeks=12)), "end_date": str(inj_end),
                                    "race_id": r2["id"], "interrupted_on": str(injured)})
        yield c


def test_dnf_block_summarizes_pre_injury(client):
    b = next(x for x in client.get("/api/blocks").json() if x["name"] == "Injured")
    assert b["result"]["status"] == "dnf"
    assert b["result"]["distance_m"] == pytest.approx(13 * MI)
    assert b["pre_injury"]["weeks_out"] == 3
    assert b["pre_injury"]["runs"] >= 30  # other test modules share the database
    assert b["mp_estimate"] is None or "calibration" not in b["mp_estimate"]  # a DNF never calibrates
    assert MI / b["steady"]["speed"] == pytest.approx(490, abs=3)  # first (warm-up) laps skipped


def test_current_fitness_from_injured_block(client):
    block_id = next(x["id"] for x in client.get("/api/blocks").json() if x["name"] == "Injured")
    d = client.get(f"/api/fitness/current?block_id={block_id}").json()
    assert d["block"]["name"] == "Injured"
    est = next(e for e in d["estimates"] if e["method"] == "steady_ratio")
    assert est["reference"] == "Ref"
    assert est["ratio"] == pytest.approx(480 / 490, abs=0.005)
    assert 42195 / est["marathon_speed"] == pytest.approx(11400 * 490 / 480, rel=0.01)
    speeds = [e["marathon_speed"] for e in d["estimates"]]
    assert d["pre"]["marathon_speed"] == pytest.approx(sum(speeds) / len(speeds))  # methods averaged
    assert d["days"] == 31
    assert d["now"]["vdot"] < d["pre"]["vdot"]
    dnf = next(o for o in d["observed"] if o["activity_id"] == 9200)
    assert dnf["race_day"]


def test_similar_sessions_match_rep_length_across_blocks(client):
    d = client.get("/api/activities/9150/similar").json()
    assert d["shape"]["kind"] == "reps" and d["shape"]["reps"] == 5
    match = next(m for m in d["matches"] if m["activity_id"] == 9050)
    assert match["block"] == "Ref" and match["reps"] == 8
    assert d["shape"]["speed"] > match["speed"] and d["shape"]["avg_hr"] < match["avg_hr"]
    # A steady run has no comparable shape.
    assert client.get("/api/activities/9100/similar").json()["shape"] is None

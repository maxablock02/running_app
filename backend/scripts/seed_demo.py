"""Fill a throwaway database with a fictional runner's year to try the UI.

Two finished builds (a half marathon, then a marathon) with structured workouts
and laps, a 30-day break after the marathon, a gradual return with rehab logs,
and two upcoming races. Dates are relative to today. Safe to re-run.

Refuses to run against the real database. From the backend folder:

    $env:RUNNING_DB="data\\demo.db"; $env:PYTHONPATH="."; .venv\\Scripts\\python scripts\\seed_demo.py
"""

import os
import random
import sys
from datetime import date, datetime, timedelta

if "RUNNING_DB" not in os.environ:
    sys.exit("Set RUNNING_DB to a demo database path first (this never touches data/running.db).")
if os.path.basename(os.environ["RUNNING_DB"]) == "running.db":
    sys.exit("RUNNING_DB points at running.db; use a separate demo database.")

from sqlmodel import Session, select  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from app.models import Activity, Block, DailyLog, Lap, Race  # noqa: E402

MI = 1609.344
HALF_M, MARATHON_M = 21097.5, 42195
SLOPE = 0.02  # m/s per bpm: the fictional runner's pace-vs-HR relation
HALF_RACE, MARATHON_RACE = 290, 80  # race days, as days before today
BREAK = range(46, 76)  # no running
REHAB_FROM = 45

random.seed(4)
today = date.today()


def fitness(back: int) -> float:
    """Speed multiplier: builds up slowly over the year, dips after the break."""
    f = 1 + 0.05 * (380 - back) / 380
    return f * 0.95 if back < REHAB_FROM else f


def speed(hr: float, back: int) -> float:
    """Speed (m/s) this runner holds at a given HR on a given day: ~9:00/mi at HR 140 to start."""
    return (2.98 + SLOPE * (hr - 140)) * fitness(back)


def mile_laps(back: int, miles: float, hr: float, segments: list[tuple[float, float]] | None = None) -> list[dict]:
    """Auto mile laps. segments = [(miles, hr)] overrides the steady HR for parts of the run."""
    plan = segments or [(miles, hr)]
    laps = []
    for seg_mi, seg_hr in plan:
        whole, part = int(seg_mi), seg_mi - int(seg_mi)
        for dist in [MI] * whole + ([part * MI] if part > 0.05 else []):
            h = round(seg_hr + random.uniform(-2, 2) - (8 if not laps else 0))  # HR still rising in lap 1
            laps.append({"distance_m": dist, "duration_s": dist / speed(h, back) * random.uniform(0.98, 1.02), "avg_hr": h})
    return laps


def intervals(back: int, reps: int, rep_m: float) -> list[dict]:
    """Lap-button session: warm-up, reps with standing/jog rests, cool-down."""
    laps = mile_laps(back, 1.5, 140)
    for _ in range(reps):
        hr = random.randint(164, 168)
        laps.append({"distance_m": rep_m, "duration_s": rep_m / (speed(hr, back) * 1.12), "avg_hr": hr, "max_hr": hr + 12})
        laps.append({"distance_m": 100, "duration_s": 90, "avg_hr": 135})
    return laps + mile_laps(back, 1, 142)


def race_practice(back: int, mp_miles: int) -> list[dict]:
    """Structured watch workout: easy step then marathon-pace step."""
    easy = [dict(l, intensity="ACTIVE", step_index=0) for l in mile_laps(back, 4, 142)]
    mp = [dict(l, intensity="ACTIVE", step_index=1) for l in mile_laps(back, mp_miles, 157)]
    return easy + mp


runs: list[tuple[int, str, list[dict]]] = []  # (days back, name, laps)
for back in range(380, 0, -1):
    if back in BREAK:
        continue
    weekday = (today - timedelta(days=back)).weekday()  # Mon = 0
    week = None
    for race_back, weeks in ((HALF_RACE, 12), (MARATHON_RACE, 16)):
        if 0 < back - race_back <= weeks * 7:
            week = weeks - (back - race_back - 1) // 7  # W1 .. W16, race week last
            build_weeks = weeks
    if back == HALF_RACE:
        runs.append((back, "Morning Run", mile_laps(back, 13.1, 166)))
    elif back == MARATHON_RACE:
        runs.append((back, "Morning Run", mile_laps(back, 26.2, 157)))
    elif back < REHAB_FROM:
        if random.random() < 0.45:
            continue
        mi = min(2 + (REHAB_FROM - back) / 10 + random.uniform(0, 1), 6)
        runs.append((back, "Morning Run", mile_laps(back, round(mi, 1), random.uniform(135, 142))))
    elif week is None:  # off-season base
        if weekday in (0, 4) or random.random() < 0.2:
            continue
        runs.append((back, "Morning Run", mile_laps(back, random.choice([4, 5, 6, 6, 8]), random.uniform(130, 140))))
    elif week > build_weeks - 1 and weekday not in (1, 3):  # race week: two short runs
        continue
    elif weekday == 0:
        continue  # rest day
    elif weekday == 1 and week % 2:
        runs.append((back, "Morning Run", intervals(back, random.choice([6, 8]), 800)))
    elif weekday == 1:
        runs.append((back, f"W{week} Tue Intervals - 5 x 1K", intervals(back, 5, 1000)))
    elif weekday == 3 and week > 2:
        t = min(2 + week // 3, 6)
        runs.append((back, "Morning Run", mile_laps(back, t + 3, 0, [(2, 142), (t, 163), (1, 142)])))
    elif weekday == 5:
        long_mi = min(10 + week, 20 if build_weeks == 16 else 15)
        if week % 3 == 0 and week > 3 and build_weeks == 16:
            mp = min(6 + week // 2, 12)
            runs.append((back, f"W{week} Sat Long Run - {mp + 4}mi Race Practice", race_practice(back, mp)))
        else:
            runs.append((back, "Morning Run", mile_laps(back, long_mi, 140)))
    else:
        runs.append((back, "Morning Run", mile_laps(back, random.choice([5, 6, 6, 7, 8]), random.uniform(132, 140))))


init_db()
with Session(engine) as s:
    for back, name, laps in runs:
        aid = 1000 + back
        d = today - timedelta(days=back)
        dist = sum(l["distance_m"] for l in laps)
        dur = sum(l["duration_s"] for l in laps)
        a = Activity(id=aid, start_time=datetime.combine(d, datetime.min.time()).replace(hour=7), name=name,
                     activity_type="running", distance_m=dist, duration_s=dur,
                     avg_hr=round(sum(l["avg_hr"] * l["duration_s"] for l in laps) / dur),
                     max_hr=max(l.get("max_hr", l["avg_hr"] + 6) for l in laps), laps_fetched=True)
        if back < REHAB_FROM:
            a.pain = max(0, round(REHAB_FROM / 15 - (REHAB_FROM - back) / 15 + random.uniform(-0.5, 0.5)))
            a.rpe = random.choice([3, 4, 4, 5])
        s.merge(a)
        for i, l in enumerate(laps):
            s.merge(Lap(activity_id=aid, lap_index=i, **l))

    for back in range(REHAB_FROM, -1, -1):
        d = today - timedelta(days=back)
        s.merge(DailyLog(day=d, pain_morning=max(0, round(back / 9 + random.random() - 0.3)), rehab_done=True,
                         calf_raises_left=12 + (REHAB_FROM - back) // 3 if back % 4 == 0 else None,
                         calf_raises_right=27 if back % 4 == 0 else None))

    def race(name: str, back: int, distance_m: float, priority: str, **kw) -> Race:
        r = s.exec(select(Race).where(Race.name == name)).first()
        if r is None:
            r = Race(name=name, distance_m=distance_m, priority=priority, **kw)
            s.add(r)
        r.race_date = today - timedelta(days=back)
        s.flush()
        return r

    def actual_time(back: int) -> int:
        return round(s.get(Activity, 1000 + back).duration_s)

    half = race("Riverfront Half Marathon", HALF_RACE, HALF_M, "A", goal_time_s=95 * 60, result_time_s=actual_time(HALF_RACE))
    full = race("Harbor City Marathon", MARATHON_RACE, MARATHON_M, "A", goal_time_s=3 * 3600 + 25 * 60,
                result_time_s=actual_time(MARATHON_RACE))
    race("Spring 10K", -45, 10000, "B", goal_time_s=42 * 60, notes="Tune-up")
    race("Autumn Half Marathon", -150, HALF_M, "A", goal_time_s=93 * 60)

    for name, r, weeks in (("Half build", half, 12), ("Marathon build", full, 16)):
        if s.exec(select(Block).where(Block.name == name)).first() is None:
            s.add(Block(name=name, start_date=r.race_date - timedelta(weeks=weeks) + timedelta(days=1),
                        end_date=r.race_date, race_id=r.id))
    s.commit()
print(len(runs), "runs")

"""Training blocks: the build into a race, its key workouts, and what it says about fitness."""

from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.engine.fitness import steady_marker, steady_ref_hr
from app.engine.load import activity_load, load_series
from app.engine.vdot import predict_seconds, vdot
from app.engine.workouts import speed_at_hr, summarize
from app.garmin_client import GarminNotLoggedIn
from app.models import MILE_M, Activity, Block, BlockBase, Profile, Race
from app.routers.activities import (
    activity_is_key, hr_slope, is_run, load_laps, physiology, steady_points, with_load, work_json, workout_type,
)
from app.sync import fetch_laps

router = APIRouter(prefix="/api/blocks", tags=["blocks"])

LONG_RUN_MI = 16
# Marathon-pace estimate uses continuous work segments of at least this length in the final weeks.
MP_MIN_SEGMENT_MI = 3
MP_WINDOW_WEEKS = 8
MP_TYPES = {"race_practice", "long", "tempo", "workout"}
# Only segments run fairly close to marathon HR count: the HR->pace shift is less reliable over big gaps.
# Training "marathon effort" usually sits a few bpm below race-day HR (no taper, no adrenaline, no drift).
MP_HR_TOLERANCE = 10
EQUIVALENTS = {"5K": 5000, "10K": 10000, "Half": 21097.5, "Marathon": 42195}


def block_runs(session: Session, b: Block) -> list[Activity]:
    acts = session.exec(
        select(Activity)
        .where(Activity.start_time >= b.start_date, Activity.start_time < b.end_date + timedelta(days=1))
        .order_by(Activity.start_time)
    ).all()
    return [a for a in acts if is_run(a.activity_type) and not a.excluded]


def race_activity(runs: list[Activity], race: Race | None, end: date) -> Activity | None:
    """The run on race day that matches the race distance (for a DNF: the longest run that day)."""
    if race is None:
        return None
    on_day = [a for a in runs if a.start_time.date() == (race.race_date or end)]
    if race.status == "dnf":
        return max(on_day, key=lambda a: a.distance_m, default=None)
    for a in on_day:
        if abs(a.distance_m - race.distance_m) <= 0.04 * race.distance_m:
            return a
    return None


def training_stats(training: list[Activity], weeks: list[dict], n_weeks: int) -> dict:
    miles = [w["miles"] for w in weeks]
    return {
        "total_mi": round(sum(miles), 1),
        "avg_week_mi": round(sum(miles) / n_weeks, 1) if n_weeks else 0,
        "peak_week_mi": max(miles, default=0),
        "runs": len(training),
        "long_runs": sum(1 for a in training if a.distance_m >= LONG_RUN_MI * MILE_M),
        "longest_mi": round(max((a.distance_m for a in training), default=0) / MILE_M, 1),
    }


def fitness_by_day(session: Session) -> dict[date, float]:
    p = physiology(session)
    daily: dict[date, float] = defaultdict(float)
    for a in session.exec(select(Activity).where(Activity.excluded == False)).all():  # noqa: E712
        daily[a.start_time.date()] += activity_load(a.duration_s, a.avg_hr, a.rpe, p, a.load_override)[0]
    if not daily:
        return {}
    return {s.day: s.fitness for s in load_series(daily, min(daily), max(max(daily), date.today()))}


def summarize_block(session: Session, b: Block, fitness: dict[date, float], slope: float, detail: bool = False) -> dict:
    prof = session.get(Profile, 1)
    phys = physiology(session)
    race = session.get(Race, b.race_id) if b.race_id else None
    runs = block_runs(session, b)
    race_run = race_activity(runs, race, b.end_date)
    training = [a for a in runs if a is not race_run]
    laps = load_laps(session, [a.id for a in runs])
    key_runs = [a for a in training if activity_is_key(a, prof.lthr, laps.get(a.id))]

    n_weeks = (b.end_date - b.start_date).days // 7 + 1
    weeks = [{"weeks_out": w, "miles": 0.0, "runs": 0, "long_mi": 0.0} for w in range(n_weeks - 1, -1, -1)]
    for a in training:
        w = (b.end_date - a.start_time.date()).days // 7
        row = weeks[n_weeks - 1 - w]
        mi = a.distance_m / MILE_M
        row["miles"] = round(row["miles"] + mi, 1)
        row["runs"] += 1
        row["long_mi"] = round(max(row["long_mi"], mi), 1)

    block_fitness = [fitness.get(b.start_date + timedelta(days=i), 0) for i in range((b.end_date - b.start_date).days + 1)]
    out = {
        **b.model_dump(),
        "race": race.model_dump() if race else None,
        "weeks": weeks,
        "stats": {
            **training_stats(training, weeks, n_weeks),
            "key_workouts": len(key_runs),
            # Fitness the morning of the last day (race morning) and the block's peak.
            "fitness_end": round(fitness.get(b.end_date - timedelta(days=1), 0), 1),
            "fitness_peak": round(max(block_fitness, default=0), 1),
        },
        "pre_injury": None,
        "result": None,
        "mp_estimate": None,
    }

    # Training was cut short: summarize the part before the injury, which is what fitness estimates use.
    cutoff = b.interrupted_on if b.interrupted_on and b.interrupted_on <= b.end_date else None
    if cutoff:
        pre = [a for a in training if a.start_time.date() < cutoff]
        weeks_out = (b.end_date - cutoff).days // 7
        pre_weeks = [w for w in weeks if w["weeks_out"] > weeks_out]
        out["pre_injury"] = {
            **training_stats(pre, pre_weeks, len(pre_weeks)),
            "weeks_out": weeks_out,
            "last_run": max((a.start_time.date() for a in pre), default=None),
            "fitness": round(fitness.get(cutoff - timedelta(days=1), 0), 1),
        }

    if race and race.status == "dnf":
        out["result"] = {
            "status": "dnf",
            "distance_m": race_run.distance_m if race_run else None,
            "time_s": (race_run.moving_s or race_run.duration_s) if race_run else None,
            "avg_hr": race_run.avg_hr if race_run else None,
        }
    result_s = None if race and race.status else (
        (race.result_time_s if race else None) or (race_run.moving_s or race_run.duration_s if race_run else None)
    )
    if race and result_s:
        v = vdot(race.distance_m, result_s)
        out["result"] = {
            "status": "finished",
            "time_s": result_s,
            "vdot": round(v, 1),
            "avg_hr": race_run.avg_hr if race_run else None,
            "equivalents": {k: round(predict_seconds(v, d)) for k, d in EQUIVALENTS.items()},
        }

    # Work segments of key workouts (only those with cached laps).
    work = {a.id: summarize(laps[a.id], prof.lthr) for a in key_runs if a.id in laps}

    # Marathon-pace estimate: long continuous work segments in the last weeks of real training
    # (before race day, or before the injury), scaled to marathon HR.
    window_end = cutoff or b.end_date
    window_start = window_end - timedelta(weeks=MP_WINDOW_WEEKS)
    samples = []
    for a in key_runs:
        s = work.get(a.id)
        if (
            s and s.avg_hr and window_start <= a.start_time.date() < window_end
            and workout_type(a, prof.lthr, laps.get(a.id)) in MP_TYPES
            and "treadmill" not in a.activity_type  # treadmill pace isn't trustworthy
            and abs(s.avg_hr - prof.marathon_hr) <= MP_HR_TOLERANCE
            and s.distance_m >= MP_MIN_SEGMENT_MI * MILE_M
            and s.reps <= 30  # continuous effort, not short reps
        ):
            est = speed_at_hr(s.speed, s.avg_hr, prof.marathon_hr, prof.resting_hr, slope)
            samples.append({"activity_id": a.id, "date": a.start_time.date(), "name": a.name,
                            "work_mi": round(s.distance_m / MILE_M, 1), "speed": s.speed, "avg_hr": round(s.avg_hr), "est_speed": est})
    marker = steady_marker(
        [p for a in training if window_start <= a.start_time.date() < window_end
         for p in steady_points(a, laps.get(a.id), prof.lthr)],
        steady_ref_hr(prof.lthr), slope,
    )
    out["steady"] = marker.__dict__ if marker else None

    if samples:
        recent = sorted(samples, key=lambda x: x["date"])[-3:]
        est_speeds = sorted(x["est_speed"] for x in recent)
        est = est_speeds[len(est_speeds) // 2]
        out["mp_estimate"] = {
            "marathon_hr": prof.marathon_hr,
            "hr_tolerance": MP_HR_TOLERANCE,
            "speed": est,
            "marathon_s": round(42195 / est),
            "samples": samples,
            "used": [x["activity_id"] for x in recent],
        }
        if race and result_s and abs(race.distance_m - 42195) < 500:
            out["mp_estimate"]["actual_speed"] = race.distance_m / result_s
            out["mp_estimate"]["calibration"] = (race.distance_m / result_s) / est

    if detail:
        out["key_runs"] = [
            {**with_load(a, phys, laps.get(a.id)), "work": work_json(work.get(a.id)),
             "weeks_out": (b.end_date - a.start_time.date()).days // 7}
            for a in key_runs
        ]
        out["race_run"] = with_load(race_run, phys, laps.get(race_run.id)) if race_run else None
    return out


def apply_calibration(blocks: list[dict]) -> None:
    """Blocks without a marathon result borrow the calibration from the latest one that has it."""
    last = None
    for b in sorted(blocks, key=lambda b: b["end_date"]):
        est = b["mp_estimate"]
        if est and "calibration" in est:
            last = (est["calibration"], b["name"])
        elif est and last:
            est["calibrated_speed"] = est["speed"] * last[0]
            est["calibrated_from"] = last[1]
            est["calibrated_marathon_s"] = round(42195 / est["calibrated_speed"])


def all_block_summaries(session: Session) -> list[dict]:
    fitness = fitness_by_day(session)
    slope = hr_slope(session)
    blocks = [summarize_block(session, b, fitness, slope) for b in session.exec(select(Block)).all()]
    apply_calibration(blocks)
    return sorted(blocks, key=lambda b: b["end_date"], reverse=True)


@router.get("")
def list_blocks(session: Session = Depends(get_session)):
    return all_block_summaries(session)


@router.get("/{block_id}")
def get_block(block_id: int, session: Session = Depends(get_session)):
    b = session.get(Block, block_id)
    if b is None:
        raise HTTPException(404, "Block not found")
    fitness = fitness_by_day(session)
    slope = hr_slope(session)
    everything = [summarize_block(session, x, fitness, slope, detail=x.id == block_id) for x in session.exec(select(Block)).all()]
    apply_calibration(everything)
    return next(x for x in everything if x["id"] == block_id)


@router.post("")
def create_block(body: BlockBase, session: Session = Depends(get_session)):
    b = Block(**body.model_dump())
    session.add(b)
    session.commit()
    session.refresh(b)
    return b


@router.put("/{block_id}")
def update_block(block_id: int, body: BlockBase, session: Session = Depends(get_session)):
    if session.get(Block, block_id) is None:
        raise HTTPException(404, "Block not found")
    b = session.merge(Block(**body.model_dump(), id=block_id))
    session.commit()
    session.refresh(b)
    return b


@router.delete("/{block_id}")
def delete_block(block_id: int, session: Session = Depends(get_session)):
    b = session.get(Block, block_id)
    if b is None:
        raise HTTPException(404, "Block not found")
    session.delete(b)
    session.commit()
    return {"ok": True}


@router.post("/{block_id}/fetch-laps")
def fetch_block_laps(block_id: int, session: Session = Depends(get_session)):
    """Fetch laps from Garmin for every key workout in the block that doesn't have them yet."""
    b = session.get(Block, block_id)
    if b is None:
        raise HTTPException(404, "Block not found")
    # Every run: an unnamed run's laps are what reveal whether it was a workout.
    ids = [a.id for a in block_runs(session, b)]
    try:
        return {"fetched": fetch_laps(session, ids)}
    except GarminNotLoggedIn as e:
        raise HTTPException(401, str(e)) from e

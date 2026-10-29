from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.engine.fitness import STEADY_LAP_M, LapPoint, fit_hr_slope
from app.engine.load import Physiology, activity_load, load_series
from app.engine.workouts import (
    LapData, classify, infer_structure, is_key, is_unstructured, speed_at_hr, summarize, work_laps,
)
from app.garmin_client import GarminNotLoggedIn
from app.models import MILE_M, Activity, Block, Lap, Profile
from app.sync import fetch_laps

router = APIRouter(prefix="/api", tags=["activities"])


def is_run(activity_type: str) -> bool:
    return "running" in activity_type


def physiology(session: Session) -> Physiology:
    p = session.get(Profile, 1)
    return Physiology(p.max_hr, p.resting_hr, p.lthr, p.sex, p.rpe_weight)


def lap_data(laps: list[Lap]) -> list[LapData]:
    return [LapData(l.lap_index, l.distance_m, l.moving_s or l.duration_s, l.avg_hr, l.intensity, l.step_index, l.max_hr) for l in laps]


def load_laps(session: Session, activity_ids: list[int]) -> dict[int, list[LapData]]:
    """Cached laps for many activities in one query, ordered by lap index."""
    by_id: dict[int, list[Lap]] = defaultdict(list)
    for lap in session.exec(select(Lap).where(Lap.activity_id.in_(activity_ids)).order_by(Lap.lap_index)).all():
        by_id[lap.activity_id].append(lap)
    return {i: lap_data(ls) for i, ls in by_id.items()}


STEADY_EXCLUDE = {"intervals", "race"}


def steady_points(a: Activity, laps: list[LapData] | None, lthr: int) -> list[LapPoint]:
    """Steady auto-mile laps of a run (skipping the first, HR still rising), for pace-vs-HR markers."""
    if not laps or not is_run(a.activity_type) or "treadmill" in a.activity_type or a.excluded:
        return []
    if workout_type(a, lthr, laps) in STEADY_EXCLUDE:
        return []
    lo, hi = STEADY_LAP_M
    return [LapPoint(l.speed, l.avg_hr) for l in laps[1:] if lo <= l.distance_m <= hi and l.avg_hr]


def hr_slope(session: Session) -> float:
    """Your pace-vs-HR slope, fitted from steady laps across all history."""
    lthr = session.get(Profile, 1).lthr
    runs = session.exec(select(Activity).where(Activity.activity_type.contains("running"))).all()
    laps = load_laps(session, [a.id for a in runs])
    points = [p for a in runs for p in steady_points(a, laps.get(a.id), lthr) if 0.70 * lthr <= p.hr <= 0.95 * lthr]
    return fit_hr_slope(points)


def workout_type(a: Activity, lthr: int, laps: list[LapData] | None = None) -> str | None:
    if not is_run(a.activity_type):
        return None
    return a.workout_type_override or classify(a.name, a.distance_m, a.avg_hr, lthr, laps)


def activity_is_key(a: Activity, lthr: int, laps: list[LapData] | None = None) -> bool:
    if a.key_override is not None:
        return a.key_override
    t = workout_type(a, lthr, laps)
    return t is not None and is_key(t, a.distance_m)


def with_load(a: Activity, p: Physiology, laps: list[LapData] | None = None) -> dict:
    load, source = activity_load(a.duration_s, a.avg_hr, a.rpe, p, a.load_override)
    return {
        **a.model_dump(),
        "load": 0.0 if a.excluded else round(load, 1),
        "load_source": source,
        "workout_type": workout_type(a, p.lthr, laps),
        "key": activity_is_key(a, p.lthr, laps),
    }


@router.get("/activities")
def list_activities(limit: int = 100, offset: int = 0, runs_only: bool = False, session: Session = Depends(get_session)):
    q = select(Activity).order_by(Activity.start_time.desc())
    if runs_only:
        q = q.where(Activity.activity_type.contains("running"))
    p = physiology(session)
    acts = session.exec(q.offset(offset).limit(limit)).all()
    laps = load_laps(session, [a.id for a in acts])
    return [with_load(a, p, laps.get(a.id)) for a in acts]


class ActivityUpdate(BaseModel):
    rpe: int | None = None
    pain: int | None = None
    notes: str | None = None
    load_override: float | None = None
    excluded: bool | None = None
    workout_type_override: str | None = None
    key_override: bool | None = None


@router.patch("/activities/{activity_id}")
def update_activity(activity_id: int, body: ActivityUpdate, session: Session = Depends(get_session)):
    a = session.get(Activity, activity_id)
    if a is None:
        raise HTTPException(404, "Activity not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    session.add(a)
    session.commit()
    session.refresh(a)
    return with_load(a, physiology(session), load_laps(session, [a.id]).get(a.id))


@router.get("/activities/{activity_id}/laps")
def activity_laps(activity_id: int, session: Session = Depends(get_session)):
    """Laps plus the detected work segment. Fetched from Garmin on first request, then cached."""
    a = session.get(Activity, activity_id)
    if a is None:
        raise HTTPException(404, "Activity not found")
    try:
        fetch_laps(session, [activity_id])
    except GarminNotLoggedIn as e:
        raise HTTPException(401, str(e)) from e
    laps = session.exec(select(Lap).where(Lap.activity_id == activity_id).order_by(Lap.lap_index)).all()
    data = lap_data(laps)
    lthr = session.get(Profile, 1).lthr
    # Unnamed runs: roles come from the inferred structure; plan workouts: from Garmin's tags.
    tagged = infer_structure(data, lthr).laps if is_unstructured(data) else data
    role = {l.lap_index: l.intensity for l in tagged}
    work_idx = {l.lap_index for l in work_laps(data, lthr)}
    return {
        "laps": [{**l.model_dump(), "role": role.get(l.lap_index), "work": l.lap_index in work_idx} for l in laps],
        "work": work_json(summarize(data, lthr)),
        "inferred": is_unstructured(data),
    }


SIMILAR_REP_TOLERANCE = 0.20  # interval sessions: mean rep length within ±20%
SIMILAR_SEGMENT_TOLERANCE = 0.35  # continuous efforts: segment length within ±35%
CONTINUOUS_TYPES = {"tempo", "race_practice", "workout"}


def session_shape(a: Activity, laps: list[LapData] | None, lthr: int) -> dict | None:
    """What kind of session this was, in comparable terms: reps of X m, or one Y-mile effort."""
    if not laps:
        return None
    t = workout_type(a, lthr, laps)
    s = summarize(laps, lthr)
    if s is None:
        return None
    work = work_laps(laps, lthr)
    peaks = [l.max_hr for l in work if l.max_hr]
    shape = {
        "activity_id": a.id, "date": a.start_time.date(), "name": a.name, "workout_type": t,
        **work_json(s), "speed": s.speed, "peak_hr": sum(peaks) / len(peaks) if peaks else None,
    }
    if t == "intervals" and s.intervals and s.reps >= 2:
        return {**shape, "kind": "reps", "rep_m": s.distance_m / s.reps}
    # A "workout" by HR alone whose work is the whole run is just a hard steady run, not a segment.
    whole_run = s.distance_m > 0.9 * a.distance_m
    if t in CONTINUOUS_TYPES and s.distance_m >= 2 * MILE_M and not s.intervals and not (t == "workout" and whole_run):
        return {**shape, "kind": "segment"}
    return None


@router.get("/activities/{activity_id}/similar")
def similar_sessions(activity_id: int, limit: int = 12, session: Session = Depends(get_session)):
    """Sessions shaped like this one (same rep length, or similar continuous effort), across all your blocks."""
    lthr = session.get(Profile, 1).lthr
    runs = session.exec(select(Activity).where(Activity.activity_type.contains("running"), Activity.excluded == False)).all()  # noqa: E712
    laps = load_laps(session, [a.id for a in runs])
    target = next((a for a in runs if a.id == activity_id), None)
    me = session_shape(target, laps.get(activity_id), lthr) if target else None
    if me is None:
        return {"shape": None, "matches": []}

    blocks = session.exec(select(Block)).all()

    def block_name(d: date) -> str | None:
        return next((b.name for b in blocks if b.start_date <= d <= b.end_date), None)

    matches = []
    for a in runs:
        if a.id == activity_id or "treadmill" in a.activity_type:
            continue
        other = session_shape(a, laps.get(a.id), lthr)
        if other is None or other["kind"] != me["kind"]:
            continue
        if me["kind"] == "reps":
            ok = abs(other["rep_m"] / me["rep_m"] - 1) <= SIMILAR_REP_TOLERANCE
        else:
            ok = abs(other["distance_m"] / me["distance_m"] - 1) <= SIMILAR_SEGMENT_TOLERANCE
        if ok:
            matches.append({**other, "block": block_name(other["date"])})
    matches.sort(key=lambda m: m["date"], reverse=True)
    return {"shape": {**me, "block": block_name(me["date"])}, "matches": matches[:limit]}


def work_json(s) -> dict | None:
    if s is None:
        return None
    return {"reps": s.reps, "distance_m": s.distance_m, "duration_s": s.duration_s, "avg_hr": s.avg_hr, "intervals": s.intervals}


@router.get("/metrics/aerobic")
def aerobic_trend(session: Session = Depends(get_session)):
    """Monthly median easy-run pace scaled to profile.aerobic_hr: your aerobic efficiency over time."""
    prof = session.get(Profile, 1)
    runs = session.exec(select(Activity).where(Activity.activity_type.contains("running"))).all()
    laps = load_laps(session, [a.id for a in runs])
    slope = hr_slope(session)
    by_month: dict[str, list[float]] = defaultdict(list)
    for a in runs:
        if a.excluded or not a.avg_hr or a.distance_m < 3 * MILE_M:
            continue
        if workout_type(a, prof.lthr, laps.get(a.id)) != "easy" or abs(a.avg_hr - prof.aerobic_hr) > 20:
            continue
        speed = a.distance_m / (a.moving_s or a.duration_s)
        by_month[a.start_time.strftime("%Y-%m")].append(speed_at_hr(speed, a.avg_hr, prof.aerobic_hr, prof.resting_hr, slope))
    out = []
    for month in sorted(by_month):
        speeds = sorted(by_month[month])
        out.append({"month": month, "runs": len(speeds), "speed": speeds[len(speeds) // 2]})
    return {"hr": prof.aerobic_hr, "months": out}


@router.get("/metrics/load")
def load_metrics(days: int = 180, session: Session = Depends(get_session)):
    """Daily fitness / fatigue / form. Computed from all history so the averages are warmed up."""
    activities = session.exec(select(Activity).where(Activity.excluded == False)).all()  # noqa: E712
    if not activities:
        return []
    p = physiology(session)
    daily: dict[date, float] = defaultdict(float)
    for a in activities:
        daily[a.start_time.date()] += activity_load(a.duration_s, a.avg_hr, a.rpe, p, a.load_override)[0]
    end = date.today()
    series = load_series(daily, min(daily), end)
    cutoff = end - timedelta(days=days)
    return [
        {"day": s.day, "load": round(s.load, 1), "fitness": round(s.fitness, 1), "fatigue": round(s.fatigue, 1), "form": round(s.form, 1)}
        for s in series
        if s.day > cutoff
    ]


@router.get("/metrics/weekly")
def weekly_metrics(weeks: int = 26, session: Session = Depends(get_session)):
    """Per-week (Monday start) running mileage, run count, total load and average injury pain."""
    start = date.today() - timedelta(weeks=weeks)
    start -= timedelta(days=start.weekday())
    activities = session.exec(select(Activity).where(Activity.start_time >= start)).all()
    p = physiology(session)
    buckets: dict[date, dict] = {}
    for i in range(weeks + 1):
        wk = start + timedelta(weeks=i)
        buckets[wk] = {"week": wk, "miles": 0.0, "runs": 0, "load": 0.0, "pains": []}
    for a in activities:
        wk = a.start_time.date() - timedelta(days=a.start_time.weekday())
        b = buckets.get(wk)
        if b is None:
            continue
        if not a.excluded:
            b["load"] += activity_load(a.duration_s, a.avg_hr, a.rpe, p, a.load_override)[0]
        if is_run(a.activity_type):
            b["miles"] += a.distance_m / MILE_M
            b["runs"] += 1
            if a.pain is not None:
                b["pains"].append(a.pain)
    return [
        {
            "week": b["week"],
            "miles": round(b["miles"], 1),
            "runs": b["runs"],
            "load": round(b["load"]),
            "avg_pain": round(sum(b["pains"]) / len(b["pains"]), 1) if b["pains"] else None,
        }
        for b in buckets.values()
    ]

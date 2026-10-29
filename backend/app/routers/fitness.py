"""Current fitness: the last solid estimate from a training block, carried forward through time off."""

from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.engine.fitness import STEADY_HR_WINDOW, detraining_loss, steady_ref_hr
from app.engine.load import activity_load, load_series
from app.engine.vdot import predict_seconds, vdot
from app.models import MILE_M, Activity, Profile
from app.routers.activities import hr_slope, load_laps, physiology, steady_points
from app.routers.blocks import EQUIVALENTS, all_block_summaries

router = APIRouter(prefix="/api/fitness", tags=["fitness"])

MARATHON_M = 42195
OBSERVED_MIN_M = 3 * MILE_M
OBSERVED_MIN_LAPS = 3


def is_finished_marathon(b: dict) -> bool:
    return bool(b["result"] and b["result"]["status"] == "finished" and b["race"] and abs(b["race"]["distance_m"] - MARATHON_M) < 500)


def window_end(b: dict) -> date:
    return date.fromisoformat(str(b["interrupted_on"])) if b["interrupted_on"] else date.fromisoformat(str(b["end_date"]))


def fitness_from_marathon_speed(speed: float) -> dict:
    v = vdot(MARATHON_M, MARATHON_M / speed)
    return {
        "vdot": round(v, 1),
        "marathon_speed": speed,
        "equivalents": {k: round(predict_seconds(v, d)) for k, d in EQUIVALENTS.items()},
    }


def pre_estimates(subject: dict, blocks: list[dict]) -> list[dict]:
    """Every way we can put a marathon pace on the subject block, best first."""
    out = []
    if is_finished_marathon(subject):
        out.append({"method": "race", "label": f"{subject['race']['name']} result",
                    "marathon_speed": subject["race"]["distance_m"] / subject["result"]["time_s"]})
    est = subject["mp_estimate"]
    if est and est.get("calibrated_speed"):
        out.append({"method": "mp_workouts", "label": f"Marathon-effort workouts, adjusted by {est['calibrated_from']}",
                    "marathon_speed": est["calibrated_speed"]})
    # Steady-pace ratio against the latest earlier finished marathon.
    earlier = [b for b in blocks if is_finished_marathon(b) and b["steady"] and b["end_date"] < subject["end_date"]]
    if subject["steady"] and earlier:
        ref = max(earlier, key=lambda b: b["end_date"])
        ratio = subject["steady"]["speed"] / ref["steady"]["speed"]
        ref_speed = ref["race"]["distance_m"] / ref["result"]["time_s"]
        out.append({
            "method": "steady_ratio",
            "label": f"Steady pace at HR {subject['steady']['ref_hr']} vs {ref['name']}",
            "marathon_speed": ref_speed * ratio,
            "ratio": ratio,
            "reference": ref["name"],
            # Spread from the subject block's interquartile range.
            "low_speed": ref_speed * subject["steady"]["low"] / ref["steady"]["speed"],
            "high_speed": ref_speed * subject["steady"]["high"] / ref["steady"]["speed"],
        })
    return out


def combine(estimates: list[dict]) -> dict:
    """A race result stands on its own; otherwise average the workout-based methods so no single one dominates."""
    if estimates[0]["method"] == "race":
        return estimates[0]
    speeds = [e["marathon_speed"] for e in estimates]
    if len(speeds) == 1:
        return estimates[0]
    bounds = speeds + [e[k] for e in estimates for k in ("low_speed", "high_speed") if k in e]
    return {
        "method": "combined",
        "label": "Average of " + " and ".join(e["label"].split(",")[0].lower() for e in estimates),
        "marathon_speed": sum(speeds) / len(speeds),
        "low_speed": min(bounds),
        "high_speed": max(bounds),
    }


@router.get("/current")
def current_fitness(block_id: int | None = None, session: Session = Depends(get_session)):
    """Start from the most recent block with a usable estimate (or `block_id`) and carry it to today."""
    prof = session.get(Profile, 1)
    today = date.today()
    blocks = all_block_summaries(session)
    candidates = [b for b in blocks if window_end(b) <= today and pre_estimates(b, blocks)]
    if block_id is not None:
        candidates = [b for b in candidates if b["id"] == block_id]
    if not candidates:
        return None
    subject = max(candidates, key=window_end)
    estimates = pre_estimates(subject, blocks)
    pre = {**fitness_from_marathon_speed(combine(estimates)["marathon_speed"]), **combine(estimates)}

    # Time since training stopped (injury) or since race day.
    since = window_end(subject) if subject["interrupted_on"] else window_end(subject) + timedelta(days=1)
    days = (today - since).days

    phys = physiology(session)
    acts = session.exec(select(Activity).where(Activity.excluded == False)).all()  # noqa: E712
    daily: dict[date, float] = defaultdict(float)
    for a in acts:
        daily[a.start_time.date()] += activity_load(a.duration_s, a.avg_hr, a.rpe, phys, a.load_override)[0]
    series = {s.day: s for s in load_series(daily, min(daily), today)} if daily else {}
    fitness_then = series[since - timedelta(days=1)].fitness if since - timedelta(days=1) in series else 0

    def retention_until(d: date) -> float:
        n = (d - since).days + 1
        if n <= 0 or not fitness_then:
            return 1.0
        return sum(daily.get(since + timedelta(days=i), 0) for i in range(n)) / n / fitness_then

    def vdot_on(d: date) -> float:
        return pre["vdot"] * (1 - detraining_loss((d - since).days, retention_until(d)))

    curve = []
    d = since
    while d <= today:
        curve.append({"day": d, "vdot": round(vdot_on(d), 2), "fitness": round(series[d].fitness, 1) if d in series else None})
        d += timedelta(days=7)
    if curve and curve[-1]["day"] != today:
        curve.append({"day": today, "vdot": round(vdot_on(today), 2), "fitness": round(series[today].fitness, 1) if today in series else None})

    retention = retention_until(today)
    loss = detraining_loss(days, retention)
    v_now = pre["vdot"] * (1 - loss)
    now = {
        "vdot": round(v_now, 1),
        "loss": loss,
        "equivalents": {k: round(predict_seconds(v_now, dist)) for k, dist in EQUIVALENTS.items()},
    }

    # Measured check: steady runs since `since`, their laps read through the pre-injury steady marker.
    observed = []
    ref_hr = steady_ref_hr(prof.lthr)
    slope = hr_slope(session)
    if subject["steady"]:
        recent = sorted((a for a in acts if a.start_time.date() >= since and a.distance_m >= OBSERVED_MIN_M), key=lambda a: a.start_time)
        laps = load_laps(session, [a.id for a in recent])
        for a in recent:
            points = [p for p in steady_points(a, laps.get(a.id), prof.lthr) if abs(p.hr - ref_hr) <= STEADY_HR_WINDOW]
            if len(points) < OBSERVED_MIN_LAPS:
                continue
            at_ref = median(p.speed + slope * (ref_hr - p.hr) for p in points)
            ratio = at_ref / subject["steady"]["speed"]
            secs = a.moving_s or a.duration_s
            observed.append({
                "activity_id": a.id, "date": a.start_time.date(), "name": a.name,
                "miles": round(a.distance_m / MILE_M, 1), "speed": a.distance_m / secs, "avg_hr": a.avg_hr,
                "speed_at_ref": at_ref, "ratio": ratio, "laps": len(points),
                # Tapered, cool, adrenaline: race-day runs read fitter than training would.
                "race_day": any(a.start_time.date() == date.fromisoformat(str(b["end_date"])) for b in blocks if b["race"]),
                "vdot": fitness_from_marathon_speed(pre["marathon_speed"] * ratio)["vdot"],
            })

    return {
        "block": {"id": subject["id"], "name": subject["name"], "interrupted_on": subject["interrupted_on"], "end_date": subject["end_date"]},
        "pre": pre,
        "estimates": estimates,
        "since": since,
        "days": days,
        "fitness_then": round(fitness_then, 1),
        "fitness_now": round(series[today].fitness, 1) if today in series else None,
        "retention": round(retention, 2),
        "now": now,
        "curve": curve,
        "observed": observed,
        "ref_hr": ref_hr,
        "hr_slope": slope,
    }

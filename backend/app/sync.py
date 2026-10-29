"""Pull activities from Garmin into the local database."""

import time
from datetime import date, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.garmin_client import get_client
from app.models import Activity, Lap, SyncState

INITIAL_HISTORY_DAYS = 400  # enough to warm up the 42-day fitness average well before today
LAPS_PER_SYNC = 40  # cap Garmin calls per sync; scripts/backfill_laps.py does the rest


def activity_from_garmin(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a Garmin activity summary to Activity's Garmin-sourced fields."""
    return {
        "id": raw["activityId"],
        "start_time": datetime.fromisoformat(raw["startTimeLocal"]),
        "name": raw.get("activityName") or "",
        "activity_type": (raw.get("activityType") or {}).get("typeKey", ""),
        "distance_m": raw.get("distance") or 0,
        "duration_s": raw.get("duration") or 0,
        "moving_s": raw.get("movingDuration"),
        "avg_hr": raw.get("averageHR"),
        "max_hr": raw.get("maxHR"),
        "elevation_gain_m": raw.get("elevationGain"),
        "avg_cadence": raw.get("averageRunningCadenceInStepsPerMinute"),
        "garmin_training_load": raw.get("activityTrainingLoad"),
        "aerobic_te": raw.get("aerobicTrainingEffect"),
        "vo2max": raw.get("vO2MaxValue"),
    }


def upsert_activities(session: Session, raws: list[dict[str, Any]]) -> int:
    new = 0
    for raw in raws:
        fields = activity_from_garmin(raw)
        existing = session.get(Activity, fields["id"])
        if existing is None:
            session.add(Activity(**fields))
            new += 1
        else:
            for k, v in fields.items():
                setattr(existing, k, v)
    session.commit()
    return new


def lap_from_garmin(activity_id: int, raw: dict[str, Any]) -> Lap:
    return Lap(
        activity_id=activity_id,
        lap_index=raw["lapIndex"],
        distance_m=raw.get("distance") or 0,
        duration_s=raw.get("duration") or 0,
        moving_s=raw.get("movingDuration"),
        avg_hr=raw.get("averageHR"),
        max_hr=raw.get("maxHR"),
        intensity=raw.get("intensityType"),
        step_index=raw.get("wktStepIndex"),
    )


def fetch_laps(session: Session, activity_ids: list[int], client=None) -> int:
    """Fetch and cache laps for activities that don't have them yet. Returns how many were fetched."""
    todo = [a for a in (session.get(Activity, i) for i in activity_ids) if a and not a.laps_fetched]
    if not todo:
        return 0
    client = client or get_client()
    for n, activity in enumerate(todo):
        if n:
            time.sleep(0.5)  # be gentle; Garmin rate-limits by IP
        raws = client.get_activity_splits(activity.id).get("lapDTOs") or []
        for raw in raws:
            session.merge(lap_from_garmin(activity.id, raw))
        activity.laps_fetched = True
        session.add(activity)
        session.commit()
    return len(todo)


def run_sync(session: Session, full: bool = False, since: date | None = None) -> dict[str, Any]:
    """Incremental by default; `full` re-pulls ~400 days; `since` backfills from a given date."""
    latest = session.exec(select(Activity).order_by(Activity.start_time.desc())).first()
    if since is not None:
        start = since
    elif latest is None or full:
        start = date.today() - timedelta(days=INITIAL_HISTORY_DAYS)
    else:
        start = latest.start_time.date() - timedelta(days=2)  # re-pull recent days to catch edits

    client = get_client()
    raws = client.get_activities_by_date(start.isoformat(), date.today().isoformat())
    new = upsert_activities(session, raws)

    # Laps tell unnamed runs apart (intervals vs tempo vs easy), so fetch them for recent runs.
    missing = [a.id for a in session.exec(
        select(Activity).where(Activity.activity_type.contains("running"), Activity.laps_fetched == False)  # noqa: E712
        .order_by(Activity.start_time.desc()).limit(LAPS_PER_SYNC)
    ).all()]
    laps = fetch_laps(session, missing, client)

    state = session.get(SyncState, 1)
    state.last_sync = datetime.now()
    state.last_result = f"{len(raws)} fetched, {new} new since {start}; laps for {laps} runs"
    session.add(state)
    session.commit()
    return {"fetched": len(raws), "new": new, "since": start.isoformat(), "laps": laps}

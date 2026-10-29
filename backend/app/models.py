"""Database tables.

Garmin-sourced fields are overwritten on every sync; manual fields (rpe, pain,
notes, load_override, excluded) are never touched by sync.
"""

from datetime import date

from pydantic import NaiveDatetime
from sqlmodel import Field, Session, SQLModel, select


# Each editable table has a *Base model used as the request body. Table models
# skip pydantic validation, so parsing a request straight into one leaves
# "2027-03-21" as a string and SQLite rejects it.


class ProfileBase(SQLModel):
    """The physiology the load engine needs."""

    max_hr: int = 185
    resting_hr: int = 60
    lthr: int = 165  # lactate-threshold heart rate
    sex: str = "male"  # TRIMP weighting: "male" or "female"
    # How much a run's RPE pulls its load away from the HR-based number (0 = ignore RPE, 1 = RPE only).
    rpe_weight: float = 0.3
    injury_focus: str | None = None
    # Average HR you can hold for a marathon; used to turn workout HR/pace into a marathon pace estimate.
    marathon_hr: int = 158
    # Fixed HR for the easy-run aerobic-efficiency trend ("easy pace at 145").
    aerobic_hr: int = 145


class Profile(ProfileBase, table=True):
    id: int = Field(default=1, primary_key=True)  # single row


class Activity(SQLModel, table=True):
    id: int = Field(primary_key=True)  # Garmin activityId
    start_time: NaiveDatetime = Field(index=True)
    name: str = ""
    activity_type: str = Field(default="", index=True)
    distance_m: float = 0
    duration_s: float = 0
    moving_s: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    elevation_gain_m: float | None = None
    avg_cadence: float | None = None
    garmin_training_load: float | None = None
    aerobic_te: float | None = None
    vo2max: float | None = None

    # Manual inputs
    rpe: int | None = None  # 1-10
    pain: int | None = None  # 0-10, injury pain during/after
    notes: str | None = None
    load_override: float | None = None
    excluded: bool = False  # drop from load calculations (e.g. bad HR data)
    workout_type_override: str | None = None  # see engine.workouts.WORKOUT_TYPES
    key_override: bool | None = None  # None = let the classifier decide
    laps_fetched: bool = False


class Lap(SQLModel, table=True):
    """Garmin lap/split, fetched on demand for key workouts."""

    activity_id: int = Field(primary_key=True, foreign_key="activity.id")
    lap_index: int = Field(primary_key=True)
    distance_m: float = 0
    duration_s: float = 0
    moving_s: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    intensity: str | None = None  # WARMUP / ACTIVE / INTERVAL / REST / RECOVERY / COOLDOWN, None if unstructured
    step_index: int | None = None  # structured-workout step the lap belongs to


class DailyLogBase(SQLModel):
    """One day of manual wellness / rehab input."""

    pain_morning: int | None = None  # 0-10 injury pain on waking / first steps
    soreness: int | None = None  # 0-10 general muscle soreness
    sleep_quality: int | None = None  # 1-5
    calf_raises_left: int | None = None  # single-leg calf raise reps to fatigue
    calf_raises_right: int | None = None
    rehab_done: bool = False
    notes: str | None = None


class DailyLog(DailyLogBase, table=True):
    day: date = Field(primary_key=True)


class RaceBase(SQLModel):
    name: str
    race_date: date | None = None
    distance_m: float
    priority: str = "A"  # A / B / C
    goal_time_s: int | None = None
    result_time_s: int | None = None
    status: str | None = None  # None = finished / upcoming; "dnf" or "dns"
    notes: str | None = None


class Race(RaceBase, table=True):
    id: int | None = Field(default=None, primary_key=True)


class BlockBase(SQLModel):
    """A training block: the build into a race (or any date range you want to study)."""

    name: str
    start_date: date
    end_date: date  # usually race day
    race_id: int | None = Field(default=None, foreign_key="race.id")
    # First day training was knocked out (injury/illness). Fitness estimates use only data before it.
    interrupted_on: date | None = None
    notes: str | None = None


class Block(BlockBase, table=True):
    id: int | None = Field(default=None, primary_key=True)


class SyncState(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    last_sync: NaiveDatetime | None = None
    last_result: str | None = None


MILE_M = 1609.344



def seed_defaults(session: Session) -> None:
    if session.get(Profile, 1) is None:
        session.add(Profile())
    if session.get(SyncState, 1) is None:
        session.add(SyncState())
    session.commit()

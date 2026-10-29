"""Spoken run recaps: a short, speech-friendly summary of one run.

Pure functions only. routers/voice.py gathers the data; app/voice.py turns the text into audio.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.engine.workouts import WorkSummary
from app.models import MILE_M

TYPE_SPOKEN = {
    "race": "race", "race_practice": "race-practice run", "long": "long run", "tempo": "tempo run",
    "intervals": "interval session", "workout": "workout", "easy": "easy run",
}
SAME_PACE_S = 3  # within this many seconds per mile of the average counts as "in line"


@dataclass
class RecapInput:
    day: date
    today: date
    workout_type: str | None
    distance_m: float
    seconds: float  # moving time when known
    avg_hr: float | None
    load: float
    week_miles: float  # the run's Monday-start week, up to and including this run
    work: WorkSummary | None = None
    similar_speeds: list[float] = field(default_factory=list)  # same-type runs of similar length, last 8 weeks
    pain: int | None = None
    notes: str | None = None


def spoken_duration(s: float) -> str:
    """3125 -> "52 minutes 5 seconds"; seconds are dropped once there are hours."""
    s = round(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    unit = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"  # noqa: E731
    parts = [unit(h, "hour")] if h else []
    if m:
        parts.append(unit(m, "minute"))
    if sec and not h:
        parts.append(unit(sec, "second"))
    return " ".join(parts) or "0 seconds"


def spoken_pace(speed: float) -> str:
    """m/s -> "7:12 per mile"."""
    s = round(MILE_M / speed)
    return f"{s // 60}:{s % 60:02d} per mile"


def _when(day: date, today: date) -> str:
    days = (today - day).days
    if days == 0:
        return "Today's"
    if days == 1:
        return "Yesterday's"
    if 1 < days < 7:
        return f"{day:%A}'s"
    return f"The {day:%B} {day.day}"


def run_recap(r: RecapInput) -> str:
    kind = TYPE_SPOKEN.get(r.workout_type or "", "run")
    speed = r.distance_m / r.seconds if r.seconds else 0
    hr = f" at an average heart rate of {round(r.avg_hr)}" if r.avg_hr else ""
    out = [f"{_when(r.day, r.today)} {kind}: {r.distance_m / MILE_M:.1f} miles in {spoken_duration(r.seconds)}"
           + (f", averaging {spoken_pace(speed)}" if speed else "") + f"{hr}."]

    w = r.work
    if w and w.speed and r.workout_type not in ("easy", "long"):
        if w.intervals and w.reps >= 2:
            out.append(f"The work was {w.reps} reps averaging {spoken_pace(w.speed)}.")
        elif w.distance_m < 0.9 * r.distance_m:
            out.append(f"The hard part was {w.distance_m / MILE_M:.1f} miles at {spoken_pace(w.speed)}.")

    if speed and len(r.similar_speeds) >= 2:
        avg = sum(r.similar_speeds) / len(r.similar_speeds)
        diff = round(MILE_M / avg - MILE_M / speed)  # positive = faster than usual
        n = len(r.similar_speeds)
        if speed > max(r.similar_speeds):
            out.append(f"That's your fastest of {n + 1} similar runs in the last 8 weeks.")
        elif abs(diff) < SAME_PACE_S:
            out.append("That's right in line with your similar runs over the last 8 weeks.")
        else:
            out.append(f"That's {abs(diff)} seconds per mile {'faster' if diff > 0 else 'slower'} "
                       "than your average for similar runs over the last 8 weeks.")

    monday = lambda d: d - timedelta(days=d.weekday())  # noqa: E731
    this_week = monday(r.day) == monday(r.today)
    out.append(f"Training load {round(r.load)}, with {r.week_miles:.1f} miles so far {'this' if this_week else 'that'} week.")

    if r.pain is not None and r.pain >= 4:
        out.append(f"You logged pain at {r.pain} out of 10, so keep an eye on it.")
    elif r.notes:
        out.append(f"Your note: {r.notes.strip().rstrip('.')}.")
    return " ".join(out)

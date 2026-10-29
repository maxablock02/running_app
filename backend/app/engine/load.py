"""Training load: per-activity stress scores and the fitness / fatigue / form model.

Scale: 100 points ~= one hour at lactate-threshold heart rate (same scale as
TrainingPeaks TSS, so numbers will feel familiar).

Per-activity load, in priority order:
  1. load_override (you said so)
  2. HR-based TRIMP, blended toward session-RPE load by profile.rpe_weight when RPE exists
  3. session-RPE alone (no HR, e.g. strength or treadmill without strap)
  4. nothing -> 0
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

CTL_DAYS = 42  # fitness time constant
ATL_DAYS = 7  # fatigue time constant

# sRPE load (RPE x minutes) for one hour at threshold, roughly RPE 7 x 60.
SRPE_PER_THRESHOLD_HOUR = 7 * 60


@dataclass
class Physiology:
    max_hr: int
    resting_hr: int
    lthr: int
    sex: str = "male"
    rpe_weight: float = 0.3


def _trimp_per_minute(hr: float, p: Physiology) -> float:
    """Banister TRIMP per minute at a given heart rate."""
    hrr = (hr - p.resting_hr) / (p.max_hr - p.resting_hr)
    hrr = min(max(hrr, 0.0), 1.0)
    b = 1.67 if p.sex == "female" else 1.92
    return hrr * 0.64 * math.exp(b * hrr)


def hr_load(duration_s: float, avg_hr: float, p: Physiology) -> float:
    """TRIMP normalised so an hour at LTHR = 100."""
    threshold_hour = 60 * _trimp_per_minute(p.lthr, p)
    return 100 * (duration_s / 60) * _trimp_per_minute(avg_hr, p) / threshold_hour


def rpe_load(duration_s: float, rpe: int) -> float:
    return 100 * rpe * (duration_s / 60) / SRPE_PER_THRESHOLD_HOUR


def activity_load(
    duration_s: float,
    avg_hr: float | None,
    rpe: int | None,
    p: Physiology,
    load_override: float | None = None,
) -> tuple[float, str]:
    """Return (load, source) where source says which method produced it."""
    if load_override is not None:
        return load_override, "override"
    if avg_hr:
        hr = hr_load(duration_s, avg_hr, p)
        if rpe:
            w = p.rpe_weight
            return (1 - w) * hr + w * rpe_load(duration_s, rpe), "hr+rpe"
        return hr, "hr"
    if rpe:
        return rpe_load(duration_s, rpe), "rpe"
    return 0.0, "none"


@dataclass
class DayLoad:
    day: date
    load: float
    fitness: float  # CTL
    fatigue: float  # ATL
    form: float  # TSB = yesterday's fitness - yesterday's fatigue (how fresh you are today)


def load_series(daily_loads: dict[date, float], start: date, end: date) -> list[DayLoad]:
    """Exponentially weighted fitness/fatigue from a {day: total load} map, one row per day."""
    k_ctl = 1 - math.exp(-1 / CTL_DAYS)
    k_atl = 1 - math.exp(-1 / ATL_DAYS)
    ctl = atl = 0.0
    out: list[DayLoad] = []
    d = start
    while d <= end:
        form = ctl - atl
        load = daily_loads.get(d, 0.0)
        ctl += k_ctl * (load - ctl)
        atl += k_atl * (load - atl)
        out.append(DayLoad(d, load, ctl, atl, form))
        d += timedelta(days=1)
    return out

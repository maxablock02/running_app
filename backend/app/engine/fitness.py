"""Fitness markers that can be compared across blocks, and detraining after time off.

Pace vs HR: from your own steady laps, speed rises roughly linearly with HR.
fit_hr_slope() measures that slope (m/s per bpm); everything that converts a
pace at one HR to another HR uses it.

Steady-pace marker: median of steady laps, each shifted to one reference HR
along that slope. Faster at the same HR = fitter. Laps (not whole runs) so the
warm-up mile, stops and drift don't blur it. Comparing two blocks' markers gives
a speed ratio, which turns a known marathon result in one block into an estimate
for the other.

Detraining: VO2max falls roughly 7% after 3 weeks and ~16% after 8 weeks of no
training (Coyle et al. 1984), levelling off after that. Cross-training and any
running that continues hold some of it; the loss is scaled down by how much of
the pre-injury training load you've kept up. These are population averages:
treat the output as a ballpark and check it against real runs when you have them.
"""

import math
from dataclasses import dataclass
from statistics import median

STEADY_LAP_M = (1500, 1700)  # auto mile laps (km auto-laps are handled by the caller)
STEADY_HR_WINDOW = 15  # laps within this many bpm of the reference HR count
STEADY_REF_HR_FRAC = 0.85  # reference HR = 85% of LTHR (a steady aerobic effort)
MIN_STEADY_LAPS = 10

# Plausible bounds for the fitted slope (m/s per bpm); outside them, use the default.
SLOPE_RANGE = (0.010, 0.040)
DEFAULT_SLOPE = 0.023
MIN_SLOPE_POINTS = 50

DETRAIN_MAX_LOSS = 0.18
DETRAIN_TAU_DAYS = 45
# Share of the detraining loss that fully maintained load (retention = 1) prevents.
RETENTION_PROTECTION = 0.6


def steady_ref_hr(lthr: int) -> int:
    return round(STEADY_REF_HR_FRAC * lthr)


@dataclass
class LapPoint:
    speed: float  # m/s
    hr: float


def fit_hr_slope(points: list[LapPoint]) -> float:
    """Least-squares slope of speed on HR across steady laps; DEFAULT_SLOPE if too few or implausible."""
    if len(points) < MIN_SLOPE_POINTS:
        return DEFAULT_SLOPE
    mx = sum(p.hr for p in points) / len(points)
    my = sum(p.speed for p in points) / len(points)
    var = sum((p.hr - mx) ** 2 for p in points)
    if not var:
        return DEFAULT_SLOPE
    slope = sum((p.hr - mx) * (p.speed - my) for p in points) / var
    return slope if SLOPE_RANGE[0] <= slope <= SLOPE_RANGE[1] else DEFAULT_SLOPE


@dataclass
class SteadyMarker:
    ref_hr: int
    speed: float  # median m/s at ref_hr
    low: float  # interquartile range of the per-lap speeds
    high: float
    laps: int


def steady_marker(points: list[LapPoint], ref_hr: int, slope: float) -> SteadyMarker | None:
    speeds = sorted(p.speed + slope * (ref_hr - p.hr) for p in points if abs(p.hr - ref_hr) <= STEADY_HR_WINDOW)
    if len(speeds) < MIN_STEADY_LAPS:
        return None
    return SteadyMarker(ref_hr, median(speeds), speeds[len(speeds) // 4], speeds[(3 * len(speeds)) // 4], len(speeds))


def detraining_loss(days: int, retention: float) -> float:
    """Fractional VDOT loss after `days` off, given retained load share (0 = complete rest, 1 = fully maintained)."""
    if days <= 0:
        return 0.0
    retention = min(max(retention, 0.0), 1.0)
    base = DETRAIN_MAX_LOSS * (1 - math.exp(-days / DETRAIN_TAU_DAYS))
    return base * (1 - RETENTION_PROTECTION * retention)

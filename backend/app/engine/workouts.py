"""Workout classification and lap analysis.

Classification, in order of trust:
  1. the Garmin activity name, when it came from a structured plan workout
     ("Build - W8 Sat Long Run - 19mi Race Practice")
  2. race distance + race-level heart rate
  3. lap structure of unnamed runs: lap-button reps and rests, or a block of
     clearly faster miles inside auto mile laps (infer_structure)
  4. distance and average heart rate relative to threshold
"""

import re
from dataclasses import dataclass, replace

MILE_M = 1609.344

WORKOUT_TYPES = ["race", "race_practice", "long", "tempo", "intervals", "workout", "easy"]
KEY_TYPES = {"race", "race_practice", "tempo", "intervals", "workout"}
KEY_LONG_RUN_MI = 14

# Standard race distances (m) and the minimum share of LTHR a full race effort averages.
RACE_DISTANCES = [(5000, 0.97), (8000, 0.97), (10000, 0.97), (21097.5, 0.95), (42195, 0.90)]

_PLAN_NAME = re.compile(r"\bW\d+\s+\w{3}\s+(?P<kind>[^-]+?)(?:\s+#\d+)?\s+-", re.IGNORECASE)


def is_race_distance(distance_m: float) -> float | None:
    """The standard distance this run matches (within GPS slop), if any."""
    for d, _ in RACE_DISTANCES:
        if d * 0.98 <= distance_m <= d * 1.04:
            return d
    return None


def classify(name: str, distance_m: float, avg_hr: float | None, lthr: int, laps: list["LapData"] | None = None) -> str:
    lname = name.lower()
    # Garmin truncates names, so "Race Practice" can arrive as "Race Pra".
    if re.search(r"race pra|race pace", lname):
        return "race_practice"
    m = _PLAN_NAME.search(name)
    if m:
        kind = m.group("kind").lower()
        for word, t in (("long", "long"), ("tempo", "tempo"), ("interval", "intervals"), ("easy", "easy"), ("recovery", "easy")):
            if word in kind:
                return t
        return "workout"

    hr_frac = (avg_hr or 0) / lthr
    std = is_race_distance(distance_m)
    if std is not None and hr_frac >= dict(RACE_DISTANCES)[std]:
        return "race"

    if laps and is_unstructured(laps):
        s = infer_structure(laps, lthr)  # walk/run and strides fail its HR / distance guards
        work = summarize(s.laps)
        if s.kind == "intervals" and work:
            return "intervals"
        if s.kind == "segment" and work:
            seg_mi = work.distance_m / MILE_M
            if distance_m >= 13 * MILE_M and seg_mi >= 3:
                return "race_practice"
            if seg_mi >= 2:
                return "tempo"

    if distance_m >= 13 * MILE_M:
        return "long"
    if hr_frac >= 0.88:
        return "workout"
    return "easy"


def is_key(workout_type: str, distance_m: float) -> bool:
    return workout_type in KEY_TYPES or (workout_type == "long" and distance_m >= KEY_LONG_RUN_MI * MILE_M)


# --- Laps --------------------------------------------------------------------

@dataclass
class LapData:
    lap_index: int
    distance_m: float
    duration_s: float
    avg_hr: float | None
    intensity: str | None
    step_index: int | None
    max_hr: float | None = None

    @property
    def speed(self) -> float:
        return self.distance_m / self.duration_s if self.duration_s else 0.0


NON_WORK = {"WARMUP", "COOLDOWN", "REST", "RECOVERY"}
MIN_LAP_M = 150  # ignore lap-button blips
MIN_REST_S = 20  # a short lap that lasted this long is a standing recovery, not a blip

AUTO_LAP_DISTANCES = (MILE_M, 1000.0)
# Manual laps: a pace gap of 12%+ between the faster and slower laps means reps vs recoveries.
REP_GAP = 1.12
# Auto laps: 2+ consecutive splits this much faster than the run's easy splits form a segment.
SEGMENT_SPEEDUP = 1.07
LONG_RUN_M = 13 * MILE_M
# Guards against false positives (a stop mid-run, a few quicker easy miles, strides):
MAX_WORK_SHARE = 0.80  # "reps" covering more than this share of the run means it was a steady run
HARD_HR_FRAC = 0.86  # work must average at least this share of LTHR...
HARD_PEAK_HR_FRAC = 0.90  # ...or, for short reps where HR lags, peak at this share
MIN_INTERVAL_WORK_M = MILE_M  # less total rep distance than this is strides


def is_unstructured(laps: list[LapData]) -> bool:
    """Not a watch workout: only auto laps and/or lap-button presses.

    Plan workouts always carry step indexes. Newer Garmin recordings tag plain
    auto laps as INTERVAL/ACTIVE, so the intensity alone doesn't mean structure;
    only warm-up / rest / cool-down tags do.
    """
    return all(l.step_index is None for l in laps) and not any(l.intensity in NON_WORK for l in laps)


@dataclass
class Structure:
    kind: str | None  # "intervals", "segment" (one continuous faster block), or None (steady)
    laps: list[LapData]  # copies tagged WARMUP / ACTIVE / REST / COOLDOWN


def _is_auto_lapped(laps: list[LapData]) -> bool:
    body = laps[:-1]  # the last lap is whatever was left over
    return any(
        all(abs(l.distance_m - d) <= 0.02 * d for l in body)
        for d in AUTO_LAP_DISTANCES
    )


def _tag(laps: list[LapData], active: set[int], between: str) -> list[LapData]:
    """ACTIVE for active laps; before the first = WARMUP, after the last = COOLDOWN, in between = `between`."""
    if not active:
        return [replace(l, intensity="ACTIVE") for l in laps]
    first, last = min(active), max(active)
    out = []
    for i, l in enumerate(laps):
        role = "ACTIVE" if i in active else "WARMUP" if i < first else "COOLDOWN" if i > last else between
        out.append(replace(l, intensity=role))
    return out


def _plausible_work(laps: list[LapData], work: set[int], moving: list[int], lthr: int | None, use_peak: bool) -> bool:
    """Is this candidate 'work' a real workout effort rather than an artifact of how the laps fell?"""
    total = sum(laps[i].distance_m for i in moving)
    work_m = sum(laps[i].distance_m for i in work)
    if work_m > MAX_WORK_SHARE * total:
        return False
    if lthr is None:
        return True
    timed = [laps[i] for i in work if laps[i].avg_hr]
    if not timed:
        return True
    avg_hr = sum(l.avg_hr * l.duration_s for l in timed) / sum(l.duration_s for l in timed)
    if avg_hr >= HARD_HR_FRAC * lthr:
        return True
    peaks = [l.max_hr for l in timed if l.max_hr]
    return use_peak and bool(peaks) and sum(peaks) / len(peaks) >= HARD_PEAK_HR_FRAC * lthr


def infer_structure(laps: list[LapData], lthr: int | None = None) -> Structure:
    """Recover workout structure from an unnamed run's laps.

    With lthr, candidate work must also look hard by heart rate; without it
    (e.g. when only re-tagging laps for display) the pace pattern alone decides.
    """
    steady = Structure(None, _tag(laps, set(), "ACTIVE"))
    moving = [i for i, l in enumerate(laps) if l.distance_m >= MIN_LAP_M]
    if len(moving) < 3:
        return steady

    if not _is_auto_lapped([laps[i] for i in moving]):
        # Lap-button presses: split laps into fast and slow at the biggest pace gap.
        speeds = sorted(laps[i].speed for i in moving)
        ratios = [(speeds[k + 1] / speeds[k], k) for k in range(len(speeds) - 1) if speeds[k] > 0]
        gap, k = max(ratios, default=(1.0, 0))
        if gap < REP_GAP:
            return steady
        cut = speeds[k + 1]
        fast = {i for i in moving if laps[i].speed >= cut}
        # Short stationary laps between reps are rests too.
        tagged = _tag(laps, fast, "REST")
        reps_with_rest = len(fast) >= 2 and any(
            t.intensity == "REST" and (t.distance_m >= MIN_LAP_M or t.duration_s >= MIN_REST_S) for t in tagged
        )
        if not _plausible_work(laps, fast, moving, lthr, use_peak=reps_with_rest):
            return steady
        if reps_with_rest and sum(laps[i].distance_m for i in fast) < MIN_INTERVAL_WORK_M:
            return steady  # strides
        return Structure("intervals" if reps_with_rest else "segment", tagged)

    # Auto laps: look for the longest stretch of clearly faster splits.
    slower_half = sorted(laps[i].speed for i in moving)[: max(1, len(moving) // 2)]
    easy_ref = slower_half[len(slower_half) // 2]
    best: list[int] = []
    run: list[int] = []
    for i in moving:
        if laps[i].speed >= SEGMENT_SPEEDUP * easy_ref:
            run.append(i)
            best = max(best, run, key=len)
        else:
            run = []
    # In a long run, a 2-mile pickup is noise; it takes 3+ miles to be a planned segment.
    min_laps = 3 if sum(laps[i].distance_m for i in moving) >= LONG_RUN_M else 2
    if len(best) >= min_laps and _plausible_work(laps, set(best), moving, lthr, use_peak=False):
        return Structure("segment", _tag(laps, set(best), "ACTIVE"))
    return steady


def work_laps(laps: list[LapData], lthr: int | None = None) -> list[LapData]:
    """The 'work' part of a run.

    Structured workouts: drop warm-up / cool-down / rest laps. A continuous
    structured run (no rest laps, e.g. 4 mi easy then 13 mi at marathon pace,
    all tagged ACTIVE) keeps only the steps within 5% of the fastest step.
    Interval sessions (with rest laps) keep every active rep, so the slower
    long reps of a pyramid still count.
    Unstructured runs: infer_structure() tags the laps first; a steady run is all work.
    """
    if laps and is_unstructured(laps):
        laps = infer_structure(laps, lthr).laps
    # Check for rest laps before dropping short laps: standing recoveries are often < MIN_LAP_M.
    has_rest = any(lap.intensity in ("REST", "RECOVERY") for lap in laps)
    laps = [lap for lap in laps if lap.distance_m >= MIN_LAP_M]
    work = [lap for lap in laps if (lap.intensity or "ACTIVE") not in NON_WORK]
    steps: dict[int, list[LapData]] = {}
    for lap in work:
        if lap.step_index is not None:
            steps.setdefault(lap.step_index, []).append(lap)
    if len(steps) > 1 and not has_rest:
        speed = {s: sum(l.distance_m for l in ls) / sum(l.duration_s for l in ls) for s, ls in steps.items()}
        fastest = max(speed.values())
        keep = {s for s, v in speed.items() if v >= 0.95 * fastest}
        work = [lap for lap in work if lap.step_index in keep]
    return work


@dataclass
class WorkSummary:
    reps: int  # number of work laps
    distance_m: float
    duration_s: float
    avg_hr: float | None
    # True for interval-style work (rest laps between reps); False for one continuous effort,
    # which may still span several laps (auto mile-splits, or consecutive marathon-pace miles).
    intervals: bool = False

    @property
    def speed(self) -> float:
        return self.distance_m / self.duration_s if self.duration_s else 0.0


def summarize(laps: list[LapData], lthr: int | None = None) -> WorkSummary | None:
    """Work summary; pass lthr so unnamed runs get the same HR guards as classify()."""
    if laps and is_unstructured(laps):
        laps = infer_structure(laps, lthr).laps
    work = work_laps(laps)
    if not work:
        return None
    dist = sum(l.distance_m for l in work)
    dur = sum(l.duration_s for l in work)
    hr_laps = [l for l in work if l.avg_hr]
    hr = sum(l.avg_hr * l.duration_s for l in hr_laps) / sum(l.duration_s for l in hr_laps) if hr_laps else None
    intervals = any(l.intensity in ("REST", "RECOVERY") for l in laps)
    return WorkSummary(len(work), dist, dur, hr, intervals)


# --- HR-scaled pace ----------------------------------------------------------

def speed_at_hr(speed: float, avg_hr: float, target_hr: float, resting_hr: float, slope: float | None = None) -> float:
    """Scale a speed to a different HR.

    With `slope` (m/s per bpm, fitted from your own laps; see engine.fitness.fit_hr_slope)
    the shift is linear: speed + slope * (target - avg). Without it, falls back to
    speed ~ heart-rate reserve, which overstates the change for most runners
    (~31 vs a measured ~23 mm/s per bpm here). Either way, keep gaps under ~15 bpm.
    """
    if slope is not None:
        return speed + slope * (target_hr - avg_hr)
    if avg_hr <= resting_hr:
        return speed
    return speed * (target_hr - resting_hr) / (avg_hr - resting_hr)

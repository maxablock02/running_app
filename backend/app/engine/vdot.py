"""Jack Daniels' VDOT: a race result -> an effective VO2max -> equivalent times and training paces."""

import math


def _vo2(speed_m_min: float) -> float:
    return -4.60 + 0.182258 * speed_m_min + 0.000104 * speed_m_min**2


def _pct_max(minutes: float) -> float:
    return 0.8 + 0.1894393 * math.exp(-0.012778 * minutes) + 0.2989558 * math.exp(-0.1932605 * minutes)


def vdot(distance_m: float, seconds: float) -> float:
    minutes = seconds / 60
    return _vo2(distance_m / minutes) / _pct_max(minutes)


def predict_seconds(vdot_value: float, distance_m: float) -> float:
    """Race time at a distance for a given VDOT (bisection; vdot() is monotonic in time)."""
    lo, hi = 60.0, 60 * 60 * 10.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if vdot(distance_m, mid) > vdot_value:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def speed_at_vo2_fraction(vdot_value: float, fraction: float) -> float:
    """Speed (m/s) at which oxygen cost = fraction x VDOT (inverts the VO2 cost curve)."""
    target = fraction * vdot_value
    a, b, c = 0.000104, 0.182258, -4.60 - target
    v_m_min = (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)
    return v_m_min / 60


# Daniels' training intensities as fractions of VDOT (midpoints of his ranges).
TRAINING_ZONES = {"easy": 0.70, "threshold": 0.88, "interval": 0.975, "repetition": 1.05}


def training_paces(vdot_value: float) -> dict[str, float]:
    """Speeds in m/s; marathon pace comes from the marathon prediction, not a fixed fraction."""
    paces = {k: speed_at_vo2_fraction(vdot_value, f) for k, f in TRAINING_ZONES.items()}
    paces["marathon"] = 42195 / predict_seconds(vdot_value, 42195)
    return paces

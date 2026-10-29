from datetime import date, timedelta

import pytest

from app.engine.load import Physiology, activity_load, hr_load, load_series, rpe_load

P = Physiology(max_hr=185, resting_hr=60, lthr=165, rpe_weight=0.3)


def test_hour_at_threshold_is_100():
    assert hr_load(3600, 165, P) == pytest.approx(100)
    assert rpe_load(3600, 7) == pytest.approx(100)


def test_easy_run_scores_well_below_threshold():
    assert 30 < hr_load(3600, 140, P) < 60


def test_rpe_pulls_hr_load_up_when_it_felt_hard():
    hr_only, _ = activity_load(3600, 140, None, P)
    blended, src = activity_load(3600, 140, 9, P)
    assert src == "hr+rpe"
    assert blended > hr_only


def test_override_wins_and_missing_data_is_zero():
    assert activity_load(3600, 150, 5, P, load_override=42) == (42, "override")
    assert activity_load(3600, None, None, P) == (0.0, "none")
    assert activity_load(1800, None, 6, P)[1] == "rpe"


def test_constant_load_converges_and_form_goes_negative_on_ramp():
    start = date(2026, 1, 1)
    days = {start + timedelta(days=i): 50.0 for i in range(300)}
    series = load_series(days, start, start + timedelta(days=299))
    assert series[-1].fitness == pytest.approx(50, abs=0.1)
    assert series[-1].fatigue == pytest.approx(50, abs=0.1)
    # After a sudden jump in load, fatigue outruns fitness.
    assert series[10].form < 0

import pytest

from app.engine.vdot import predict_seconds, training_paces, vdot
from app.engine.workouts import LapData, classify, infer_structure, is_key, speed_at_hr, summarize

LTHR = 183
MI = 1609.344


@pytest.mark.parametrize(
    "name,miles,hr,expected",
    [
        ("Build - W8 Sat Long Run - 19mi Race Practice", 19, 158, "race_practice"),
        ("Build - W11 Sat Long Run - 22mi Race Pra", 15, 158, "race_practice"),  # truncated by Garmin
        ("Build - W11 Wed Intervals - 600m Madness", 6.7, 146, "intervals"),
        ("Build - W9 Tue Tempo - Tempo 2 Miles (8mi)", 8.2, 159, "tempo"),
        ("Build - W8 Fri Easy Run #2 - 8mi Easy Run", 8, 142, "easy"),
        ("Build - W12 Sun Long Run - 20mi Long Run", 20, 160, "long"),
        ("Morning Run", 26.5, 173, "race"),  # marathon
        ("Morning Run", 6.24, 191, "race"),  # 10K
        ("Morning Run", 6.24, 150, "easy"),
        ("Morning Run", 18, 154, "long"),
        ("Montgomery County Running", 7, 168, "workout"),
    ],
)
def test_classify(name, miles, hr, expected):
    assert classify(name, miles * MI, hr, LTHR) == expected


def test_key_rules():
    assert is_key("tempo", 5 * MI)
    assert is_key("long", 16 * MI)
    assert not is_key("long", 13 * MI)
    assert not is_key("easy", 10 * MI)


def test_vdot_matches_daniels_tables():
    # Daniels: VDOT 50 ~ 19:57 5K and ~3:10:49 marathon.
    assert vdot(5000, 19 * 60 + 57) == pytest.approx(50, abs=0.2)
    assert predict_seconds(50, 42195) == pytest.approx(3 * 3600 + 10 * 60 + 49, abs=60)
    p = training_paces(50)
    assert p["easy"] < p["marathon"] < p["threshold"] < p["interval"] < p["repetition"]


def lap(i, miles, secs, hr, intensity=None, step=None):
    return LapData(i, miles * MI, secs, hr, intensity, step)


def test_race_practice_keeps_only_marathon_pace_step():
    laps = [lap(i, 1, 520, 145, "ACTIVE", 0) for i in range(4)] + [lap(4 + i, 1, 430, 168, "ACTIVE", 1) for i in range(13)]
    s = summarize(laps)
    assert s.reps == 13 and s.avg_hr == pytest.approx(168)
    assert s.distance_m / s.duration_s == pytest.approx(MI / 430)


def test_intervals_drop_warmup_rest_and_blips():
    laps = [lap(0, 2, 1000, 145, "WARMUP", 0)]
    for i in range(6):
        laps += [lap(1 + 2 * i, 0.37, 134, 155, "ACTIVE", 2), lap(2 + 2 * i, 0.05, 90, 140, "REST", 3)]
    laps += [lap(20, 0.01, 30, 120, "ACTIVE", 2), lap(21, 1, 540, 140, "COOLDOWN", 9)]
    s = summarize(laps)
    assert s.reps == 6


def test_pyramid_keeps_slower_long_reps():
    # 400 / 800 / 1200 / 800 / 400, each its own plan step, faster on the short reps.
    reps = [(0.25, 85), (0.5, 180), (0.75, 285), (0.5, 180), (0.25, 85)]
    laps = [lap(0, 2, 1000, 145, "WARMUP", 0)]
    for i, (mi, secs) in enumerate(reps):
        # Standing recoveries: shorter than the lap-blip cutoff.
        laps += [lap(1 + 2 * i, mi, secs, 160, "ACTIVE", 1 + 2 * i), lap(2 + 2 * i, 0.06, 90, 140, "REST", 2 + 2 * i)]
    s = summarize(laps)
    assert s.reps == 5 and s.intervals
    assert s.distance_m == pytest.approx(2.25 * MI)


def test_unstructured_run_is_all_work():
    s = summarize([lap(i, 1, 500, 150) for i in range(10)])
    assert s.reps == 10 and not s.intervals


def miles(*paces_hr):
    """Auto mile laps from (secs_per_mile, hr) pairs."""
    return [lap(i, 1, p, hr) for i, (p, hr) in enumerate(paces_hr)]


def test_steady_auto_laps_have_no_structure():
    laps = miles(*[(480 + (i % 3) * 6, 150) for i in range(10)])
    assert infer_structure(laps).kind is None
    assert classify("Morning Run", 10 * MI, 150, LTHR, laps) == "easy"
    assert summarize(laps).distance_m == pytest.approx(10 * MI)


def test_tempo_inside_auto_laps():
    # 2 easy, 4 at tempo, 1 easy.
    laps = miles((500, 140), (495, 145), (360, 170), (355, 172), (350, 174), (352, 175), (505, 150))
    assert classify("Morning Run", 7 * MI, 160, LTHR, laps) == "tempo"
    s = summarize(laps)
    assert s.reps == 4 and not s.intervals and s.avg_hr == pytest.approx(172.75, abs=0.1)  # time-weighted


def test_marathon_pace_block_in_unnamed_long_run_is_race_practice():
    laps = miles(*[(510, 145)] * 6, *[(435, 168)] * 8, (520, 150))
    assert classify("Morning Run", 15 * MI, 156, LTHR, laps) == "race_practice"
    assert summarize(laps).distance_m == pytest.approx(8 * MI)


def test_auto_laps_tagged_interval_are_still_unstructured():
    # Newer Garmin files tag every auto lap INTERVAL on a plain run.
    paces = [508, 496, 511, 511, 510, 512, 505, 441, 426, 431, 448, 446, 446, 446, 433, 531]
    hrs = [130, 139, 140, 144, 143, 147, 145, 151, 161, 158, 162, 164, 163, 169, 170, 154]
    laps = [LapData(i, MI, p, h, "INTERVAL", None) for i, (p, h) in enumerate(zip(paces, hrs))]
    assert classify("Morning Run", 16.5 * MI, 152, LTHR, laps) == "race_practice"
    s = summarize(laps, LTHR)
    assert s.distance_m == pytest.approx(8 * MI)  # miles 8-15


def test_fast_finish_long_run_stays_long():
    laps = miles(*[(500, 150)] * 14, (450, 165))
    assert classify("Morning Run", 15 * MI, 151, LTHR, laps) == "long"


def test_two_quick_miles_in_a_long_run_stay_long():
    laps = miles((460, 165), (455, 168), *[(495, 162)] * 14)
    assert classify("Morning Run", 16 * MI, 163, LTHR, laps) == "long"
    assert summarize(laps, LTHR).distance_m == pytest.approx(16 * MI)  # whole run is the work


def test_lap_button_intervals():
    # 1.5 mi warm-up, 6 x 800 m with 90 s standing rest, 1 mi cool-down.
    laps = [lap(0, 1.5, 780, 140)]
    for i in range(6):
        laps += [lap(1 + 2 * i, 0.5, 180, 168), lap(2 + 2 * i, 0.02, 90, 130)]
    laps += [lap(20, 1, 540, 145)]
    assert classify("Morning Run", 5.6 * MI, 155, LTHR, laps) == "intervals"
    s = summarize(laps)
    assert s.reps == 6 and s.intervals
    assert s.distance_m == pytest.approx(3 * MI)


def test_lap_button_tempo():
    laps = [lap(0, 1.5, 780, 140), lap(1, 4, 4 * 400, 172), lap(2, 1, 540, 150)]
    assert classify("Morning Run", 6.5 * MI, 160, LTHR, laps) == "tempo"
    assert summarize(laps).distance_m == pytest.approx(4 * MI)


def test_walk_run_is_easy():
    # Rehab: 0.16 mi jog / 0.11 mi walk, low HR.
    laps = []
    for i in range(5):
        laps += [lap(2 * i, 0.16, 0.16 * 580, 122), lap(2 * i + 1, 0.11, 0.11 * 1060, 112)]
    assert classify("Morning Run", 1.4 * MI, 116, LTHR, laps) == "easy"


def test_stop_mid_run_is_not_intervals():
    # Steady 8:35 laps of odd lengths with one slow (stopped / walked) lap.
    laps = [lap(i, 0.9, 0.9 * 515, 152) for i in range(11)]
    laps.insert(5, lap(99, 0.2, 0.2 * 900, 120))
    assert classify("Morning Run", 10.1 * MI, 150, LTHR, laps) == "easy"


def test_slightly_quicker_easy_miles_are_not_tempo():
    laps = miles((540, 145), (535, 148), (495, 154), (493, 155), (494, 156), (538, 150))
    assert classify("Morning Run", 6 * MI, 151, LTHR, laps) == "easy"


def test_strides_are_not_intervals():
    # 6 easy miles, then 4 x 160 m strides with walk-back recoveries.
    laps = [lap(0, 6, 6 * 520, 148)]
    for i in range(4):
        laps += [lap(1 + 2 * i, 0.1, 32, 155), lap(2 + 2 * i, 0.05, 60, 140)]
    assert classify("Morning Run", 6.6 * MI, 149, LTHR, laps) == "easy"


def test_short_reps_pass_on_peak_hr():
    # 8 x 400 m: HR lags so the average is lowish, but each rep peaks high.
    laps = [lap(0, 1.5, 780, 140)]
    for i in range(8):
        laps += [LapData(1 + 2 * i, 400, 82, 150, None, None, 170), lap(2 + 2 * i, 0.03, 90, 135)]
    laps += [lap(30, 1, 540, 145)]
    assert classify("Morning Run", 5 * MI, 148, LTHR, laps) == "intervals"


def test_speed_at_hr_scales_with_hr_reserve():
    assert speed_at_hr(3.0, 150, 150, 50) == 3.0
    assert speed_at_hr(3.0, 150, 170, 50) == pytest.approx(3.6)

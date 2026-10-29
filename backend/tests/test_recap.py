from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import engine
from app.engine.workouts import WorkSummary
from app.main import app
from app.models import MILE_M
from app.recap import RecapInput, run_recap, spoken_duration, spoken_pace
from app.sync import upsert_activities

TODAY = date(2026, 10, 29)  # a Thursday


def test_spoken_formats():
    assert spoken_duration(3125) == "52 minutes 5 seconds"
    assert spoken_duration(5520) == "1 hour 32 minutes"
    assert spoken_duration(61) == "1 minute 1 second"
    assert spoken_pace(MILE_M / 432) == "7:12 per mile"


def test_recap_easy_run_compares_with_similar_runs():
    text = run_recap(RecapInput(
        day=TODAY, today=TODAY, workout_type="easy", distance_m=5 * MILE_M, seconds=5 * 480,
        avg_hr=142, load=48.6, week_miles=17.25,
        similar_speeds=[MILE_M / 500, MILE_M / 510],  # avg 8:25/mi vs today's 8:00
    ))
    assert text.startswith("Today's easy run: 5.0 miles in 40 minutes, averaging 8:00 per mile at an average heart rate of 142.")
    assert "fastest of 3 similar runs" in text
    assert "Training load 49, with 17.2 miles so far this week." in text


def test_recap_workout_mentions_reps_pain_and_last_week():
    text = run_recap(RecapInput(
        day=TODAY - timedelta(days=5), today=TODAY, workout_type="intervals", distance_m=7 * MILE_M,
        seconds=7 * 450, avg_hr=155, load=90, week_miles=30,
        work=WorkSummary(reps=6, distance_m=6 * 800, duration_s=6 * 165, avg_hr=168, intervals=True),
        similar_speeds=[MILE_M / 440, MILE_M / 450, MILE_M / 460], pain=5, notes="calf tight",
    ))
    assert text.startswith("Saturday's interval session")
    assert "The work was 6 reps averaging 5:32 per mile." in text
    assert "right in line" in text
    assert "so far that week" in text
    assert "pain at 5 out of 10" in text and "calf tight" not in text  # pain outranks the note


def garmin_run(activity_id: int, days_ago: int, miles: float, avg_hr: float) -> dict:
    start = datetime.combine(date.today() - timedelta(days=days_ago), datetime.min.time()).replace(hour=7)
    return {
        "activityId": activity_id,
        "startTimeLocal": start.strftime("%Y-%m-%d %H:%M:%S"),
        "activityName": "Morning Run",
        "activityType": {"typeKey": "running"},
        "distance": miles * MILE_M,
        "duration": miles * 540,
        "averageHR": avg_hr,
    }


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        with Session(engine) as s:
            upsert_activities(s, [garmin_run(501, 20, 6, 140), garmin_run(502, 13, 6.2, 141), garmin_run(503, 2, 6.1, 142)])
        yield c


def test_recap_text_endpoint(client):
    r = client.get("/api/activities/503/recap")
    assert r.status_code == 200
    assert "6.1 miles" in r.json()["text"]
    assert client.get("/api/activities/999999/recap").status_code == 404


def test_audio_without_key_is_503(client, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert client.get("/api/voice").json() == {"configured": False}
    r = client.get("/api/activities/503/recap/audio")
    assert r.status_code == 503 and "ELEVENLABS_API_KEY" in r.json()["detail"]


def test_audio_sends_recap_to_elevenlabs(client, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    sent = {}

    class FakeResponse:
        status_code = 200
        content = b"ID3fake-mp3"
        text = ""

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return FakeResponse()

    monkeypatch.setattr("app.voice.httpx.post", fake_post)
    assert client.get("/api/voice").json() == {"configured": True}
    r = client.get("/api/activities/503/recap/audio")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3fake-mp3"
    assert sent["url"].endswith("/v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb")
    assert sent["headers"]["xi-api-key"] == "test-key"
    assert sent["json"]["text"] == client.get("/api/activities/503/recap").json()["text"]


def test_audio_upstream_error_is_502(client, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "bad-key")

    class Unauthorized:
        status_code = 401
        content = b""
        text = '{"detail": "invalid api key"}'

    monkeypatch.setattr("app.voice.httpx.post", lambda url, **kw: Unauthorized())
    r = client.get("/api/activities/503/recap/audio")
    assert r.status_code == 502 and "401" in r.json()["detail"]

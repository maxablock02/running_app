from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from app import voice
from app.db import get_session
from app.engine.load import activity_load
from app.engine.workouts import summarize
from app.models import MILE_M, Activity
from app.recap import RecapInput, run_recap
from app.routers.activities import is_run, load_laps, physiology, workout_type

router = APIRouter(prefix="/api", tags=["voice"])

SIMILAR_DAYS = 56  # compare against the last 8 weeks
SIMILAR_DISTANCE = 0.25  # "similar" = same workout type, distance within ±25%


def build_recap(session: Session, activity_id: int) -> str:
    """Recap text for one run. Uses cached laps only, so it never calls Garmin."""
    a = session.get(Activity, activity_id)
    if a is None:
        raise HTTPException(404, "Activity not found")
    p = physiology(session)
    laps = load_laps(session, [a.id]).get(a.id)
    t = workout_type(a, p.lthr, laps)

    since = a.start_time - timedelta(days=SIMILAR_DAYS)
    earlier = session.exec(select(Activity).where(
        Activity.activity_type.contains("running"), Activity.excluded == False,  # noqa: E712
        Activity.start_time >= since, Activity.start_time < a.start_time,
    )).all()
    earlier_laps = load_laps(session, [o.id for o in earlier])
    similar = [
        o.distance_m / (o.moving_s or o.duration_s)
        for o in earlier
        if (o.moving_s or o.duration_s) and a.distance_m
        and abs(o.distance_m / a.distance_m - 1) <= SIMILAR_DISTANCE
        and workout_type(o, p.lthr, earlier_laps.get(o.id)) == t
    ]

    week_start = a.start_time.date() - timedelta(days=a.start_time.weekday())
    week = session.exec(select(Activity).where(
        Activity.start_time >= week_start, Activity.start_time <= a.start_time,
    )).all()

    return run_recap(RecapInput(
        day=a.start_time.date(),
        today=date.today(),
        workout_type=t,
        distance_m=a.distance_m,
        seconds=a.moving_s or a.duration_s,
        avg_hr=a.avg_hr,
        load=0.0 if a.excluded else activity_load(a.duration_s, a.avg_hr, a.rpe, p, a.load_override)[0],
        week_miles=sum(w.distance_m for w in week if is_run(w.activity_type)) / MILE_M,
        work=summarize(laps, p.lthr) if laps else None,
        similar_speeds=similar,
        pain=a.pain,
        notes=a.notes,
    ))


@router.get("/voice")
def voice_status():
    return {"configured": voice.is_configured()}


@router.get("/activities/{activity_id}/recap")
def recap_text(activity_id: int, session: Session = Depends(get_session)):
    return {"text": build_recap(session, activity_id)}


@router.get("/activities/{activity_id}/recap/audio")
def recap_audio(activity_id: int, session: Session = Depends(get_session)):
    """The recap read aloud by ElevenLabs, as MP3."""
    text = build_recap(session, activity_id)
    try:
        audio = voice.speak(text)
    except voice.VoiceNotConfigured as e:
        raise HTTPException(503, str(e)) from e
    except voice.VoiceError as e:
        raise HTTPException(502, str(e)) from e
    return Response(audio, media_type="audio/mpeg")

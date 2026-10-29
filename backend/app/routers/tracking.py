"""Manual inputs: daily rehab/wellness log, races, profile, and Garmin sync."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.garmin_client import GarminNotLoggedIn
from app.models import DailyLog, DailyLogBase, Profile, ProfileBase, Race, RaceBase, SyncState
from app.sync import run_sync

router = APIRouter(prefix="/api", tags=["tracking"])


# --- Daily log ---------------------------------------------------------------

@router.get("/daily")
def list_daily(days: int = 60, session: Session = Depends(get_session)):
    since = date.today() - timedelta(days=days)
    return session.exec(select(DailyLog).where(DailyLog.day >= since).order_by(DailyLog.day.desc())).all()


@router.put("/daily/{day}")
def upsert_daily(day: date, body: DailyLogBase, session: Session = Depends(get_session)):
    log = session.merge(DailyLog(**body.model_dump(), day=day))
    session.commit()
    session.refresh(log)
    return log


# --- Races -------------------------------------------------------------------

@router.get("/races")
def list_races(session: Session = Depends(get_session)):
    races = session.exec(select(Race)).all()
    return sorted(races, key=lambda r: (r.race_date is None, r.race_date or date.max))


@router.post("/races")
def create_race(body: RaceBase, session: Session = Depends(get_session)):
    race = Race(**body.model_dump())
    session.add(race)
    session.commit()
    session.refresh(race)
    return race


@router.put("/races/{race_id}")
def update_race(race_id: int, body: RaceBase, session: Session = Depends(get_session)):
    if session.get(Race, race_id) is None:
        raise HTTPException(404, "Race not found")
    race = session.merge(Race(**body.model_dump(), id=race_id))
    session.commit()
    session.refresh(race)
    return race


@router.delete("/races/{race_id}")
def delete_race(race_id: int, session: Session = Depends(get_session)):
    race = session.get(Race, race_id)
    if race is None:
        raise HTTPException(404, "Race not found")
    session.delete(race)
    session.commit()
    return {"ok": True}


# --- Profile -----------------------------------------------------------------

@router.get("/profile")
def get_profile(session: Session = Depends(get_session)):
    return session.get(Profile, 1)


@router.put("/profile")
def update_profile(body: ProfileBase, session: Session = Depends(get_session)):
    profile = session.merge(Profile(**body.model_dump(), id=1))
    session.commit()
    session.refresh(profile)
    return profile


# --- Sync --------------------------------------------------------------------

class SyncRequest(BaseModel):
    full: bool = False
    since: date | None = None  # backfill from this date


@router.get("/sync")
def sync_status(session: Session = Depends(get_session)):
    return session.get(SyncState, 1)


@router.post("/sync")
def sync(body: SyncRequest | None = None, session: Session = Depends(get_session)):
    try:
        return run_sync(session, full=bool(body and body.full), since=body.since if body else None)
    except GarminNotLoggedIn as e:
        raise HTTPException(401, str(e)) from e

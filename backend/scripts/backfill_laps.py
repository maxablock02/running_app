"""Fetch Garmin laps for every run that doesn't have them yet. Safe to re-run.

    .venv\\Scripts\\python scripts\\backfill_laps.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from app.garmin_client import get_client  # noqa: E402
from app.models import Activity  # noqa: E402
from app.sync import fetch_laps  # noqa: E402

BATCH = 25

init_db()
with Session(engine) as session:
    ids = [a.id for a in session.exec(
        select(Activity).where(Activity.activity_type.contains("running"), Activity.laps_fetched == False)  # noqa: E712
        .order_by(Activity.start_time.desc())
    ).all()]
    print(f"{len(ids)} runs need laps", flush=True)
    client = get_client()
    done = 0
    for i in range(0, len(ids), BATCH):
        done += fetch_laps(session, ids[i:i + BATCH], client)
        print(f"{done}/{len(ids)}", flush=True)
print("done")

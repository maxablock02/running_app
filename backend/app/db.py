import os
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = Path(os.getenv("RUNNING_DB", DATA_DIR / "running.db"))

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def init_db() -> None:
    from app import models  # noqa: F401  (registers tables)

    SQLModel.metadata.create_all(engine)
    add_missing_columns()
    with Session(engine) as session:
        models.seed_defaults(session)


def add_missing_columns() -> None:
    """Additive-only migration: create_all() makes new tables but never new columns on old ones."""
    from sqlalchemy import inspect, text
    from sqlalchemy.schema import CreateColumn

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = CreateColumn(col).compile(dialect=engine.dialect)
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                if default is not None:
                    ddl = f"{ddl} DEFAULT {int(default) if isinstance(default, bool) else repr(default)}"
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {ddl}"))


def get_session():
    with Session(engine) as session:
        yield session

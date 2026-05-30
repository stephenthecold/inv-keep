import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    # Make sure the directory for the sqlite file exists.
    path = settings.database_url.split("sqlite:///")[-1]
    if path and path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after the first release. SQLite can't add them via create_all,
# so we ALTER TABLE for any that are missing on startup (data is preserved).
_ADDED_COLUMNS = {
    "parts": {
        "category_id": "INTEGER",
        "low_stock_threshold": "INTEGER",
        "low_stock_alerted": "BOOLEAN DEFAULT 0",
        "barcode_generated": "BOOLEAN DEFAULT 0",
        "unit_price": "NUMERIC DEFAULT 0",
        "description": "TEXT DEFAULT ''",
        "icon": "TEXT DEFAULT ''",
        "image": "TEXT DEFAULT ''",
    },
    "categories": {
        "description": "TEXT DEFAULT ''",
    },
    "customers": {
        "contact_name": "TEXT DEFAULT ''",
        "email": "TEXT DEFAULT ''",
        "phone": "TEXT DEFAULT ''",
        "location": "TEXT DEFAULT ''",
        "address": "TEXT DEFAULT ''",
        "notes": "TEXT DEFAULT ''",
    },
    "transactions": {
        "job_id": "INTEGER",
        "unit_price_at_time": "NUMERIC DEFAULT 0",
    },
}


def ensure_columns():
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            try:
                existing = {
                    row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
                }
            except Exception:
                continue
            if not existing:
                continue  # table doesn't exist yet; create_all will make it fresh
            for col, ddl in cols.items():
                if col not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

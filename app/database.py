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
        "archived": "BOOLEAN DEFAULT 0",
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
        "archived": "BOOLEAN DEFAULT 0",
    },
    "transactions": {
        "job_id": "INTEGER",
        "unit_price_at_time": "NUMERIC DEFAULT 0",
        "lat": "REAL",
        "lng": "REAL",
        "geo_accuracy_m": "REAL",
        "order_id": "INTEGER",
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
        _relax_transactions_customer_id(conn)


def _relax_transactions_customer_id(conn):
    """v1.9: cart lines exist before a client is picked, so transactions.customer_id
    must be nullable. SQLite can't ALTER a column's NOT NULL flag — rebuild the
    table when the old NOT NULL constraint is still in place. Idempotent."""
    try:
        info = list(conn.exec_driver_sql("PRAGMA table_info(transactions)"))
    except Exception:
        return
    if not info:
        return
    # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
    cust = next((row for row in info if row[1] == "customer_id"), None)
    if not cust or cust[3] == 0:
        return  # already nullable (or column missing) — nothing to do
    cols = [row[1] for row in info]
    col_list = ", ".join(cols)
    conn.exec_driver_sql("CREATE TABLE _txn_rebuild AS SELECT * FROM transactions")
    conn.exec_driver_sql("DROP TABLE transactions")
    conn.exec_driver_sql("""
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER REFERENCES customers(id),
            job_id INTEGER REFERENCES jobs(id),
            part_id INTEGER NOT NULL REFERENCES parts(id),
            order_id INTEGER REFERENCES orders(id),
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_cost_at_time NUMERIC NOT NULL DEFAULT 0,
            unit_price_at_time NUMERIC NOT NULL DEFAULT 0,
            scanned_by TEXT DEFAULT '',
            note TEXT DEFAULT '',
            voided BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME,
            lat REAL,
            lng REAL,
            geo_accuracy_m REAL
        )
    """)
    conn.exec_driver_sql(f"INSERT INTO transactions ({col_list}) SELECT {col_list} FROM _txn_rebuild")
    conn.exec_driver_sql("DROP TABLE _txn_rebuild")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_transactions_order_id ON transactions(order_id)")

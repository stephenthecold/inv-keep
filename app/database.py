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
        "pack_size": "INTEGER DEFAULT 1",
        "pack_unit_label": "TEXT DEFAULT ''",
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
        "card_uid": "TEXT",
    },
    "kiosk_pins": {
        "badge_uid": "TEXT",
    },
    "transactions": {
        "job_id": "INTEGER",
        "unit_price_at_time": "NUMERIC DEFAULT 0",
        "lat": "REAL",
        "lng": "REAL",
        "geo_accuracy_m": "REAL",
        "order_id": "INTEGER",
        "location_id": "INTEGER",
        "receipt_id": "TEXT",
    },
    "orders": {
        "location_id": "INTEGER",
        "client_action_id": "TEXT",
    },
    "roles": {
        # v1.22: once True, rbac.seed_roles() leaves the role's perm list
        # alone on startup so admins can remove default perms.
        "customized": "BOOLEAN DEFAULT 0",
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


def seed_locations_and_stock():
    """v1.15: bootstrap the new locations / stock_levels tables.

    - If `locations` is empty, create a single row called "Main".
    - For each Part with no StockLevel row, insert one for Main equal to the
      part's existing `quantity_on_hand` (so totals stay consistent).
    - Auto-cancel any open carts left over from the pre-1.15 schema (their
      lines have no `location_id`); restore the lines' stock to Main.

    Idempotent — safe to call on every startup.
    """
    from .models import Location, Order, Part, StockLevel, Transaction
    from datetime import datetime

    db = SessionLocal()
    try:
        main = db.query(Location).order_by(Location.id).first()
        if main is None:
            main = Location(name="Main", notes="Default location (auto-created).",
                            active=True, archived=False)
            db.add(main)
            db.flush()

        # Seed stock_levels for any part missing one. Use a single query to find
        # parts that don't already have a row in stock_levels.
        existing_part_ids = {pid for (pid,) in db.query(StockLevel.part_id).distinct()}
        for part in db.query(Part).all():
            if part.id in existing_part_ids:
                continue
            db.add(StockLevel(part_id=part.id, location_id=main.id,
                              quantity=part.quantity_on_hand or 0))

        # Auto-cancel any pre-existing open carts so they don't strand stock.
        # Their lines were decremented from the legacy single-counter without
        # a location stamp — restore to Main.
        open_carts = db.query(Order).filter(Order.status == "open").all()
        for cart in open_carts:
            lines = (db.query(Transaction)
                     .filter(Transaction.order_id == cart.id,
                             Transaction.voided == False)  # noqa: E712
                     .all())
            for ln in lines:
                if ln.part is not None:
                    ln.part.quantity_on_hand += ln.quantity
                    # Mirror into stock_levels at Main if a row exists.
                    sl = (db.query(StockLevel)
                          .filter(StockLevel.part_id == ln.part_id,
                                  StockLevel.location_id == main.id)
                          .first())
                    if sl is not None:
                        sl.quantity += ln.quantity
                ln.voided = True
            cart.status = "cancelled"
            cart.voided_by = "system"
            cart.voided_at = datetime.utcnow()
            cart.voided_reason = "Auto-cancelled on upgrade to multi-location stock."
        db.commit()
    finally:
        db.close()


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
    conn.exec_driver_sql("CREATE TABLE _txn_rebuild AS SELECT * FROM transactions")
    conn.exec_driver_sql("DROP TABLE transactions")
    # The new table must list EVERY column the live table has by this point —
    # ensure_columns() runs the additive ADD COLUMN loop before us, so on an
    # old DB the source already carries location_id + receipt_id. Omitting them
    # here (as an earlier version did) made the INSERT below reference columns
    # the target lacked → OperationalError on boot + lost per-location/receipt
    # history. We declare them, and additionally copy only the columns common
    # to both tables so any future additive column can't break this rebuild.
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
            geo_accuracy_m REAL,
            location_id INTEGER REFERENCES locations(id),
            receipt_id TEXT
        )
    """)
    new_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(transactions)")}
    common = [c for c in cols if c in new_cols]
    col_list = ", ".join(common)
    conn.exec_driver_sql(f"INSERT INTO transactions ({col_list}) SELECT {col_list} FROM _txn_rebuild")
    conn.exec_driver_sql("DROP TABLE _txn_rebuild")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_transactions_order_id ON transactions(order_id)")

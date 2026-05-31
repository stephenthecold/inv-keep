import csv
import io
import math
from datetime import datetime

from .models import Client, Order, Part, Transaction

NO_JOB = "— No job —"


def _c(v):
    """Ceiling-cents (mirror of main.ceil_cents — duplicated to avoid
    importing the FastAPI app module from here)."""
    return f"{math.ceil(float(v or 0) * 100 - 1e-9) / 100:.2f}"


def month_bounds(year: int, month: int):
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end


def build_report(db, year: int, month: int, client_ids=None):
    start, end = month_bounds(year, month)
    return build_report_range(db, start, end, client_ids=client_ids)


def build_report_range(db, start, end, client_ids=None):
    """Clients -> jobs -> line items in [start, end), plus charge/cost/margin totals.

    If ``client_ids`` is provided (non-empty iterable), restrict to just those
    client IDs. Empty / None means "all clients" (the historical behavior).
    """
    q = (
        db.query(Transaction)
        .join(Part)
        .join(Client, Transaction.customer_id == Client.id)
        .outerjoin(Order, Transaction.order_id == Order.id)
        .filter(
            Transaction.voided == False,  # noqa: E712
            Transaction.created_at >= start,
            Transaction.created_at < end,
            # Exclude lines still tied to an open / cancelled cart.
            (Order.id.is_(None)) | (Order.status == "submitted"),
        )
    )
    if client_ids:
        q = q.filter(Transaction.customer_id.in_(list(client_ids)))
    txns = q.all()

    clients = {}
    for t in txns:
        c = clients.setdefault(
            t.customer_id,
            {"name": t.client.name, "reference": t.client.reference, "jobs": {},
             "charge": 0.0, "cost": 0.0},
        )
        jkey = t.job_id or 0
        job = c["jobs"].setdefault(
            jkey,
            {"name": t.job.name if t.job else NO_JOB,
             "reference": t.job.reference if t.job else "",
             "lines": {}, "charge": 0.0, "cost": 0.0},
        )
        key = (t.part_id, float(t.unit_price_at_time), float(t.unit_cost_at_time))
        line = job["lines"].setdefault(
            key,
            {"part": t.part.name, "barcode": t.part.barcode,
             "unit_cost": float(t.unit_cost_at_time), "unit_price": float(t.unit_price_at_time),
             "quantity": 0, "charge": 0.0, "cost": 0.0},
        )
        line["quantity"] += t.quantity
        line["charge"] += t.total_charge
        line["cost"] += t.total_cost
        job["charge"] += t.total_charge
        job["cost"] += t.total_cost
        c["charge"] += t.total_charge
        c["cost"] += t.total_cost

    result = []
    for c in clients.values():
        jobs = []
        for j in c["jobs"].values():
            j["lines"] = sorted(j["lines"].values(), key=lambda x: x["part"].lower())
            j["margin"] = j["charge"] - j["cost"]
            jobs.append(j)
        jobs.sort(key=lambda j: (j["name"] == NO_JOB, j["name"].lower()))
        c["jobs"] = jobs
        c["margin"] = c["charge"] - c["cost"]
        result.append(c)
    result.sort(key=lambda x: x["name"].lower())

    totals = {
        "charge": sum(c["charge"] for c in result),
        "cost": sum(c["cost"] for c in result),
    }
    totals["margin"] = totals["charge"] - totals["cost"]
    return result, totals


def report_csv(db, year: int, month: int, client_ids=None) -> str:
    report, totals = build_report(db, year, month, client_ids=client_ids)
    return report_csv_for(report, totals)


def report_csv_for(report, totals) -> str:
    """Render the CSV for an already-built (report, totals) tuple."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Client", "Account Ref", "Job", "Job Ref", "Part", "Barcode", "Quantity",
                "Unit Cost", "Unit Charge", "Line Cost", "Line Charge", "Line Margin"])
    for c in report:
        for job in c["jobs"]:
            for ln in job["lines"]:
                w.writerow([c["name"], c["reference"], job["name"], job["reference"],
                            ln["part"], ln["barcode"], ln["quantity"],
                            _c(ln["unit_cost"]), _c(ln["unit_price"]),
                            _c(ln["cost"]), _c(ln["charge"]), _c(ln["charge"] - ln["cost"])])
            w.writerow([c["name"], c["reference"], job["name"], job["reference"], "", "", "",
                        "", "Job subtotal", _c(job["cost"]), _c(job["charge"]), _c(job["margin"])])
        w.writerow([c["name"], c["reference"], "", "", "", "", "",
                    "", "Client total", _c(c["cost"]), _c(c["charge"]), _c(c["margin"])])
        w.writerow([])
    w.writerow(["", "", "", "", "", "", "", "", "GRAND TOTAL",
                _c(totals["cost"]), _c(totals["charge"]), _c(totals["margin"])])
    return buf.getvalue()

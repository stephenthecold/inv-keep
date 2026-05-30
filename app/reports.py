import csv
import io
from datetime import datetime

from .models import Client, Part, Transaction

NO_JOB = "— No job —"


def month_bounds(year: int, month: int):
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end


def build_report(db, year: int, month: int):
    """Clients -> jobs -> line items for the month, plus charge/cost/margin totals."""
    start, end = month_bounds(year, month)
    txns = (
        db.query(Transaction)
        .join(Part)
        .join(Client, Transaction.customer_id == Client.id)
        .filter(
            Transaction.voided == False,  # noqa: E712
            Transaction.created_at >= start,
            Transaction.created_at < end,
        )
        .all()
    )

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


def report_csv(db, year: int, month: int) -> str:
    report, totals = build_report(db, year, month)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Client", "Account Ref", "Job", "Job Ref", "Part", "Barcode", "Quantity",
                "Unit Cost", "Unit Charge", "Line Cost", "Line Charge", "Line Margin"])
    for c in report:
        for job in c["jobs"]:
            for ln in job["lines"]:
                w.writerow([c["name"], c["reference"], job["name"], job["reference"],
                            ln["part"], ln["barcode"], ln["quantity"],
                            f"{ln['unit_cost']:.2f}", f"{ln['unit_price']:.2f}",
                            f"{ln['cost']:.2f}", f"{ln['charge']:.2f}", f"{ln['charge'] - ln['cost']:.2f}"])
            w.writerow([c["name"], c["reference"], job["name"], job["reference"], "", "", "",
                        "", "Job subtotal", f"{job['cost']:.2f}", f"{job['charge']:.2f}", f"{job['margin']:.2f}"])
        w.writerow([c["name"], c["reference"], "", "", "", "", "",
                    "", "Client total", f"{c['cost']:.2f}", f"{c['charge']:.2f}", f"{c['margin']:.2f}"])
        w.writerow([])
    w.writerow(["", "", "", "", "", "", "", "", "GRAND TOTAL",
                f"{totals['cost']:.2f}", f"{totals['charge']:.2f}", f"{totals['margin']:.2f}"])
    return buf.getvalue()

import os
import secrets
import threading
import uuid
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import audit, auth, emailer, labels, reports
from . import settings_store as store
from .config import settings
from .database import Base, SessionLocal, engine, ensure_columns, get_db
from .models import AuditLog, Category, Client, Job, Part, Transaction
from .version import __version__

Base.metadata.create_all(bind=engine)
ensure_columns()

# Uploaded brand assets live alongside the database (under the mounted ./data volume).
UPLOAD_DIR = os.path.join("data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title=settings.app_title)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
templates = Jinja2Templates(directory="app/templates")

PUBLIC_PATHS = {"/login", "/auth/callback", "/logout", "/health"}

_stop_event = threading.Event()


@app.on_event("startup")
def _start_scheduler():
    threading.Thread(target=emailer.scheduler_loop, args=(_stop_event,), daemon=True).start()


@app.on_event("shutdown")
def _stop_scheduler():
    _stop_event.set()


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static") or path in PUBLIC_PATHS:
        return await call_next(request)
    db = SessionLocal()
    try:
        user = auth.resolve_user(request, db)
        mode = auth.effective_mode(db)
    finally:
        db.close()
    if not user:
        if mode == "oidc":
            return RedirectResponse("/login")
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    request.state.user = user
    return await call_next(request)


# Added LAST so it sits OUTERMOST in the stack and runs before auth_middleware,
# making request.session available when OIDC mode reads it.
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)


def ctx(request: Request, db: Session, **kwargs):
    base = {
        "request": request,
        "user": getattr(request.state, "user", {"username": "", "email": ""}),
        "settings": settings,
        "cfg": store.all_settings(db),
        "version": __version__,
        "now": datetime.utcnow(),
        "msg": request.query_params.get("msg", ""),
        "ok": request.query_params.get("ok", "1") != "0",
    }
    base.update(kwargs)
    return base


def current_user(request: Request):
    return getattr(request.state, "user", {"username": ""})


# ---- category helpers ------------------------------------------------------
def category_choices(db):
    """Flat list of (id, indented_label, depth, category) ordered as a tree."""
    cats = db.query(Category).all()
    by_parent = {}
    for c in cats:
        by_parent.setdefault(c.parent_id, []).append(c)
    out = []

    def walk(parent_id, depth):
        for c in sorted(by_parent.get(parent_id, []), key=lambda x: x.name.lower()):
            out.append((c.id, ("    " * depth) + c.name, depth, c))
            walk(c.id, depth + 1)

    walk(None, 0)
    return out


def category_path(db, cat):
    parts = []
    seen = set()
    while cat is not None and cat.id not in seen:
        seen.add(cat.id)
        parts.append(cat.name)
        cat = cat.parent
    return " › ".join(reversed(parts))


def redirect(path, msg="", ok=True):
    sep = "&" if "?" in path else "?"
    if msg:
        path = f"{path}{sep}msg={msg}&ok={'1' if ok else '0'}"
    return RedirectResponse(path, status_code=303)


def reports_money(db, value):
    return f"{store.get(db, 'currency')}{value:.2f}"


# ============================================================ auth routes
@app.get("/health")
def health():
    return {"status": "ok"}


def _auth_error_page(detail):
    return HTMLResponse(
        "<html><body style='font-family:system-ui;max-width:640px;margin:4rem auto;color:#333'>"
        "<h2>Sign-in is not working</h2>"
        f"<p>The OpenID Connect provider could not be reached or rejected the request:</p>"
        f"<pre style='background:#f4f4f4;padding:1rem;border-radius:8px;white-space:pre-wrap'>{detail}</pre>"
        "<p>Check the discovery URL, client ID/secret, and redirect URI in your IdP. "
        "If you are locked out, set the environment variable <code>DISABLE_AUTH=1</code> and "
        "restart the app to regain access, then fix the settings.</p>"
        "</body></html>",
        status_code=502,
    )


@app.get("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    if auth.effective_mode(db) != "oidc":
        return RedirectResponse("/")
    redirect_uri = store.get(db, "oidc_redirect_url") or str(request.url_for("auth_callback"))
    try:
        client = auth.build_oidc(db)
        return await client.idp.authorize_redirect(request, redirect_uri)
    except Exception as e:  # noqa: BLE001
        return _auth_error_page(e)


@app.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        client = auth.build_oidc(db)
        token = await client.idp.authorize_access_token(request)
    except Exception as e:  # noqa: BLE001
        return _auth_error_page(e)
    info = token.get("userinfo") or {}
    request.session["user"] = {
        "username": info.get("preferred_username") or info.get("email") or "user",
        "email": info.get("email", ""),
    }
    return RedirectResponse("/")


@app.get("/logout")
async def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse("/")


# ============================================================ scan page
@app.get("/", response_class=HTMLResponse)
def scan_page(request: Request, db: Session = Depends(get_db)):
    clients = db.query(Client).filter(Client.active == True).order_by(Client.name).all()  # noqa: E712
    jobs = db.query(Job).filter(Job.active == True).order_by(Job.name).all()  # noqa: E712
    recent = db.query(Transaction).order_by(Transaction.created_at.desc()).limit(15).all()
    return templates.TemplateResponse("scan.html", ctx(request, db, clients=clients, jobs=jobs, recent=recent))


class CheckoutIn(BaseModel):
    barcode: str
    client_id: int
    job_id: Optional[int] = None
    quantity: int = 1
    note: str = ""


@app.post("/api/checkout")
def api_checkout(payload: CheckoutIn, request: Request, db: Session = Depends(get_db)):
    barcode = payload.barcode.strip()
    part = db.query(Part).filter(Part.barcode == barcode, Part.active == True).first()  # noqa: E712
    if not part:
        return {"ok": False, "error": "unknown_barcode", "barcode": barcode}

    qty = 1 if part.type == "unique" else max(1, payload.quantity)
    if part.quantity_on_hand < qty:
        return {"ok": False, "error": "insufficient_stock", "available": part.quantity_on_hand, "part": part.name}

    client = db.get(Client, payload.client_id)
    if not client:
        return {"ok": False, "error": "no_client"}

    job = None
    if payload.job_id:
        job = db.get(Job, payload.job_id)
        if not job or job.client_id != client.id:
            return {"ok": False, "error": "bad_job"}

    user = current_user(request)
    part.quantity_on_hand -= qty
    txn = Transaction(
        part_id=part.id,
        customer_id=client.id,
        job_id=job.id if job else None,
        quantity=qty,
        unit_cost_at_time=part.unit_cost,
        unit_price_at_time=part.unit_price,
        scanned_by=user.get("username", ""),
        note=payload.note or "",
    )
    db.add(txn)
    db.flush()
    where = client.name + (f" / {job.name}" if job else "")
    audit.record(
        db, user, "sale.checkout", "transaction", txn.id,
        f"{qty} × {part.name} → {where} ({reports_money(db, txn.total_charge)})",
    )
    emailer.maybe_low_stock_alert(db, part)
    db.commit()
    db.refresh(txn)
    return {
        "ok": True,
        "line": {
            "id": txn.id,
            "part": part.name,
            "quantity": qty,
            "unit_cost": float(part.unit_cost),
            "unit_price": float(part.unit_price),
            "charge": txn.total_charge,
            "cost": txn.total_cost,
            "remaining": part.quantity_on_hand,
            "client": client.name,
            "job": job.name if job else "",
        },
    }


@app.get("/api/search")
def api_search(q: str = "", db: Session = Depends(get_db)):
    q = (q or "").strip()
    if not q:
        return {"results": []}
    like = f"%{q}%"
    rows = (
        db.query(Part)
        .filter(Part.active == True, or_(Part.name.ilike(like), Part.barcode.ilike(like)))  # noqa: E712
        .order_by(Part.name)
        .limit(10)
        .all()
    )
    return {
        "results": [
            {
                "id": p.id,
                "name": p.name,
                "icon": p.icon or "",
                "description": p.description or "",
                "barcode": p.barcode,
                "type": p.type,
                "qty": p.quantity_on_hand,
                "unit_cost": float(p.unit_cost),
                "unit_price": float(p.unit_price),
            }
            for p in rows
        ]
    }


@app.post("/api/void/{txn_id}")
def api_void(txn_id: int, request: Request, db: Session = Depends(get_db)):
    txn = db.get(Transaction, txn_id)
    if not txn or txn.voided:
        return {"ok": False}
    txn.voided = True
    part = db.get(Part, txn.part_id)
    if part:
        part.quantity_on_hand += txn.quantity
    audit.record(
        db, current_user(request), "sale.void", "transaction", txn.id,
        f"Voided {txn.quantity} × {part.name if part else '?'}",
    )
    db.commit()
    return {"ok": True}


# ============================================================ parts
@app.get("/parts", response_class=HTMLResponse)
def parts_page(request: Request, db: Session = Depends(get_db)):
    parts = db.query(Part).order_by(Part.name).all()
    cats = category_choices(db)
    cat_names = {cid: category_path(db, c) for cid, _label, _d, c in cats}
    return templates.TemplateResponse(
        "parts.html",
        ctx(request, db, parts=parts, categories=cats, cat_names=cat_names,
            prefill=request.query_params.get("barcode", "")),
    )


@app.post("/parts/add")
def parts_add(
    request: Request,
    name: str = Form(...),
    barcode: str = Form(""),
    type: str = Form("bulk"),
    icon: str = Form(""),
    description: str = Form(""),
    unit_cost: float = Form(0.0),
    unit_price: float = Form(0.0),
    quantity_on_hand: int = Form(0),
    category_id: str = Form(""),
    low_stock_threshold: str = Form(""),
    db: Session = Depends(get_db),
):
    barcode = barcode.strip()
    cat_id = int(category_id) if category_id else None
    threshold = int(low_stock_threshold) if low_stock_threshold.strip() else None
    if type == "unique":
        quantity_on_hand = max(quantity_on_hand, 1)

    if barcode:
        if db.query(Part).filter(Part.barcode == barcode).first():
            return redirect("/parts", "That barcode already exists.", ok=False)
        part = Part(
            name=name.strip(), barcode=barcode, type=type, unit_cost=unit_cost, unit_price=unit_price,
            quantity_on_hand=quantity_on_hand, category_id=cat_id, low_stock_threshold=threshold,
            icon=icon.strip(), description=description.strip(),
        )
        db.add(part)
        db.flush()
        generated = False
    else:
        part = Part(
            name=name.strip(), barcode="tmp-" + uuid.uuid4().hex, type=type, unit_cost=unit_cost,
            unit_price=unit_price, quantity_on_hand=quantity_on_hand, category_id=cat_id,
            low_stock_threshold=threshold, icon=icon.strip(), description=description.strip(),
        )
        db.add(part)
        db.flush()
        part.barcode = labels.generate_value(part.id)
        part.barcode_generated = True
        generated = True

    audit.record(db, current_user(request), "part.create", "part", part.id, f"Created {part.name} ({part.barcode})")
    db.commit()
    if generated:
        return redirect(f"/parts/{part.id}/label", "Barcode generated — print the label.")
    return redirect("/parts", "Part added.")


@app.post("/parts/{part_id}/edit")
def parts_edit(
    part_id: int,
    request: Request,
    name: str = Form(...),
    icon: str = Form(""),
    description: str = Form(""),
    unit_cost: float = Form(0.0),
    unit_price: float = Form(0.0),
    category_id: str = Form(""),
    low_stock_threshold: str = Form(""),
    active: str = Form(""),
    db: Session = Depends(get_db),
):
    part = db.get(Part, part_id)
    if part:
        part.name = name.strip()
        part.icon = icon.strip()
        part.description = description.strip()
        part.unit_cost = unit_cost
        part.unit_price = unit_price
        part.category_id = int(category_id) if category_id else None
        part.low_stock_threshold = int(low_stock_threshold) if low_stock_threshold.strip() else None
        part.active = active == "on"
        audit.record(db, current_user(request), "part.edit", "part", part.id, f"Edited {part.name}")
        db.commit()
    return redirect("/parts", "Part saved.")


@app.post("/parts/{part_id}/restock")
def parts_restock(part_id: int, request: Request, amount: int = Form(...), db: Session = Depends(get_db)):
    part = db.get(Part, part_id)
    if part:
        part.quantity_on_hand += amount
        if part.low_stock_alerted:
            part.low_stock_alerted = False
        audit.record(db, current_user(request), "part.restock", "part", part.id, f"+{amount} → {part.quantity_on_hand}")
        db.commit()
    return redirect("/parts", "Stock updated.")


@app.get("/parts/{part_id}/label", response_class=HTMLResponse)
def part_label(part_id: int, request: Request, db: Session = Depends(get_db)):
    part = db.get(Part, part_id)
    if not part:
        return redirect("/parts", "Part not found.", ok=False)
    svg = labels.render_svg(part.barcode)
    return templates.TemplateResponse("label.html", ctx(request, db, parts_to_print=[(part, svg)]))


@app.get("/labels", response_class=HTMLResponse)
def labels_sheet(request: Request, db: Session = Depends(get_db)):
    parts = (
        db.query(Part)
        .filter(Part.barcode_generated == True, Part.active == True)  # noqa: E712
        .order_by(Part.name)
        .all()
    )
    rendered = [(p, labels.render_svg(p.barcode)) for p in parts]
    return templates.TemplateResponse("label.html", ctx(request, db, parts_to_print=rendered, sheet=True))


# ============================================================ categories
@app.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("categories.html", ctx(request, db, tree=category_choices(db)))


@app.post("/categories/add")
def categories_add(request: Request, name: str = Form(...), description: str = Form(""), parent_id: str = Form(""), db: Session = Depends(get_db)):
    cat = Category(name=name.strip(), description=description.strip(), parent_id=int(parent_id) if parent_id else None)
    db.add(cat)
    db.flush()
    audit.record(db, current_user(request), "category.create", "category", cat.id, f"Created {cat.name}")
    db.commit()
    return redirect("/categories", "Category added.")


@app.post("/categories/{cat_id}/edit")
def categories_edit(cat_id: int, request: Request, name: str = Form(...), description: str = Form(""), parent_id: str = Form(""), db: Session = Depends(get_db)):
    cat = db.get(Category, cat_id)
    if cat:
        new_parent = int(parent_id) if parent_id else None
        if new_parent != cat.id:
            cat.parent_id = new_parent
        cat.name = name.strip()
        cat.description = description.strip()
        audit.record(db, current_user(request), "category.edit", "category", cat.id, f"Edited {cat.name}")
        db.commit()
    return redirect("/categories", "Category saved.")


@app.post("/categories/{cat_id}/delete")
def categories_delete(cat_id: int, request: Request, db: Session = Depends(get_db)):
    cat = db.get(Category, cat_id)
    if cat:
        for child in list(cat.children):
            child.parent_id = cat.parent_id
        for p in db.query(Part).filter(Part.category_id == cat_id).all():
            p.category_id = cat.parent_id
        audit.record(db, current_user(request), "category.delete", "category", cat.id, f"Deleted {cat.name}")
        db.delete(cat)
        db.commit()
    return redirect("/categories", "Category deleted.")


# ============================================================ clients
@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request, db: Session = Depends(get_db)):
    clients = db.query(Client).order_by(Client.name).all()
    return templates.TemplateResponse("clients.html", ctx(request, db, clients=clients))


@app.post("/clients/add")
def clients_add(
    request: Request,
    name: str = Form(...),
    reference: str = Form(""),
    contact_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    location: str = Form(""),
    address: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    c = Client(
        name=name.strip(), reference=reference.strip(), contact_name=contact_name.strip(),
        email=email.strip(), phone=phone.strip(), location=location.strip(),
        address=address.strip(), notes=notes.strip(),
    )
    db.add(c)
    db.flush()
    audit.record(db, current_user(request), "client.create", "client", c.id, f"Created {c.name}")
    db.commit()
    return redirect("/clients", "Client added.")


@app.post("/clients/{client_id}/edit")
def clients_edit(
    client_id: int,
    request: Request,
    name: str = Form(...),
    reference: str = Form(""),
    contact_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    location: str = Form(""),
    address: str = Form(""),
    notes: str = Form(""),
    active: str = Form(""),
    db: Session = Depends(get_db),
):
    c = db.get(Client, client_id)
    if c:
        c.name = name.strip()
        c.reference = reference.strip()
        c.contact_name = contact_name.strip()
        c.email = email.strip()
        c.phone = phone.strip()
        c.location = location.strip()
        c.address = address.strip()
        c.notes = notes.strip()
        c.active = active == "on"
        audit.record(db, current_user(request), "client.edit", "client", c.id, f"Edited {c.name}")
        db.commit()
    return redirect("/clients", "Client saved.")


# ============================================================ jobs
@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, db: Session = Depends(get_db)):
    jobs = db.query(Job).join(Client, Job.client_id == Client.id).order_by(Client.name, Job.name).all()
    clients = db.query(Client).filter(Client.active == True).order_by(Client.name).all()  # noqa: E712
    return templates.TemplateResponse("jobs.html", ctx(request, db, jobs=jobs, clients=clients))


@app.post("/jobs/add")
def jobs_add(
    request: Request,
    client_id: int = Form(...),
    name: str = Form(...),
    reference: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    if not db.get(Client, client_id):
        return redirect("/jobs", "Pick a valid client.", ok=False)
    job = Job(client_id=client_id, name=name.strip(), reference=reference.strip(), notes=notes.strip())
    db.add(job)
    db.flush()
    audit.record(db, current_user(request), "job.create", "job", job.id, f"Created {job.name}")
    db.commit()
    return redirect("/jobs", "Job added.")


@app.post("/jobs/{job_id}/edit")
def jobs_edit(
    job_id: int,
    request: Request,
    client_id: int = Form(...),
    name: str = Form(...),
    reference: str = Form(""),
    notes: str = Form(""),
    active: str = Form(""),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if job:
        if db.get(Client, client_id):
            job.client_id = client_id
        job.name = name.strip()
        job.reference = reference.strip()
        job.notes = notes.strip()
        job.active = active == "on"
        audit.record(db, current_user(request), "job.edit", "job", job.id, f"Edited {job.name}")
        db.commit()
    return redirect("/jobs", "Job saved.")


# ============================================================ history
@app.get("/transactions", response_class=HTMLResponse)
def transactions_page(request: Request, db: Session = Depends(get_db)):
    q = db.query(Transaction)
    month = request.query_params.get("month", "")
    if month:
        try:
            year, mon = (int(x) for x in month.split("-"))
            start, end = reports.month_bounds(year, mon)
            q = q.filter(Transaction.created_at >= start, Transaction.created_at < end)
        except ValueError:
            pass
    txns = q.order_by(Transaction.created_at.desc()).limit(500).all()
    return templates.TemplateResponse("transactions.html", ctx(request, db, txns=txns, month=month))


# ============================================================ audit
@app.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, db: Session = Depends(get_db)):
    q = db.query(AuditLog)
    action = request.query_params.get("action", "")
    user = request.query_params.get("user", "")
    month = request.query_params.get("month", "")
    if action:
        q = q.filter(AuditLog.action.like(f"{action}%"))
    if user:
        q = q.filter(AuditLog.user.like(f"%{user}%"))
    if month:
        try:
            year, mon = (int(x) for x in month.split("-"))
            start, end = reports.month_bounds(year, mon)
            q = q.filter(AuditLog.created_at >= start, AuditLog.created_at < end)
        except ValueError:
            pass
    entries = q.order_by(AuditLog.created_at.desc()).limit(500).all()
    actions = [r[0] for r in db.query(AuditLog.action).distinct().all()]
    return templates.TemplateResponse(
        "audit.html",
        ctx(request, db, entries=entries, actions=sorted(actions), f_action=action, f_user=user, f_month=month),
    )


# ============================================================ reports
def _parse_month(value: str):
    if value:
        try:
            year, mon = (int(x) for x in value.split("-"))
            return year, mon
        except ValueError:
            pass
    now = datetime.utcnow()
    return now.year, now.month


@app.get("/report", response_class=HTMLResponse)
def report_page(request: Request, db: Session = Depends(get_db)):
    year, mon = _parse_month(request.query_params.get("month", ""))
    report, totals = reports.build_report(db, year, mon)
    return templates.TemplateResponse(
        "report.html",
        ctx(request, db, report=report, totals=totals, month=f"{year:04d}-{mon:02d}"),
    )


@app.get("/report.csv")
def report_csv(request: Request, db: Session = Depends(get_db)):
    year, mon = _parse_month(request.query_params.get("month", ""))
    csv_text = reports.report_csv(db, year, mon)
    filename = f"charge-out-{year:04d}-{mon:02d}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================ settings
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "settings.html",
        ctx(request, db, providers=emailer.PROVIDERS, this_month=datetime.utcnow().strftime("%Y-%m"),
            disable_auth=settings.disable_auth),
    )


@app.post("/settings/general")
def settings_general(
    request: Request,
    app_title: str = Form(...),
    currency: str = Form("$"),
    low_stock_threshold: int = Form(5),
    db: Session = Depends(get_db),
):
    store.set(db, "app_title", app_title.strip())
    store.set(db, "currency", currency.strip())
    store.set(db, "low_stock_threshold", low_stock_threshold)
    audit.record(db, current_user(request), "settings.general", "settings", None, "Updated general settings")
    db.commit()
    return redirect("/settings", "General settings saved.")


@app.post("/settings/branding")
def settings_branding(
    request: Request,
    brand_accent: str = Form(""),
    brand_emoji: str = Form("📦"),
    brand_footer: str = Form(""),
    db: Session = Depends(get_db),
):
    store.set(db, "brand_accent", brand_accent.strip())
    store.set(db, "brand_emoji", brand_emoji.strip() or "📦")
    store.set(db, "brand_footer", brand_footer.strip())
    audit.record(db, current_user(request), "settings.branding", "settings", None, "Updated branding")
    db.commit()
    return redirect("/settings", "Branding saved.")


@app.post("/settings/branding/logo")
async def settings_branding_logo(request: Request, logo: UploadFile = File(...), db: Session = Depends(get_db)):
    allowed = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg",
               "image/webp": ".webp", "image/gif": ".gif", "image/x-icon": ".ico"}
    ext = allowed.get(logo.content_type)
    if not ext:
        return redirect("/settings", "Unsupported image type (use PNG, JPG, SVG, WEBP, GIF).", ok=False)
    data = await logo.read()
    if len(data) > 2 * 1024 * 1024:
        return redirect("/settings", "Logo too large (max 2 MB).", ok=False)
    # Stable filename so the old one is overwritten; cache-bust via query string.
    fname = f"logo{ext}"
    with open(os.path.join(UPLOAD_DIR, fname), "wb") as fh:
        fh.write(data)
    store.set(db, "brand_logo", f"/uploads/{fname}?v={secrets.token_hex(4)}")
    audit.record(db, current_user(request), "settings.branding_logo", "settings", None, "Uploaded brand logo")
    db.commit()
    return redirect("/settings", "Logo uploaded.")


@app.post("/settings/branding/logo/remove")
def settings_branding_logo_remove(request: Request, db: Session = Depends(get_db)):
    store.set(db, "brand_logo", "")
    audit.record(db, current_user(request), "settings.branding_logo", "settings", None, "Removed brand logo")
    db.commit()
    return redirect("/settings", "Logo removed.")


@app.post("/settings/auth")
def settings_auth(
    request: Request,
    auth_mode: str = Form("none"),
    oidc_discovery_url: str = Form(""),
    oidc_client_id: str = Form(""),
    oidc_client_secret: str = Form(""),
    oidc_redirect_url: str = Form(""),
    forward_auth_user_header: str = Form(""),
    forward_auth_email_header: str = Form(""),
    db: Session = Depends(get_db),
):
    if auth_mode not in ("none", "oidc", "forward"):
        auth_mode = "none"
    store.set(db, "auth_mode", auth_mode)
    store.set(db, "oidc_discovery_url", oidc_discovery_url.strip())
    store.set(db, "oidc_client_id", oidc_client_id.strip())
    store.set(db, "oidc_redirect_url", oidc_redirect_url.strip())
    store.set(db, "forward_auth_user_header", forward_auth_user_header.strip() or "x-authentik-username")
    store.set(db, "forward_auth_email_header", forward_auth_email_header.strip() or "x-authentik-email")
    if oidc_client_secret:
        store.set(db, "oidc_client_secret", oidc_client_secret)
    audit.record(db, current_user(request), "settings.auth", "settings", None, f"Auth mode set to {auth_mode}")
    db.commit()
    note = "Authentication settings saved."
    if auth_mode == "oidc":
        note += " Log out and back in to test it (break-glass: set DISABLE_AUTH=1 if locked out)."
    return redirect("/settings", note)


@app.post("/settings/email")
def settings_email(
    request: Request,
    email_method: str = Form("none"),
    email_from: str = Form(""),
    email_from_name: str = Form(""),
    smtp_host: str = Form(""),
    smtp_port: str = Form("587"),
    smtp_username: str = Form(""),
    smtp_password: str = Form(""),
    smtp_use_tls: str = Form(""),
    oauth_client_id: str = Form(""),
    oauth_client_secret: str = Form(""),
    oauth_tenant: str = Form("common"),
    db: Session = Depends(get_db),
):
    store.set(db, "email_method", email_method)
    store.set(db, "email_from", email_from.strip())
    store.set(db, "email_from_name", email_from_name.strip())
    store.set(db, "smtp_host", smtp_host.strip())
    store.set(db, "smtp_port", smtp_port.strip() or "587")
    store.set(db, "smtp_username", smtp_username.strip())
    store.set(db, "smtp_use_tls", "1" if smtp_use_tls == "on" else "0")
    store.set(db, "oauth_client_id", oauth_client_id.strip())
    store.set(db, "oauth_tenant", oauth_tenant.strip() or "common")
    if smtp_password:
        store.set(db, "smtp_password", smtp_password)
    if oauth_client_secret:
        store.set(db, "oauth_client_secret", oauth_client_secret)
    audit.record(db, current_user(request), "settings.email", "settings", None, f"Email method set to {email_method}")
    db.commit()
    return redirect("/settings", "Email settings saved.")


@app.post("/settings/email/test")
def settings_email_test(request: Request, test_to: str = Form(...), db: Session = Depends(get_db)):
    ok, message = emailer.send(
        db, test_to, "Inv-Keep test email",
        "<p>This is a test email from your Inv-Keep app. If you got this, email works. 🎉</p>",
    )
    return redirect("/settings", message, ok=ok)


@app.get("/settings/email/oauth/connect")
def email_oauth_connect(request: Request, db: Session = Depends(get_db)):
    method = store.get(db, "email_method")
    if method not in emailer.PROVIDERS:
        return redirect("/settings", "Pick an OAuth email method and save first.", ok=False)
    state = secrets.token_urlsafe(16)
    request.session["email_oauth_state"] = state
    request.session["email_oauth_method"] = method
    redirect_uri = str(request.url_for("email_oauth_callback"))
    url = emailer.authorize_url(db, method, redirect_uri, state)
    return RedirectResponse(url)


@app.get("/settings/email/oauth/callback", name="email_oauth_callback")
def email_oauth_callback(request: Request, db: Session = Depends(get_db)):
    if request.query_params.get("state") != request.session.get("email_oauth_state"):
        return redirect("/settings", "OAuth state mismatch — try again.", ok=False)
    method = request.session.get("email_oauth_method")
    code = request.query_params.get("code")
    if not code or method not in emailer.PROVIDERS:
        return redirect("/settings", "OAuth failed (no code).", ok=False)
    redirect_uri = str(request.url_for("email_oauth_callback"))
    try:
        emailer.exchange_code(db, method, code, redirect_uri)
        audit.record(db, current_user(request), "settings.email_oauth", "settings", None, f"Connected {method}")
        db.commit()
    except Exception as e:  # noqa: BLE001
        return redirect("/settings", f"OAuth token exchange failed: {e}", ok=False)
    return redirect("/settings", "Mailbox connected via OAuth.")


@app.post("/settings/alerts")
def settings_alerts(
    request: Request,
    alert_low_stock_enabled: str = Form(""),
    alert_low_stock_recipients: str = Form(""),
    alert_monthly_enabled: str = Form(""),
    alert_monthly_day: int = Form(1),
    alert_monthly_recipients: str = Form(""),
    db: Session = Depends(get_db),
):
    store.set(db, "alert_low_stock_enabled", "1" if alert_low_stock_enabled == "on" else "0")
    store.set(db, "alert_low_stock_recipients", alert_low_stock_recipients.strip())
    store.set(db, "alert_monthly_enabled", "1" if alert_monthly_enabled == "on" else "0")
    store.set(db, "alert_monthly_day", max(1, min(28, alert_monthly_day)))
    store.set(db, "alert_monthly_recipients", alert_monthly_recipients.strip())
    audit.record(db, current_user(request), "settings.alerts", "settings", None, "Updated alert settings")
    db.commit()
    return redirect("/settings", "Alert settings saved.")


@app.post("/settings/alerts/send-monthly")
def settings_send_monthly(request: Request, month: str = Form(""), to: str = Form(""), db: Session = Depends(get_db)):
    year, mon = _parse_month(month)
    recipients = to.strip() or store.get(db, "alert_monthly_recipients")
    if not recipients:
        return redirect("/settings", "No recipients for the monthly report.", ok=False)
    html = emailer.build_monthly_html(db, year, mon)
    ok, message = emailer.send(db, recipients, f"Monthly charge-out report — {year:04d}-{mon:02d}", html)
    return redirect("/settings", message, ok=ok)

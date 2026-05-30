"""Email sending (SMTP password or OAuth2 XOAUTH2) + alert helpers.

OAuth providers supported: Microsoft 365 and Google, both via SMTP XOAUTH2.
Tokens are stored in the DB settings and refreshed on demand.
"""

import base64
import smtplib
import threading
import time
from datetime import datetime
from email.mime.text import MIMEText

import httpx

from . import settings_store as store
from .database import SessionLocal

# ---- OAuth provider definitions -------------------------------------------
PROVIDERS = {
    "oauth_microsoft": {
        "label": "Microsoft 365 / Outlook",
        "authorize": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "scope": "https://outlook.office.com/SMTP.Send offline_access openid email",
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "extra_authorize": {},
    },
    "oauth_google": {
        "label": "Google / Gmail",
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "https://mail.google.com/",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "extra_authorize": {"access_type": "offline", "prompt": "consent"},
    },
}


def provider_for(method):
    return PROVIDERS.get(method)


# ---- OAuth token handling --------------------------------------------------
def authorize_url(db, method, redirect_uri, state):
    p = PROVIDERS[method]
    tenant = store.get(db, "oauth_tenant") or "common"
    params = {
        "client_id": store.get(db, "oauth_client_id"),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": p["scope"],
        "state": state,
    }
    params.update(p.get("extra_authorize", {}))
    query = str(httpx.QueryParams(params))  # handles URL-encoding
    return p["authorize"].format(tenant=tenant) + "?" + query


def exchange_code(db, method, code, redirect_uri):
    p = PROVIDERS[method]
    tenant = store.get(db, "oauth_tenant") or "common"
    data = {
        "client_id": store.get(db, "oauth_client_id"),
        "client_secret": store.get(db, "oauth_client_secret"),
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    r = httpx.post(p["token"].format(tenant=tenant), data=data, timeout=30)
    r.raise_for_status()
    tok = r.json()
    _store_token(db, tok)


def _store_token(db, tok):
    if tok.get("refresh_token"):
        store.set(db, "oauth_refresh_token", tok["refresh_token"])
    if tok.get("access_token"):
        store.set(db, "oauth_access_token", tok["access_token"])
    expires_in = int(tok.get("expires_in", 3600))
    store.set(db, "oauth_token_expiry", int(time.time()) + expires_in - 60)


def _valid_access_token(db, method):
    expiry = store.get_int(db, "oauth_token_expiry")
    token = store.get(db, "oauth_access_token")
    if token and time.time() < expiry:
        return token
    # refresh
    p = PROVIDERS[method]
    tenant = store.get(db, "oauth_tenant") or "common"
    data = {
        "client_id": store.get(db, "oauth_client_id"),
        "client_secret": store.get(db, "oauth_client_secret"),
        "refresh_token": store.get(db, "oauth_refresh_token"),
        "grant_type": "refresh_token",
        "scope": p["scope"],
    }
    r = httpx.post(p["token"].format(tenant=tenant), data=data, timeout=30)
    r.raise_for_status()
    tok = r.json()
    _store_token(db, tok)
    db.commit()
    return store.get(db, "oauth_access_token")


# ---- Sending ---------------------------------------------------------------
def send(db, recipients, subject, html_body):
    """Send an email now. Returns (ok, message). Raises nothing."""
    method = store.get(db, "email_method")
    if method == "none":
        return False, "Email is disabled (set a method in Settings → Email)."

    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.replace(";", ",").split(",") if r.strip()]
    if not recipients:
        return False, "No recipients."

    from_addr = store.get(db, "email_from")
    from_name = store.get(db, "email_from_name") or from_addr
    if not from_addr:
        return False, "No 'from' address configured."

    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = ", ".join(recipients)

    try:
        if method == "smtp":
            host = store.get(db, "smtp_host")
            port = store.get_int(db, "smtp_port", 587)
            use_tls = store.get_bool(db, "smtp_use_tls")
            username = store.get(db, "smtp_username")
            password = store.get(db, "smtp_password")
            with smtplib.SMTP(host, port, timeout=30) as s:
                if use_tls:
                    s.starttls()
                if username:
                    s.login(username, password)
                s.sendmail(from_addr, recipients, msg.as_string())
        elif method in PROVIDERS:
            p = PROVIDERS[method]
            token = _valid_access_token(db, method)
            auth = base64.b64encode(
                f"user={from_addr}\x01auth=Bearer {token}\x01\x01".encode()
            ).decode()
            with smtplib.SMTP(p["smtp_host"], p["smtp_port"], timeout=30) as s:
                s.starttls()
                s.docmd("AUTH", "XOAUTH2 " + auth)
                s.sendmail(from_addr, recipients, msg.as_string())
        else:
            return False, f"Unknown email method '{method}'."
        return True, f"Sent to {', '.join(recipients)}."
    except Exception as e:  # noqa: BLE001
        return False, f"Send failed: {e}"


def send_async(recipients, subject, html_body):
    """Fire-and-forget send on its own DB session + thread (won't block a scan)."""

    def _run():
        db = SessionLocal()
        try:
            send(db, recipients, subject, html_body)
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()


# ---- Alerts ----------------------------------------------------------------
def maybe_low_stock_alert(db, part):
    """Called after a checkout. Emails once when a part crosses its threshold."""
    if not store.get_bool(db, "alert_low_stock_enabled"):
        return
    recipients = store.get(db, "alert_low_stock_recipients")
    if not recipients:
        return
    threshold = part.low_stock_threshold
    if threshold is None:
        threshold = store.get_int(db, "low_stock_threshold", 5)
    if part.quantity_on_hand <= threshold and not part.low_stock_alerted:
        part.low_stock_alerted = True
        body = (
            f"<p>Low stock alert.</p>"
            f"<p><b>{part.name}</b> (barcode {part.barcode}) is down to "
            f"<b>{part.quantity_on_hand}</b> (threshold {threshold}).</p>"
        )
        send_async(recipients, f"Low stock: {part.name}", body)
    elif part.quantity_on_hand > threshold and part.low_stock_alerted:
        part.low_stock_alerted = False  # reset so it can alert again next time


def build_monthly_html(db, year, month):
    from . import reports

    start, end = reports.month_bounds(year, month)
    return build_report_html(db, start, end)


def build_report_html(db, start, end):
    from . import reports

    report, totals = reports.build_report_range(db, start, end)
    cur = store.get(db, "currency")
    rows = []
    for c in report:
        rows.append(f"<h3>{c['name']}{(' — ' + c['reference']) if c['reference'] else ''}</h3>")
        for job in c["jobs"]:
            jhead = job["name"] + ((' — ' + job["reference"]) if job["reference"] else "")
            rows.append(f"<p style='margin:.3em 0'><b>{jhead}</b></p>")
            rows.append("<table border='1' cellpadding='4' cellspacing='0'>")
            rows.append("<tr><th>Part</th><th>Qty</th><th>Unit</th><th>Total</th></tr>")
            for line in job["lines"]:
                rows.append(
                    f"<tr><td>{line['part']}</td><td>{line['quantity']}</td>"
                    f"<td>{cur}{line['unit_price']:.2f}</td><td>{cur}{line['charge']:.2f}</td></tr>"
                )
            rows.append(f"<tr><td colspan='3'><b>Job subtotal</b></td><td><b>{cur}{job['charge']:.2f}</b></td></tr>")
            rows.append("</table>")
        rows.append(f"<p><b>{c['name']} total: {cur}{c['charge']:.2f}</b></p>")
    rows.append(f"<p style='font-size:1.1em'><b>Grand total (billable): {cur}{totals['charge']:.2f}</b></p>")
    rows.append(f"<p style='color:#666'>Internal — cost: {cur}{totals['cost']:.2f}, margin: {cur}{totals['margin']:.2f}</p>")
    return "".join(rows) if report else "<p>No charge-outs recorded for this period.</p>"


def _send_report(db, recipients, subject, start, end, last_key, tag):
    html = build_report_html(db, start, end)
    ok, _ = send(db, recipients, subject, html)
    if ok:
        store.set(db, last_key, tag)
        db.commit()


def run_due_jobs(db, now=None):
    """Send scheduled report emails (monthly / weekly / daily) at their times, once each."""
    from datetime import timedelta

    from . import reports

    now = now or datetime.utcnow()
    midnight = datetime(now.year, now.month, now.day)

    # ---- Monthly: on day-of-month at hour, billing the previous calendar month ----
    if store.get_bool(db, "alert_monthly_enabled"):
        day = max(1, min(28, store.get_int(db, "alert_monthly_day", 1)))
        hour = store.get_int(db, "alert_monthly_hour", 6)
        rec = store.get(db, "alert_monthly_recipients")
        if rec and (now.day, now.hour) >= (day, hour):
            py, pm = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
            tag = f"{py:04d}-{pm:02d}"
            if store.get(db, "alert_monthly_last_sent") != tag:
                start, end = reports.month_bounds(py, pm)
                _send_report(db, rec, f"Monthly charge-out report — {tag}", start, end,
                             "alert_monthly_last_sent", tag)

    # ---- Weekly: on weekday at hour, billing the previous 7 days ----
    if store.get_bool(db, "alert_weekly_enabled"):
        wd = max(0, min(6, store.get_int(db, "alert_weekly_weekday", 0)))
        hour = store.get_int(db, "alert_weekly_hour", 6)
        rec = store.get(db, "alert_weekly_recipients")
        if rec and now.weekday() == wd and now.hour >= hour:
            iso = now.isocalendar()
            tag = f"{iso[0]}-W{iso[1]:02d}"
            if store.get(db, "alert_weekly_last_sent") != tag:
                _send_report(db, rec, f"Weekly charge-out report — {tag}",
                             midnight - timedelta(days=7), midnight,
                             "alert_weekly_last_sent", tag)

    # ---- Daily: at hour, billing the previous day ----
    if store.get_bool(db, "alert_daily_enabled"):
        hour = store.get_int(db, "alert_daily_hour", 6)
        rec = store.get(db, "alert_daily_recipients")
        if rec and now.hour >= hour:
            tag = now.strftime("%Y-%m-%d")
            if store.get(db, "alert_daily_last_sent") != tag:
                _send_report(db, rec, f"Daily charge-out report — {tag}",
                             midnight - timedelta(days=1), midnight,
                             "alert_daily_last_sent", tag)


# Backwards-compatible alias
def run_monthly_if_due(db, now=None):
    run_due_jobs(db, now)


def scheduler_loop(stop_event):
    """Daemon: wake hourly and run any due scheduled report emails."""
    while not stop_event.wait(3600):
        db = SessionLocal()
        try:
            run_due_jobs(db)
        except Exception:  # noqa: BLE001
            pass
        finally:
            db.close()

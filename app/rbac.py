"""Role-based access control: permissions, default roles, and login resolution.

Roles carry a set of permission keys. Users (created on OIDC/forward login or
managed locally) map to a role. A user's role can be set manually (locked) or
derived from their IdP group claims via a configurable map.
"""

from . import settings_store as store
from .models import Role, User

# (key, human label) — the granular capabilities
PERMISSIONS = [
    ("view", "View the scan / cart screen and history"),
    ("view_catalog", "Browse items, categories, clients & jobs (read-only)"),
    ("see_cost", "See our cost (margin) — not just client price"),
    ("checkout", "Scan / charge out & void"),
    ("manage_items", "Add/edit items & categories, restock"),
    ("manage_clients", "Manage clients & jobs"),
    ("manage_locations", "Manage stock locations & transfers"),
    ("view_audit", "View the audit log"),
    ("manage_settings", "Change settings (branding, email, printing, auth)"),
    ("manage_users", "Manage users, roles & permissions"),
]
ALL_PERMS = [p[0] for p in PERMISSIONS]

# Granted alongside any manage_* perm — if you can edit items, you can
# obviously see them. Keeps backfill from stripping browse rights from
# previously-customised non-Admin roles.
_BROWSE_IMPLIED_BY = {"manage_items", "manage_clients", "manage_locations"}

DEFAULT_ROLES = {
    "Admin":    {"perms": ALL_PERMS, "admin": True},
    "Manager":  {"perms": ["view", "view_catalog", "see_cost", "checkout", "manage_items", "manage_clients", "manage_locations", "view_audit"], "admin": False},
    # Operator does charge-out — they need to browse the catalog to find a
    # part by name but should NOT see our cost (only client price).
    "Operator": {"perms": ["view", "view_catalog", "checkout"], "admin": False},
    # Viewer is the read-only audit role — sees everything including costs.
    "Viewer":   {"perms": ["view", "view_catalog", "see_cost", "view_audit"], "admin": False},
    # Kiosk role is granted automatically when a session authenticates via
    # the kiosk PIN. It includes `view` (scan + cart pages) and
    # `view_catalog` (browse items / categories / clients / jobs without
    # editing) by default. It does NOT get `see_cost` so the "Our cost"
    # column stays hidden on a shared front-desk device.
    "Kiosk":    {"perms": ["view", "view_catalog", "checkout"], "admin": False},
}


def seed_roles(db):
    for name, info in DEFAULT_ROLES.items():
        row = db.query(Role).filter(Role.name == name).first()
        if row is None:
            db.add(Role(name=name, permissions=",".join(info["perms"]),
                        is_admin=info["admin"], builtin=True, customized=False))
            continue
        # Backfill: a previously-seeded built-in role may have an older perm
        # set. Add any default perm it's missing, but never remove what an
        # admin has manually toggled on. Once the admin has saved the role
        # through the UI (customized=True) we leave it strictly alone, so
        # removing a default perm (e.g. dropping `view_catalog` from Kiosk)
        # actually sticks across restarts.
        if row.builtin and not bool(getattr(row, "customized", False)):
            existing = {p.strip() for p in (row.permissions or "").split(",") if p.strip()}
            missing = [p for p in info["perms"] if p not in existing]
            if missing:
                merged = sorted(existing.union(info["perms"]))
                row.permissions = ",".join(merged)
    db.commit()


def perms_for_role(role):
    if role is None:
        return set()
    if role.is_admin:
        return set(ALL_PERMS)
    return {p.strip() for p in (role.permissions or "").split(",") if p.strip()}


def _parse_group_map(raw):
    """Lines like 'developers = Admin' -> {'developers': 'Admin'}."""
    mapping = {}
    for line in (raw or "").replace(";", "\n").splitlines():
        line = line.strip()
        if not line:
            continue
        sep = "=" if "=" in line else (":" if ":" in line else None)
        if not sep:
            continue
        g, r = line.split(sep, 1)
        mapping[g.strip()] = r.strip()
    return mapping


def _role_by_name(db, name):
    if not name:
        return None
    return db.query(Role).filter(Role.name == name).first()


def admin_dict(username="local", email=""):
    return {"username": username, "email": email, "role": "Admin",
            "perms": set(ALL_PERMS), "is_admin": True}


def resolve_login(db, username, email, groups):
    """Find/create the user, decide their role, return the auth dict for the request."""
    seed_roles(db)
    email = (email or "").strip()
    username = (username or "").strip() or email or "user"
    groups = groups or []

    admin_emails = {e.strip().lower() for e in store.get(db, "rbac_admin_emails").replace(";", ",").split(",") if e.strip()}
    default_role_name = store.get(db, "rbac_default_role") or "Admin"
    auto_create = store.get_bool(db, "rbac_auto_create")
    group_map = _parse_group_map(store.get(db, "oidc_group_role_map"))

    # existing user by email (preferred) then username
    user = None
    if email:
        user = db.query(User).filter(User.email == email).first()
    if not user:
        user = db.query(User).filter(User.username == username).first()

    # Determine the role to apply (unless the user is locked to a manual role)
    def derive_role():
        if email and email.lower() in admin_emails:
            return _role_by_name(db, "Admin")
        for g in groups:
            if g in group_map:
                r = _role_by_name(db, group_map[g])
                if r:
                    return r
        return _role_by_name(db, default_role_name) or _role_by_name(db, "Viewer")

    if user and user.locked and user.role:
        role = user.role
    else:
        role = derive_role()

    if user is None:
        if auto_create:
            user = User(username=username, email=email, role_id=role.id if role else None,
                        active=True, source="idp", locked=False)
            db.add(user)
            db.commit()
        # else: not stored, but still grant the derived role for this session
    else:
        if not user.active:
            return None  # deactivated user — deny
        if not user.locked and role and user.role_id != role.id:
            user.role_id = role.id
            db.commit()

    perms = perms_for_role(role)
    return {"username": username, "email": email, "role": role.name if role else "",
            "perms": perms, "is_admin": bool(role and role.is_admin)}


# ---- per-request permission requirements -----------------------------------
def required_perm(path, method):
    if path.startswith("/api/checkout") or path.startswith("/api/void"):
        return "checkout"
    if path.startswith("/users"):
        return "manage_users"
    if path.startswith("/settings"):
        return "manage_settings"
    if path.startswith("/audit"):
        return "view_audit"
    if path.startswith("/locations") or path.startswith("/transfers"):
        return "manage_locations"
    if method == "POST" and (path.startswith("/parts") or path.startswith("/categories")):
        return "manage_items"
    if method == "POST" and (path.startswith("/clients") or path.startswith("/jobs")):
        return "manage_clients"
    # Browsing the catalog (items, categories, clients, jobs) requires
    # view_catalog rather than the bare `view` so a Kiosk role can be
    # configured to see the catalog read-only without unlocking edits.
    if method == "GET" and (
        path.startswith("/parts")
        or path.startswith("/categories")
        or path.startswith("/clients")
        or path.startswith("/jobs")
        or path.startswith("/labels")
        or path.startswith("/map")
        or path.startswith("/report")
    ):
        return "view_catalog"
    return "view"

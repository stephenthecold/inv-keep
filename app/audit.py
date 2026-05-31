from .models import AuditLog


def _strip_control(s):
    """Drop ASCII control chars (except tab) so attacker-injected newlines/escape
    sequences can't poison downstream log shippers that consume the raw column."""
    return "".join(c for c in (s or "") if c == "\t" or c >= " ")


def record(db, user, action, entity_type="", entity_id=None, summary=""):
    """Add an audit entry to the session. Caller is responsible for commit."""
    if isinstance(user, dict):
        user = user.get("username", "")
    db.add(
        AuditLog(
            user=_strip_control(user or ""),
            action=_strip_control(action),
            entity_type=_strip_control(entity_type),
            entity_id=entity_id,
            summary=_strip_control(summary),
        )
    )

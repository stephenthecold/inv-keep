from .models import AuditLog


def record(db, user, action, entity_type="", entity_id=None, summary=""):
    """Add an audit entry to the session. Caller is responsible for commit."""
    if isinstance(user, dict):
        user = user.get("username", "")
    db.add(
        AuditLog(
            user=user or "",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
        )
    )

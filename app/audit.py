from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User


def audit(
    db: AsyncSession,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Adds a journal row to the caller's transaction — it commits (or rolls
    back) together with the change it describes."""
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            actor_username=actor.username if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )

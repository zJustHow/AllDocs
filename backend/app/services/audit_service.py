from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminAuditLog


async def record_admin_audit(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    action: str,
    target_user_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> AdminAuditLog:
    log = AdminAuditLog(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        action=action,
        details=details,
    )
    db.add(log)
    await db.flush()
    return log

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import require_admin
from app.db.models import AdminAuditLog, User, UserIdentity, UserRole
from app.db.session import get_db
from app.services.audit_service import record_admin_audit
from app.services.auth_service import user_email, user_phone

users_router = APIRouter(prefix="/admin/users", tags=["admin"])
audit_router = APIRouter(prefix="/admin/audit-logs", tags=["admin"])


class AdminUserItem(BaseModel):
    id: str
    role: str
    display_name: str | None
    email: str | None
    phone: str | None
    wechat_bound: bool
    is_active: bool
    created_at: str


class AdminUserListResponse(BaseModel):
    users: list[AdminUserItem]


class AdminUserPatchRequest(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    display_name: str | None = Field(default=None, max_length=128)


class AdminAuditLogItem(BaseModel):
    id: str
    action: str
    actor_user_id: str
    actor_display_name: str | None
    target_user_id: str | None
    target_display_name: str | None
    details: dict | None
    created_at: str


class AdminAuditLogListResponse(BaseModel):
    logs: list[AdminAuditLogItem]


def _serialize_user(user: User, identities: list[UserIdentity]) -> AdminUserItem:
    email: str | None = None
    phone: str | None = None
    wechat_bound = False
    for identity in identities:
        if identity.provider == "email":
            email = user_email(identity)
        elif identity.provider == "phone":
            phone = user_phone(identity)
        elif identity.provider == "wechat":
            wechat_bound = True
    return AdminUserItem(
        id=str(user.id),
        role=user.role.value,
        display_name=user.display_name,
        email=email,
        phone=phone,
        wechat_bound=wechat_bound,
        is_active=user.is_active,
        created_at=user.created_at.isoformat(),
    )


@users_router.get("", response_model=AdminUserListResponse)
async def list_users(
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminUserListResponse:
    stmt = select(User).order_by(User.created_at.desc())
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    users = list(result.scalars().all())
    if not users:
        return AdminUserListResponse(users=[])

    identity_result = await db.execute(
        select(UserIdentity).where(UserIdentity.user_id.in_([user.id for user in users]))
    )
    identities_by_user: dict[uuid.UUID, list[UserIdentity]] = {}
    for identity in identity_result.scalars().all():
        identities_by_user.setdefault(identity.user_id, []).append(identity)

    return AdminUserListResponse(
        users=[
            _serialize_user(user, identities_by_user.get(user.id, []))
            for user in users
        ]
    )


@users_router.patch("/{user_id}", response_model=AdminUserItem)
async def patch_user(
    user_id: uuid.UUID,
    body: AdminUserPatchRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminUserItem:
    if user_id == admin.id and body.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot disable your own account")
    if user_id == admin.id and body.role == UserRole.user:
        raise HTTPException(status_code=400, detail="Cannot demote your own account")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    changes: dict[str, dict[str, str | bool | None]] = {}
    if body.role is not None and body.role != user.role:
        changes["role"] = {"from": user.role.value, "to": body.role.value}
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = {"from": user.is_active, "to": body.is_active}
        user.is_active = body.is_active
    if body.display_name is not None and body.display_name != user.display_name:
        changes["display_name"] = {"from": user.display_name, "to": body.display_name or None}
        user.display_name = body.display_name or None

    if changes:
        await record_admin_audit(
            db,
            actor_user_id=admin.id,
            action="user.update",
            target_user_id=user.id,
            details=changes,
        )

    await db.commit()
    await db.refresh(user)

    identity_result = await db.execute(select(UserIdentity).where(UserIdentity.user_id == user.id))
    identities = list(identity_result.scalars().all())
    return _serialize_user(user, identities)


@audit_router.get("", response_model=AdminAuditLogListResponse)
async def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminAuditLogListResponse:
    result = await db.execute(
        select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(limit)
    )
    logs = list(result.scalars().all())
    if not logs:
        return AdminAuditLogListResponse(logs=[])

    user_ids = {log.actor_user_id for log in logs}
    user_ids.update(log.target_user_id for log in logs if log.target_user_id)
    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    users_by_id = {user.id: user for user in users_result.scalars().all()}

    return AdminAuditLogListResponse(
        logs=[
            AdminAuditLogItem(
                id=str(log.id),
                action=log.action,
                actor_user_id=str(log.actor_user_id),
                actor_display_name=(
                    users_by_id[log.actor_user_id].display_name
                    if log.actor_user_id in users_by_id
                    else None
                ),
                target_user_id=str(log.target_user_id) if log.target_user_id else None,
                target_display_name=(
                    users_by_id.get(log.target_user_id).display_name
                    if log.target_user_id and log.target_user_id in users_by_id
                    else None
                ),
                details=log.details,
                created_at=log.created_at.isoformat(),
            )
            for log in logs
        ]
    )

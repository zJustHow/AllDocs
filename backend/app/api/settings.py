from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import require_admin
from app.db.models import User
from app.db.session import get_db
from app.services.audit_service import record_admin_audit
from app.services.runtime_settings import build_settings_response, update_overrides

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsPatchRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


@router.get("")
async def read_settings(_: User = Depends(require_admin)) -> dict[str, Any]:
    return build_settings_response()


@router.patch("")
async def patch_settings(
    body: SettingsPatchRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    if not body.values:
        raise HTTPException(status_code=400, detail="No values provided")

    try:
        _, changes = await db.run_sync(lambda session: update_overrides(session, body.values))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if changes:
        await record_admin_audit(
            db,
            actor_user_id=admin.id,
            action="settings.update",
            details=changes,
        )
        await db.commit()

    return build_settings_response()

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import get_current_user, get_current_user_flexible
from app.db.models import ChunkAsset, Document, DocumentStatus, User
from app.db.session import get_db
from app.services.storage import StorageService

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/{asset_id}")
async def get_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user_flexible),
) -> Response:
    result = await db.execute(
        select(ChunkAsset).where(ChunkAsset.id == asset_id).limit(1)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    document = await db.get(Document, asset.document_id)
    if not document or document.status == DocumentStatus.deleting:
        raise HTTPException(status_code=404, detail="Asset not found")

    storage = StorageService()
    data = await asyncio.to_thread(storage.download, asset.object_key)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )

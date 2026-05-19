from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from ..database import get_db
from ..models import PushToken
from ..schemas import PushTokenIn
from ..auth import get_current_user, CurrentUser

router = APIRouter(prefix='/voip/push', tags=['push'])


@router.post('/register', status_code=204)
async def register_push_token(
    body: PushTokenIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    if not current.extension_id:
        raise HTTPException(400, 'No extension assigned to this user')

    # Remove old tokens for same extension + platform + voip type
    await db.execute(
        delete(PushToken).where(
            PushToken.extension_id == current.extension_id,
            PushToken.platform == body.platform,
            PushToken.is_voip_push == body.is_voip_push,
        )
    )

    token = PushToken(
        extension_id=current.extension_id,
        platform=body.platform,
        token=body.token,
        is_voip_push=body.is_voip_push,
    )
    db.add(token)
    await db.commit()


@router.delete('/unregister', status_code=204)
async def unregister_push_token(
    token: str,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    await db.execute(
        delete(PushToken).where(
            PushToken.token == token,
            PushToken.extension_id == current.extension_id,
        )
    )
    await db.commit()

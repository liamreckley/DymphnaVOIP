from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc
from datetime import datetime, timezone
from ..database import get_db
from ..models import Voicemail
from ..schemas import VoicemailOut
from ..auth import get_current_user, CurrentUser

router = APIRouter(prefix='/voip/voicemail', tags=['voicemail'])


@router.get('', response_model=list[VoicemailOut])
async def list_voicemails(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    stmt = (
        select(Voicemail)
        .where(
            Voicemail.extension_id == current.extension_id,
            Voicemail.deleted == False,
        )
        .order_by(desc(Voicemail.received_at))
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.patch('/{voicemail_id}/listened', status_code=204)
async def mark_listened(
    voicemail_id: str,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    result = await db.execute(
        select(Voicemail).where(
            Voicemail.id == voicemail_id,
            Voicemail.extension_id == current.extension_id,
        )
    )
    vm = result.scalar_one_or_none()
    if not vm:
        raise HTTPException(404, 'Voicemail not found')
    vm.listened = True
    vm.listened_at = datetime.now(timezone.utc)
    await db.commit()


@router.delete('/{voicemail_id}', status_code=204)
async def delete_voicemail(
    voicemail_id: str,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    result = await db.execute(
        select(Voicemail).where(
            Voicemail.id == voicemail_id,
            Voicemail.extension_id == current.extension_id,
        )
    )
    vm = result.scalar_one_or_none()
    if not vm:
        raise HTTPException(404, 'Voicemail not found')
    vm.deleted = True
    await db.commit()

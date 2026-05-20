from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..database import get_db
from ..models import Extension as ExtModel
from ..schemas import ExtensionOut, ExtensionCreate, ExtensionUpdate, PresenceUpdate
from ..auth import get_current_user, require_admin, CurrentUser
from ..services import pjsip_provisioner
import secrets

router = APIRouter(prefix='/voip/extensions', tags=['extensions'])


@router.get('', response_model=list[ExtensionOut])
async def list_extensions(
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    result = await db.execute(select(ExtModel).where(ExtModel.is_active == True))
    return result.scalars().all()


@router.get('/me', response_model=ExtensionOut)
async def get_my_extension(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    # Look up by extensionId from JWT first, fall back to ehr_user_id
    if current.extension_id:
        result = await db.execute(select(ExtModel).where(ExtModel.id == current.extension_id))
    else:
        result = await db.execute(select(ExtModel).where(ExtModel.ehr_user_id == current.user_id))

    ext = result.scalar_one_or_none()
    if not ext:
        raise HTTPException(404, 'No extension assigned')
    return ext


@router.post('', response_model=ExtensionOut, status_code=201)
async def create_extension(
    body: ExtensionCreate,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    sip_password = secrets.token_urlsafe(16)
    ext = ExtModel(**body.model_dump(), sip_password=sip_password)
    db.add(ext)
    await db.commit()
    await db.refresh(ext)

    # Write PJSIP endpoint block and reload Asterisk
    await pjsip_provisioner.provision_extension(
        number=ext.extension_number,
        password=sip_password,
        display_name=ext.display_name,
    )

    return ext


@router.delete('/{extension_id}', status_code=204)
async def delete_extension(
    extension_id: str,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    result = await db.execute(select(ExtModel).where(ExtModel.id == extension_id))
    ext = result.scalar_one_or_none()
    if not ext:
        raise HTTPException(404, 'Extension not found')

    ext.is_active = False
    await db.commit()

    await pjsip_provisioner.deprovision_extension(ext.extension_number)


@router.patch('/me', status_code=204)
async def update_my_extension(
    body: ExtensionUpdate,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    """Staff can update their own forwarding number and display name."""
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    if not values:
        return
    if current.extension_id:
        await db.execute(update(ExtModel).where(ExtModel.id == current.extension_id).values(**values))
    else:
        await db.execute(update(ExtModel).where(ExtModel.ehr_user_id == current.user_id).values(**values))
    await db.commit()


@router.patch('/me/presence', status_code=204)
async def update_my_presence(
    body: PresenceUpdate,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    if current.extension_id:
        await db.execute(
            update(ExtModel)
            .where(ExtModel.id == current.extension_id)
            .values(presence_status=body.status)
        )
    else:
        await db.execute(
            update(ExtModel)
            .where(ExtModel.ehr_user_id == current.user_id)
            .values(presence_status=body.status)
        )
    await db.commit()


@router.get('/{extension_id}/sip-credentials')
async def get_sip_credentials(
    extension_id: str,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    """Return SIP credentials. Only the owning user or an admin can fetch."""
    if current.extension_id != extension_id and current.voip_role != 'admin':
        raise HTTPException(403, 'Cannot retrieve another user\'s SIP credentials')
    result = await db.execute(select(ExtModel).where(ExtModel.id == extension_id))
    ext = result.scalar_one_or_none()
    if not ext:
        raise HTTPException(404, 'Extension not found')
    return {
        'extension_number': ext.extension_number,
        'sip_username': ext.extension_number,
        'sip_password': ext.sip_password,
        'sip_domain': 'voip.dymphnacounseling.com',
        'sip_port': 5060,
        'transport': 'UDP',
    }

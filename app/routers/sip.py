"""SIP/WebRTC credentials for the mobile softphone.

The app registers to Asterisk over secure WebSocket using these values. Credentials
are per-extension (sip_password) and are only returned to the owning user.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..models import Extension as ExtModel
from ..auth import get_current_user, CurrentUser
from ..config import settings

router = APIRouter(prefix='/voip/sip', tags=['sip'])


def _ice_servers() -> list[dict]:
    servers: list[dict] = [{'urls': settings.stun_url}]
    if settings.turn_url:
        servers.append({
            'urls': settings.turn_url,
            'username': settings.turn_username,
            'credential': settings.turn_password,
        })
    return servers


@router.get('/credentials')
async def get_sip_credentials(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    """Return the caller's WebRTC SIP registration details."""
    if current.extension_id:
        result = await db.execute(select(ExtModel).where(ExtModel.id == current.extension_id))
    else:
        result = await db.execute(select(ExtModel).where(ExtModel.ehr_user_id == current.user_id))
    ext = result.scalar_one_or_none()
    if not ext:
        raise HTTPException(404, 'No extension assigned. Ask an admin to create your extension.')

    return {
        'username': ext.extension_number,
        'password': ext.sip_password,
        'displayName': ext.display_name,
        'sipDomain': settings.sip_domain,
        'wsUri': f'wss://{settings.sip_ws_host}:{settings.sip_ws_port}/ws',
        'iceServers': _ice_servers(),
    }

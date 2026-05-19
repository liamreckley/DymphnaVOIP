"""WebSocket presence endpoint — broadcasts real-time extension status to all connected staff."""
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..database import get_db, AsyncSessionLocal
from ..models import Extension
from ..auth import CurrentUser
from ..config import settings
from jose import jwt, JWTError

log = logging.getLogger(__name__)
router = APIRouter(tags=['presence'])

# All active WebSocket connections keyed by extension_id
_connections: dict[str, WebSocket] = {}


async def _broadcast(message: dict, exclude_id: str | None = None) -> None:
    dead = []
    for ext_id, ws in list(_connections.items()):
        if ext_id == exclude_id:
            continue
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ext_id)
    for ext_id in dead:
        _connections.pop(ext_id, None)


async def _get_extension_from_token(token: str) -> Extension | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    extension_id = payload.get('extensionId')
    if not extension_id:
        return None
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Extension).where(Extension.id == extension_id))
        return result.scalar_one_or_none()


@router.websocket('/voip/ws/presence')
async def presence_ws(
    websocket: WebSocket,
    token: str = Query(''),
):
    ext = await _get_extension_from_token(token)
    if not ext:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    _connections[ext.id] = websocket
    log.info('Presence WS connected: %s (%s)', ext.display_name, ext.extension_number)

    # Send current presence snapshot to the newly connected client
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Extension).where(Extension.is_active == True))
        all_exts = result.scalars().all()

    snapshot = [
        {
            'type': 'presence_snapshot',
            'extension_id': e.id,
            'user_id': e.ehr_user_id,
            'display_name': e.display_name,
            'status': e.presence_status,
        }
        for e in all_exts
    ]
    await websocket.send_json({'type': 'snapshot', 'data': snapshot})

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get('type') == 'presence_update':
                new_status = msg.get('status', 'available')
                # Persist to DB
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(Extension)
                        .where(Extension.id == ext.id)
                        .values(presence_status=new_status)
                    )
                    await db.commit()
                # Broadcast to all others
                await _broadcast({
                    'type': 'presence_update',
                    'extension_id': ext.id,
                    'user_id': ext.ehr_user_id,
                    'display_name': ext.display_name,
                    'status': new_status,
                }, exclude_id=ext.id)

    except WebSocketDisconnect:
        _connections.pop(ext.id, None)
        log.info('Presence WS disconnected: %s', ext.display_name)
        # Mark offline
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Extension)
                .where(Extension.id == ext.id)
                .values(presence_status='offline')
            )
            await db.commit()
        await _broadcast({
            'type': 'presence_update',
            'extension_id': ext.id,
            'user_id': ext.ehr_user_id,
            'display_name': ext.display_name,
            'status': 'offline',
        })

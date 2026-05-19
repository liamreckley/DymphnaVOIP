from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc
from datetime import datetime, timezone
from ..database import get_db
from ..models import SmsThread, SmsMessage
from ..schemas import SmsThreadOut, SmsMessageOut, SmsSendIn, SmsAssignIn
from ..auth import get_current_user, require_receptionist_or_admin, CurrentUser
from ..services import voipms

router = APIRouter(prefix='/voip/sms', tags=['sms'])


# ─── Threads ──────────────────────────────────────────────────────────────────

@router.get('/threads', response_model=list[SmsThreadOut])
async def list_threads(
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_receptionist_or_admin),
):
    stmt = (
        select(SmsThread)
        .where(SmsThread.status != 'archived')
        .order_by(desc(SmsThread.last_message_at))
    )
    result = await db.execute(stmt)
    threads = result.scalars().all()

    if search:
        s = search.lower()
        threads = [
            t for t in threads
            if s in (t.contact_name or '').lower() or s in t.external_number
        ]

    return [
        SmsThreadOut(
            id=t.id,
            external_number=t.external_number,
            contact_name=t.contact_name,
            last_message_at=t.last_message_at,
            last_message_body=t.last_message_body,
            unread_count=t.unread_count,
            assigned_to_id=t.assigned_to_id,
            assigned_to_name=t.assigned_to.display_name if t.assigned_to else None,
            status=t.status,
        )
        for t in threads
    ]


@router.get('/threads/{thread_id}')
async def get_thread(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_receptionist_or_admin),
):
    result = await db.execute(select(SmsThread).where(SmsThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(404, 'Thread not found')

    msgs_result = await db.execute(
        select(SmsMessage)
        .where(SmsMessage.thread_id == thread_id)
        .order_by(SmsMessage.sent_at)
    )
    messages = msgs_result.scalars().all()

    # Mark as read
    thread.unread_count = 0
    await db.commit()

    return {
        'thread': SmsThreadOut(
            id=thread.id,
            external_number=thread.external_number,
            contact_name=thread.contact_name,
            last_message_at=thread.last_message_at,
            last_message_body=thread.last_message_body,
            unread_count=0,
            assigned_to_id=thread.assigned_to_id,
            assigned_to_name=thread.assigned_to.display_name if thread.assigned_to else None,
            status=thread.status,
        ),
        'messages': [
            SmsMessageOut(
                id=m.id,
                thread_id=m.thread_id,
                direction=m.direction,
                body=m.body,
                sent_at=m.sent_at,
                sent_by_id=m.sent_by_id,
                sender_name=m.sent_by.display_name if m.sent_by else None,
                status=m.status,
            )
            for m in messages
        ],
    }


# ─── Send ─────────────────────────────────────────────────────────────────────

@router.post('/send', status_code=201)
async def send_sms(
    body: SmsSendIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_receptionist_or_admin),
):
    # Normalize number
    to_number = body.to_number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

    # Find or create thread
    if body.thread_id:
        result = await db.execute(select(SmsThread).where(SmsThread.id == body.thread_id))
        thread = result.scalar_one_or_none()
        if not thread:
            raise HTTPException(404, 'Thread not found')
    else:
        result = await db.execute(select(SmsThread).where(SmsThread.external_number == to_number))
        thread = result.scalar_one_or_none()
        if not thread:
            thread = SmsThread(external_number=to_number)
            db.add(thread)
            await db.flush()

    # Send via VoIP.ms
    voipms_id = await voipms.send_sms(to_number, body.body)

    # Save message
    msg = SmsMessage(
        thread_id=thread.id,
        direction='outbound',
        body=body.body,
        sent_by_id=current.extension_id,
        status='sent',
        voipms_message_id=voipms_id,
    )
    db.add(msg)

    # Update thread summary
    thread.last_message_body = body.body
    thread.last_message_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(msg)

    return {'message_id': msg.id, 'thread_id': thread.id}


# ─── Assign / Archive ─────────────────────────────────────────────────────────

@router.patch('/threads/{thread_id}/assign', status_code=204)
async def assign_thread(
    thread_id: str,
    body: SmsAssignIn,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_receptionist_or_admin),
):
    result = await db.execute(select(SmsThread).where(SmsThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(404, 'Thread not found')
    thread.assigned_to_id = body.extension_id
    await db.commit()


@router.patch('/threads/{thread_id}/archive', status_code=204)
async def archive_thread(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_receptionist_or_admin),
):
    result = await db.execute(select(SmsThread).where(SmsThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(404, 'Thread not found')
    thread.status = 'archived'
    await db.commit()


# ─── Inbound webhook (VoIP.ms posts to this endpoint) ────────────────────────

@router.post('/inbound')
async def receive_inbound_sms(
    from_number: str,
    message: str,
    token: str = '',
    db: AsyncSession = Depends(get_db),
):
    from ..config import settings
    from fastapi import HTTPException
    if settings.voipms_webhook_token and token != settings.voipms_webhook_token:
        raise HTTPException(403, 'Invalid webhook token')
    """VoIP.ms calls this URL when an inbound SMS arrives on the DID."""
    # Normalize
    from_number = from_number.strip()

    # Find or create thread
    result = await db.execute(select(SmsThread).where(SmsThread.external_number == from_number))
    thread = result.scalar_one_or_none()
    if not thread:
        thread = SmsThread(external_number=from_number)
        db.add(thread)
        await db.flush()

    msg = SmsMessage(
        thread_id=thread.id,
        direction='inbound',
        body=message,
        status='delivered',
    )
    db.add(msg)
    thread.last_message_body = message
    thread.last_message_at = datetime.now(timezone.utc)
    thread.unread_count = thread.unread_count + 1
    await db.commit()

    return {'ok': True}

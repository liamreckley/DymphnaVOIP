from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from ..database import get_db
from ..models import Call, CallNote, CallLeg, Extension as ExtModel
from ..schemas import CallLogOut, CallNoteIn, HoldIn, TransferIn
from ..auth import get_current_user, CurrentUser
from ..services import asterisk
from pydantic import BaseModel

router = APIRouter(prefix='/voip/calls', tags=['calls'])


class OriginateIn(BaseModel):
    to_number: str
    from_extension: str


class MuteIn(BaseModel):
    channel: str
    muted: bool


def _to_call_log_out(call: Call) -> dict:
    note_body = call.note.body if call.note else None
    return {
        'id': call.id,
        'direction': call.direction,
        'remote_number': call.remote_number,
        'contact_name': call.contact_name,
        'started_at': call.started_at,
        'answered_at': call.answered_at,
        'ended_at': call.ended_at,
        'duration': call.duration,
        'disposition': call.disposition,
        'recording_url': call.recording_url,
        'has_recording': bool(call.recording_url),
        'note': note_body,
    }


@router.get('', response_model=list[CallLogOut])
async def get_call_log(
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    stmt = (
        select(Call)
        .order_by(desc(Call.started_at))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    calls = result.scalars().all()
    return [_to_call_log_out(c) for c in calls]


@router.get('/{call_id}', response_model=CallLogOut)
async def get_call(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    result = await db.execute(select(Call).where(Call.id == call_id))
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(404, 'Call not found')
    return _to_call_log_out(call)


@router.post('/{call_id}/note', status_code=204)
async def add_call_note(
    call_id: str,
    body: CallNoteIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    result = await db.execute(select(Call).where(Call.id == call_id))
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(404, 'Call not found')

    if call.note:
        call.note.body = body.body
    else:
        note = CallNote(
            call_id=call_id,
            author_extension_id=current.extension_id or '',
            body=body.body,
        )
        db.add(note)
    await db.commit()


# ─── Originate outbound call ──────────────────────────────────────────────────

@router.post('/originate', status_code=201)
async def originate_call(
    body: OriginateIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    """Click-to-call: look up staff's forwarding number, then instruct Asterisk
    to call their cell first and bridge to the client number."""

    # Look up the calling staff member's extension to get their forwarding number
    if current.extension_id:
        result = await db.execute(select(ExtModel).where(ExtModel.id == current.extension_id))
    else:
        result = await db.execute(select(ExtModel).where(ExtModel.ehr_user_id == current.user_id))
    ext = result.scalar_one_or_none()

    if not ext or not ext.forwarding_number:
        raise HTTPException(400, 'No forwarding number set on your extension. Ask an admin to add your cell number.')

    # Normalize client number to 10 digits
    digits = ''.join(c for c in body.to_number if c.isdigit())
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    if len(digits) != 10:
        raise HTTPException(400, 'Invalid phone number — must be a 10-digit US number')

    result = await asterisk.originate_call(ext.forwarding_number, digits)
    return {'status': 'dialing', 'message': f'Your phone will ring shortly. Answer to connect to {body.to_number}.'}


# ─── Active call controls (AMI passthrough) ───────────────────────────────────

@router.post('/{call_id}/hold', status_code=204)
async def hold_call(
    call_id: str,
    body: HoldIn,
    _: CurrentUser = Depends(get_current_user),
):
    await asterisk.hold_channel(body.channel)


@router.post('/{call_id}/unhold', status_code=204)
async def unhold_call(
    call_id: str,
    body: HoldIn,
    _: CurrentUser = Depends(get_current_user),
):
    await asterisk.unhold_channel(body.channel)


@router.post('/{call_id}/mute', status_code=204)
async def mute_call(
    call_id: str,
    body: MuteIn,
    _: CurrentUser = Depends(get_current_user),
):
    if body.muted:
        await asterisk.mute_channel(body.channel)
    else:
        await asterisk.unmute_channel(body.channel)


@router.post('/{call_id}/transfer', status_code=204)
async def transfer_call(
    call_id: str,
    body: TransferIn,
    _: CurrentUser = Depends(get_current_user),
):
    if body.attended:
        await asterisk.attended_transfer(body.channel, body.destination)
    else:
        await asterisk.blind_transfer(body.channel, body.destination)


@router.post('/{call_id}/park', status_code=204)
async def park_call(
    call_id: str,
    body: HoldIn,
    _: CurrentUser = Depends(get_current_user),
):
    await asterisk.park_call(body.channel, body.channel)


@router.post('/{call_id}/end', status_code=204)
async def end_call(
    call_id: str,
    body: HoldIn,
    _: CurrentUser = Depends(get_current_user),
):
    await asterisk.hangup_channel(body.channel)


@router.post('/pickup/{extension_number}', status_code=204)
async def pickup_extension(
    extension_number: str,
    _: CurrentUser = Depends(get_current_user),
):
    await asterisk.pickup_extension(extension_number)


@router.get('/lookup/{phone_number}')
async def lookup_number(
    phone_number: str,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """CRM pop: look up a phone number in the EHR contact database."""
    # TODO: query EHR PostgreSQL for matching client
    return {'found': False, 'contact': None}

"""Asterisk AMI client — call control + real-time event listener for CDR logging."""
import asyncio
import logging
from datetime import datetime, timezone
from panoramisk import Manager
from ..config import settings

log = logging.getLogger(__name__)

_manager: Manager | None = None
_listener_task: asyncio.Task | None = None


async def get_manager() -> Manager:
    global _manager
    if _manager is None or not _manager.connected:
        _manager = Manager(
            host=settings.asterisk_host,
            port=settings.asterisk_port,
            username=settings.asterisk_username,
            secret=settings.asterisk_secret,
        )
        await _manager.connect()
    return _manager


# ─── Call control ─────────────────────────────────────────────────────────────

async def originate_call(extension_number: str, remote_number: str) -> dict:
    """Dial remote_number and bridge to extension."""
    mgr = await get_manager()
    result = await mgr.send_action({
        'Action': 'Originate',
        'Channel': f'PJSIP/{extension_number}',
        'Exten': remote_number,
        'Context': 'dymphna-outbound',
        'Priority': 1,
        'CallerID': f'Dymphna <{settings.voipms_did}>',
        'Async': 'true',
    })
    return result


async def hangup_channel(channel: str) -> dict:
    mgr = await get_manager()
    return await mgr.send_action({'Action': 'Hangup', 'Channel': channel})


async def hold_channel(channel: str) -> dict:
    mgr = await get_manager()
    return await mgr.send_action({'Action': 'Hold', 'Channel': channel})


async def unhold_channel(channel: str) -> dict:
    mgr = await get_manager()
    return await mgr.send_action({'Action': 'Unhold', 'Channel': channel})


async def blind_transfer(channel: str, extension: str, context: str = 'dymphna-internal') -> dict:
    mgr = await get_manager()
    return await mgr.send_action({
        'Action': 'Redirect',
        'Channel': channel,
        'Exten': extension,
        'Context': context,
        'Priority': 1,
    })


async def attended_transfer(channel: str, extension: str) -> dict:
    mgr = await get_manager()
    return await mgr.send_action({
        'Action': 'Atxfer',
        'Channel': channel,
        'Exten': extension,
        'Context': 'dymphna-internal',
        'Priority': 1,
    })


async def park_call(channel: str, parker_channel: str) -> dict:
    mgr = await get_manager()
    return await mgr.send_action({
        'Action': 'Park',
        'Channel': channel,
        'TimeoutChannel': parker_channel,
    })


async def mute_channel(channel: str, direction: str = 'in') -> dict:
    mgr = await get_manager()
    return await mgr.send_action({
        'Action': 'MuteAudio',
        'Channel': channel,
        'Direction': direction,
        'State': 'on',
    })


async def unmute_channel(channel: str, direction: str = 'in') -> dict:
    mgr = await get_manager()
    return await mgr.send_action({
        'Action': 'MuteAudio',
        'Channel': channel,
        'Direction': direction,
        'State': 'off',
    })


async def pickup_extension(target_extension: str) -> dict:
    mgr = await get_manager()
    return await mgr.send_action({
        'Action': 'Pickup',
        'Channel': f'PJSIP/{target_extension}',
    })


async def get_active_channels() -> list[dict]:
    mgr = await get_manager()
    result = await mgr.send_action({'Action': 'CoreShowChannels'})
    channels = []
    for event in result:
        if event.get('Event') == 'CoreShowChannel':
            channels.append({
                'channel': event.get('Channel'),
                'caller_id': event.get('CallerIDNum'),
                'state': event.get('ChannelState'),
                'duration': event.get('Duration'),
            })
    return channels


# ─── Real-time call event listener ────────────────────────────────────────────
# Listens for Hangup events and writes Call CDR records to the DB.

def _parse_duration(duration_str: str | None) -> int:
    """Convert 'HH:MM:SS' duration string to seconds."""
    if not duration_str:
        return 0
    try:
        parts = duration_str.split(':')
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return int(duration_str)
    except Exception:
        return 0


async def _handle_hangup(event: dict, db_factory) -> None:
    """Persist a Call CDR when Asterisk fires a Hangup event."""
    from ..models import Call
    from sqlalchemy import select

    unique_id: str = event.get('Uniqueid', '')
    cause: str = event.get('Cause-txt', '')
    channel: str = event.get('Channel', '')
    caller_id_num: str = event.get('CallerIDNum', '')
    caller_id_name: str = event.get('CallerIDName', '')
    connected_line_num: str = event.get('ConnectedLineNum', '')
    duration_str: str = event.get('Duration', '0')
    context: str = event.get('Context', '')

    if not unique_id or context == 'dymphna-ivr':
        return

    direction = 'inbound' if context == 'dymphna-inbound' else 'outbound'
    remote_number = caller_id_num if direction == 'inbound' else connected_line_num
    disposition = 'answered' if cause in ('Normal Clearing', '16') else 'missed'

    async with db_factory() as db:
        # Skip duplicate (Asterisk fires Hangup for each leg)
        existing = await db.execute(select(Call).where(Call.asterisk_unique_id == unique_id))
        if existing.scalar_one_or_none():
            return

        now = datetime.now(timezone.utc)
        duration = _parse_duration(duration_str)

        call = Call(
            asterisk_unique_id=unique_id,
            direction=direction,
            remote_number=remote_number,
            contact_name=caller_id_name or None,
            started_at=now,
            answered_at=now if disposition == 'answered' else None,
            ended_at=now,
            duration=duration,
            disposition=disposition,
        )
        db.add(call)
        await db.commit()
        log.info("Logged call %s (%s, %s, %ds)", unique_id, direction, disposition, duration)


async def start_event_listener(db_factory) -> None:
    """Connect to AMI and listen for Hangup events to log CDRs."""
    global _listener_task

    async def _run():
        while True:
            try:
                mgr = await get_manager()
                log.info("AMI event listener connected")

                async for event in mgr:
                    if event.get('Event') == 'Hangup':
                        asyncio.create_task(_handle_hangup(dict(event), db_factory))

            except Exception as exc:
                log.warning("AMI event listener disconnected: %s — reconnecting in 5s", exc)
                await asyncio.sleep(5)

    _listener_task = asyncio.create_task(_run())


async def stop_event_listener() -> None:
    global _listener_task
    if _listener_task:
        _listener_task.cancel()
        _listener_task = None

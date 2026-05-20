"""Asterisk AMI client — raw asyncio TCP, no panoramisk dependency."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from ..config import settings

log = logging.getLogger(__name__)


# ─── Raw AMI client ───────────────────────────────────────────────────────────

class AmiClient:
    """Minimal async AMI client over raw TCP."""

    def __init__(self, host: str, port: int, username: str, secret: str):
        self.host = host
        self.port = port
        self.username = username
        self.secret = secret
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._read_task: asyncio.Task | None = None
        self.connected = False

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        # Read greeting line e.g. "Asterisk Call Manager/5.0.0"
        await self._reader.readline()
        self._read_task = asyncio.create_task(self._read_loop())
        # Login
        resp = await self.send_action({'Action': 'Login', 'Username': self.username, 'Secret': self.secret})
        if resp.get('Response') != 'Success':
            raise RuntimeError(f"AMI login failed: {resp.get('Message')}")
        self.connected = True
        log.info("AMI connected to %s:%s", self.host, self.port)

    async def disconnect(self) -> None:
        self.connected = False
        if self._read_task:
            self._read_task.cancel()
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass

    async def send_action(self, action: dict) -> dict:
        action_id = action.get('ActionID', str(uuid.uuid4()))
        action['ActionID'] = action_id

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[action_id] = fut

        msg = ''.join(f'{k}: {v}\r\n' for k, v in action.items()) + '\r\n'
        self._writer.write(msg.encode())
        await self._writer.drain()

        try:
            return await asyncio.wait_for(fut, timeout=10)
        except asyncio.TimeoutError:
            self._pending.pop(action_id, None)
            return {'Response': 'Timeout'}

    async def events(self) -> AsyncIterator[dict]:
        """Async generator yielding AMI events."""
        while True:
            event = await self._event_queue.get()
            yield event

    async def _read_loop(self) -> None:
        """Background task: read AMI messages and dispatch."""
        try:
            while True:
                msg = await self._read_message()
                if not msg:
                    break
                action_id = msg.get('ActionID')
                if 'Response' in msg and action_id and action_id in self._pending:
                    fut = self._pending.pop(action_id)
                    if not fut.done():
                        fut.set_result(msg)
                elif 'Event' in msg:
                    await self._event_queue.put(msg)
        except (asyncio.CancelledError, Exception) as exc:
            log.debug("AMI read loop ended: %s", exc)
            self.connected = False
            # Fail all pending futures
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("AMI disconnected"))
            self._pending.clear()

    async def _read_message(self) -> dict:
        """Read one AMI message (blank-line terminated key:value pairs)."""
        data: dict = {}
        while True:
            line = await self._reader.readline()
            if not line:
                return data
            line = line.decode('utf-8', errors='replace').rstrip('\r\n')
            if line == '':
                if data:
                    return data
            elif ': ' in line:
                k, _, v = line.partition(': ')
                data[k.strip()] = v.strip()
        return data


# ─── Singleton ────────────────────────────────────────────────────────────────

_client: AmiClient | None = None
_listener_task: asyncio.Task | None = None


async def get_client() -> AmiClient:
    global _client
    if _client is None or not _client.connected:
        _client = AmiClient(
            host=settings.asterisk_host,
            port=settings.asterisk_port,
            username=settings.asterisk_username,
            secret=settings.asterisk_secret,
        )
        await _client.connect()
    return _client


# ─── Call control ─────────────────────────────────────────────────────────────

async def originate_call(forwarding_number: str, remote_number: str) -> dict:
    """Click-to-call: Asterisk calls staff's cell first, then bridges to remote_number.

    Flow:
      1. Asterisk dials forwarding_number (staff's cell) via VoIP.ms trunk
      2. Staff answers — Asterisk dials remote_number and bridges both legs
      3. Client sees practice DID as caller ID, not the staff member's cell
    """
    c = await get_client()
    fwd = ''.join(ch for ch in forwarding_number if ch.isdigit())
    if fwd.startswith('1') and len(fwd) == 11:
        fwd = fwd[1:]   # strip leading 1 — dymphna-outbound expects 10 digits
    return await c.send_action({
        'Action': 'Originate',
        'Channel': f'Local/{fwd}@dymphna-outbound',
        'Exten': remote_number,
        'Context': 'dymphna-outbound',
        'Priority': '1',
        'CallerID': f'Dymphna <{settings.voipms_did}>',
        'Async': 'true',
    })


async def hangup_channel(channel: str) -> dict:
    c = await get_client()
    return await c.send_action({'Action': 'Hangup', 'Channel': channel})


async def hold_channel(channel: str) -> dict:
    c = await get_client()
    return await c.send_action({'Action': 'Hold', 'Channel': channel})


async def unhold_channel(channel: str) -> dict:
    c = await get_client()
    return await c.send_action({'Action': 'Unhold', 'Channel': channel})


async def blind_transfer(channel: str, extension: str, context: str = 'dymphna-internal') -> dict:
    c = await get_client()
    return await c.send_action({
        'Action': 'Redirect',
        'Channel': channel,
        'Exten': extension,
        'Context': context,
        'Priority': '1',
    })


async def attended_transfer(channel: str, extension: str) -> dict:
    c = await get_client()
    return await c.send_action({
        'Action': 'Atxfer',
        'Channel': channel,
        'Exten': extension,
        'Context': 'dymphna-internal',
        'Priority': '1',
    })


async def park_call(channel: str, parker_channel: str) -> dict:
    c = await get_client()
    return await c.send_action({
        'Action': 'Park',
        'Channel': channel,
        'TimeoutChannel': parker_channel,
    })


async def mute_channel(channel: str, direction: str = 'in') -> dict:
    c = await get_client()
    return await c.send_action({
        'Action': 'MuteAudio',
        'Channel': channel,
        'Direction': direction,
        'State': 'on',
    })


async def unmute_channel(channel: str, direction: str = 'in') -> dict:
    c = await get_client()
    return await c.send_action({
        'Action': 'MuteAudio',
        'Channel': channel,
        'Direction': direction,
        'State': 'off',
    })


async def pickup_extension(target_extension: str) -> dict:
    c = await get_client()
    return await c.send_action({
        'Action': 'Pickup',
        'Channel': f'PJSIP/{target_extension}',
    })


async def get_active_channels() -> list[dict]:
    c = await get_client()
    result = await c.send_action({'Action': 'CoreShowChannels'})
    channels = []
    if isinstance(result, list):
        for event in result:
            if event.get('Event') == 'CoreShowChannel':
                channels.append({
                    'channel': event.get('Channel'),
                    'caller_id': event.get('CallerIDNum'),
                    'state': event.get('ChannelState'),
                    'duration': event.get('Duration'),
                })
    return channels


async def reload_pjsip() -> dict:
    c = await get_client()
    return await c.send_action({'Action': 'ModuleReload', 'Module': 'res_pjsip.so'})


# ─── Real-time event listener (CDR logging) ───────────────────────────────────

def _parse_duration(duration_str: str | None) -> int:
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
    from ..models import Call
    from sqlalchemy import select

    unique_id = event.get('Uniqueid', '')
    cause = event.get('Cause-txt', '')
    caller_id_num = event.get('CallerIDNum', '')
    caller_id_name = event.get('CallerIDName', '')
    connected_line_num = event.get('ConnectedLineNum', '')
    duration_str = event.get('Duration', '0')
    context = event.get('Context', '')

    if not unique_id or context == 'dymphna-ivr':
        return

    direction = 'inbound' if context == 'dymphna-inbound' else 'outbound'
    remote_number = caller_id_num if direction == 'inbound' else connected_line_num
    disposition = 'answered' if cause in ('Normal Clearing', '16') else 'missed'

    async with db_factory() as db:
        existing = await db.execute(select(Call).where(Call.asterisk_unique_id == unique_id))
        if existing.scalar_one_or_none():
            return

        now = datetime.now(timezone.utc)
        call = Call(
            asterisk_unique_id=unique_id,
            direction=direction,
            remote_number=remote_number,
            contact_name=caller_id_name or None,
            started_at=now,
            answered_at=now if disposition == 'answered' else None,
            ended_at=now,
            duration=_parse_duration(duration_str),
            disposition=disposition,
        )
        db.add(call)
        await db.commit()
        log.info("Logged call %s (%s, %s)", unique_id, direction, disposition)


async def start_event_listener(db_factory) -> None:
    global _listener_task

    async def _run():
        while True:
            try:
                c = await get_client()
                log.info("AMI event listener started")
                async for event in c.events():
                    if event.get('Event') == 'Hangup':
                        asyncio.create_task(_handle_hangup(event, db_factory))
            except Exception as exc:
                log.warning("AMI listener error: %s — reconnecting in 5s", exc)
                global _client
                _client = None
                await asyncio.sleep(5)

    _listener_task = asyncio.create_task(_run())


async def stop_event_listener() -> None:
    global _listener_task
    if _listener_task:
        _listener_task.cancel()
        _listener_task = None

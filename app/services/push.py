"""Push notification dispatcher for VoIP wake-ups.

iOS: PushKit (VoIP push) via APNs HTTP/2 — wakes app even in background.
Android: FCM data message — wakes app via foreground service.
"""
import asyncio
import json
import logging
import time
import httpx
from jose import jwt
from ..config import settings

log = logging.getLogger(__name__)

_apns_token_cache: tuple[str, float] | None = None


def _generate_apns_jwt() -> str:
    global _apns_token_cache
    now = int(time.time())
    if _apns_token_cache and (now - _apns_token_cache[1]) < 3000:
        return _apns_token_cache[0]
    with open(settings.apns_key_path, 'r') as f:
        key = f.read()
    token = jwt.encode(
        {'iss': settings.apns_team_id, 'iat': now},
        key,
        algorithm='ES256',
        headers={'kid': settings.apns_key_id},
    )
    _apns_token_cache = (token, now)
    return token


async def send_voip_push_ios(device_token: str, payload: dict) -> bool:
    """Send VoIP push via APNs HTTP/2 to wake the app."""
    host = 'api.sandbox.push.apple.com' if settings.apns_use_sandbox else 'api.push.apple.com'
    url = f'https://{host}/3/device/{device_token}'
    headers = {
        'authorization': f'bearer {_generate_apns_jwt()}',
        'apns-topic': f'{settings.apns_bundle_id}.voip',
        'apns-push-type': 'voip',
        'apns-priority': '10',
    }
    try:
        async with httpx.AsyncClient(http2=True, timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                return True
            log.warning('APNs VoIP push failed %d: %s', resp.status_code, resp.text)
            return False
    except Exception as exc:
        log.error('APNs push error: %s', exc)
        return False


async def send_voip_push_android(device_token: str, payload: dict) -> bool:
    """Send FCM data message to wake app on Android."""
    url = 'https://fcm.googleapis.com/fcm/send'
    body = {
        'to': device_token,
        'priority': 'high',
        'data': {**payload, 'type': 'incoming_call'},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json=body,
                headers={'Authorization': f'key={settings.fcm_server_key}'},
            )
            data = resp.json()
            return data.get('success', 0) == 1
    except Exception as exc:
        log.error('FCM push error: %s', exc)
        return False


async def notify_incoming_call(
    tokens: list[dict],  # [{'platform': 'ios'|'android', 'token': str, 'is_voip_push': bool}]
    call_id: str,
    caller_name: str,
    caller_number: str,
) -> None:
    payload = {
        'call_id': call_id,
        'caller_name': caller_name,
        'caller_number': caller_number,
    }
    tasks = []
    for t in tokens:
        if t['platform'] == 'ios' and t['is_voip_push']:
            tasks.append(send_voip_push_ios(t['token'], payload))
        elif t['platform'] == 'android':
            tasks.append(send_voip_push_android(t['token'], payload))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

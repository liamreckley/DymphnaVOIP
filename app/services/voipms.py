"""VoIP.ms REST API client for SMS and DID management."""
import httpx
from ..config import settings


async def _call(method: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(settings.voipms_base_url, params={
            'api_username': settings.voipms_api_username,
            'api_password': settings.voipms_api_password,
            'method': method,
            **params,
        })
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') != 'success':
            raise RuntimeError(f"VoIP.ms error: {data.get('status')} — {data}")
        return data


async def send_sms(to_number: str, body: str) -> str:
    """Send SMS via VoIP.ms; returns the VoIP.ms message ID."""
    data = await _call('sendSMS', {
        'did': settings.voipms_did,
        'dst': to_number.lstrip('+'),
        'message': body[:1600],
    })
    return str(data.get('sms', ''))


async def get_sms(limit: int = 100, offset: int = 0) -> list[dict]:
    """Fetch inbound SMS from VoIP.ms."""
    data = await _call('getSMS', {
        'did': settings.voipms_did,
        'limit': limit,
        'offset': offset,
        'type': 1,   # 1 = received
    })
    return data.get('sms', [])


async def get_did_info() -> dict:
    """Get DID configuration from VoIP.ms."""
    data = await _call('getDIDsInfo', {'did': settings.voipms_did})
    return data


async def set_sip_trunk(username: str, password: str) -> dict:
    """Register a SIP sub-account (extension) with VoIP.ms trunk."""
    data = await _call('createSubAccount', {
        'username': username,
        'password': password,
        'protocol': 1,   # SIP
        'auth_type': 2,  # username/password
        'allowed_codecs': 'ulaw;g729;g722',
        'dtmf_mode': 'RFC2833',
    })
    return data

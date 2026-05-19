"""Validate JWT tokens issued by the EHR Next.js backend."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from .config import settings

bearer = HTTPBearer()


class CurrentUser:
    def __init__(self, user_id: str, voip_role: str, extension_id: str | None = None):
        self.user_id = user_id
        self.voip_role = voip_role
        self.extension_id = extension_id


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> CurrentUser:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid token')

    user_id: str = payload.get('sub', '')
    voip_role: str = payload.get('voipRole', 'none')
    extension_id: str | None = payload.get('extensionId')

    if not user_id or voip_role == 'none':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='VoIP access not permitted')

    return CurrentUser(user_id=user_id, voip_role=voip_role, extension_id=extension_id)


def require_roles(*roles: str):
    """Dependency factory: assert caller has one of the given voip roles."""
    async def _check(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current.voip_role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient VoIP role')
        return current
    return _check


# Shorthand dependencies
require_admin = require_roles('admin')
require_receptionist_or_admin = require_roles('admin', 'receptionist')

"""Authentication — JWT + Supabase client."""
from datetime import datetime, timedelta, timezone
from typing import Sequence

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from supabase import Client

from config import get_settings
from database import get_supabase
from jwt_secret_provider import get_active_jwt_secret

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, role: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    payload = {"sub": user_id, "role": role, "exp": expire, "iat": datetime.now(timezone.utc)}
    # SEC-ROT-2: sign with the DB-backed active secret (fail-closed), not the
    # static env var. Signature/claims/algorithm are unchanged; this function's
    # signature is preserved so all ~96 call sites stay intact.
    secret = get_active_jwt_secret(get_supabase())
    return jwt.encode(payload, secret, algorithm=settings.JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    client: Client = Depends(get_supabase),
) -> dict:
    """Decode JWT and return user dict from Supabase."""
    settings = get_settings()
    try:
        # SEC-ROT-2: verify with the DB-backed active secret. A token signed with
        # a secret other than the current active one (e.g. before a rotation)
        # fails signature verification → JWTError → 401, with no restart needed.
        secret = get_active_jwt_secret(client)
        payload = jwt.decode(credentials.credentials, secret, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido ou expirado")

    # GRD-5 (GRD5-1): supabase-py 2.28.x returns ``None`` (the whole response, NOT
    # ``_Result(data=None)``) from ``.maybe_single().execute()`` on ZERO rows. A valid
    # token whose ``sub`` points to a DELETED user then made ``res.data`` raise
    # AttributeError → 500 on EVERY protected endpoint, instead of the intended 401.
    # Guard both ``res is None`` and ``res.data is None``. Precedent: commit 5847a60.
    res = client.table("users").select("*").eq("id", user_id).maybe_single().execute()
    if res is None or res.data is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario nao encontrado")
    # P0: a blocked user must lose access IMMEDIATELY, including tokens minted
    # BEFORE the block. Rejecting here (not only at login) covers every protected
    # endpoint with a single gate. 403 (not 401): the token is valid, the account
    # is forbidden — the frontend should not treat this as "expired, re-login".
    if (res.data.get("status") or "").lower() == "blocked":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario bloqueado")
    return res.data


def require_role(*roles: str):
    allowed = {r.upper() for r in roles}

    def dependency(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role", "").upper() not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
        return current_user

    return dependency

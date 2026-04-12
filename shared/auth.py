"""
Shared authentication utilities for the Alfred platform.

All three services use the same SECRET_KEY so tokens issued by any service
are verifiable by any other service.

Password hashing uses PBKDF2-SHA256 (same as gateway).
OurCents keeps its own bcrypt hashing in its auth_service.py — that is fine,
the shared hash functions are provided here for gateway's use.
"""

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel


ALGORITHM = "HS256"
PBKDF2_ITERATIONS = 600_000


class TokenPayload(BaseModel):
    """JWT payload model shared across all services."""

    username: str
    # OurCents tokens include these extra fields; gateway tokens leave them None
    user_id: Optional[int] = None
    family_id: Optional[int] = None


def _get_secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "change-me")
    return key


def _get_expire_minutes() -> int:
    return int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))


# ---------------------------------------------------------------------------
# Password hashing (PBKDF2-SHA256)
# ---------------------------------------------------------------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        algorithm, iterations, salt, expected_hash = hashed_password.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        base64.b64decode(salt.encode("utf-8")),
        int(iterations),
    )
    actual_hash = base64.b64encode(derived_key).decode("utf-8")
    return hmac.compare_digest(actual_hash, expected_hash)


def get_password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    encoded_salt = base64.b64encode(salt).decode("utf-8")
    encoded_hash = base64.b64encode(derived_key).decode("utf-8")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${encoded_salt}${encoded_hash}"


# ---------------------------------------------------------------------------
# JWT token creation
# ---------------------------------------------------------------------------

def create_access_token(
    subject: str,
    extra_claims: Optional[dict] = None,
    secret_key: Optional[str] = None,
    expire_minutes: Optional[int] = None,
) -> str:
    """
    Create a signed JWT token.

    Args:
        subject: Primary subject (usually username).
        extra_claims: Additional claims merged into the payload
                      (e.g. {"user_id": 1, "family_id": 2} for OurCents).
        secret_key: Override SECRET_KEY env var (useful in tests).
        expire_minutes: Override ACCESS_TOKEN_EXPIRE_MINUTES env var.
    """
    key = secret_key or _get_secret_key()
    minutes = expire_minutes or _get_expire_minutes()
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload: dict = {"sub": subject, "exp": expire}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, key, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------

def make_verify_token(token_url: str):
    """
    Returns a FastAPI dependency that validates a bearer token and
    returns a TokenPayload.

    Usage:
        verify_token = make_verify_token("/api/auth/login")

        @router.get("/protected")
        def protected(payload: TokenPayload = Depends(verify_token)):
            ...
    """
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl=token_url)

    def _verify_token(token: str = Depends(oauth2_scheme)) -> TokenPayload:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        try:
            payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        except JWTError:
            raise credentials_exception

        username = payload.get("sub")
        if not isinstance(username, str):
            raise credentials_exception

        return TokenPayload(
            username=username,
            user_id=payload.get("user_id"),
            family_id=payload.get("family_id"),
        )

    return _verify_token

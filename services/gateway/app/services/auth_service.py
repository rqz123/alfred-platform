import logging
from fastapi import Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app.core.security import create_access_token, decode_access_token, verify_password
from app.db.session import get_session
from app.repositories.auth_repository import get_admin_user
from app.schemas.auth import LoginResponse, TokenPayload


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


_log = logging.getLogger("alfred.auth")

def build_login_response(response: Response, admin, password: str) -> LoginResponse:
    if not verify_password(password, admin.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(admin.username)
    response.set_cookie(
        key="alfred_session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return LoginResponse(access_token=token, username=admin.username)


def get_current_admin(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> TokenPayload:
    username = decode_access_token(token)
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    admin = get_admin_user(session, username)
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin not found")

    return TokenPayload(username=admin.username)
"""
Alfred account system REST API.

Auth: Admin endpoints require X-Alfred-Phone header matching an alfred_users
admin record.  The resolve endpoint is open (internal network only).
Bootstrap is open and idempotent-guarded (rejects after first use).
"""

import logging

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlmodel import Session

logger = logging.getLogger("alfred.account_routes")

import app.repositories.account_repository as repo
from app.db.session import get_session
from app.models.account import AlfredUser
from app.schemas.account import (
    BootstrapRequest,
    BootstrapResponse,
    FamilyCreate,
    FamilyDetailOut,
    FamilyOut,
    FamilyUpdate,
    ResolveResponse,
    UserCreate,
    UserOut,
    UserUpdate,
)

alfred_router = APIRouter(prefix="/api/alfred", tags=["alfred"])


# ── Auth dependency ────────────────────────────────────────────────────────────

def require_admin(
    x_alfred_phone: str = Header(),
    session: Session = Depends(get_session),
) -> AlfredUser:
    user = repo.get_user_by_phone(session, x_alfred_phone)
    if not user or user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PERMISSION_DENIED", "message": "Admin access required"},
        )
    return user


# ── Bootstrap ──────────────────────────────────────────────────────────────────

@alfred_router.post("/bootstrap", response_model=BootstrapResponse)
def bootstrap(body: BootstrapRequest, session: Session = Depends(get_session)):
    if repo.has_any_user(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BOOTSTRAP_ALREADY_DONE",
                "message": "System already initialized",
            },
        )
    try:
        user, family = repo.bootstrap(
            session, body.family_name, body.admin_phone, body.admin_display_name
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "PHONE_INVALID", "message": str(exc)},
        )
    return BootstrapResponse(
        success=True,
        user_id=user.id,
        family_id=family.id,
        message=f"Bootstrap complete. Admin created: {user.phone}",
    )


# ── Resolve (internal) ─────────────────────────────────────────────────────────

@alfred_router.get("/resolve", response_model=ResolveResponse)
def resolve(phone: str, session: Session = Depends(get_session)):
    user = repo.get_user_by_phone(session, phone)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "USER_NOT_FOUND",
                "message": f"No user found with phone {phone}",
            },
        )
    return ResolveResponse(
        user_id=user.id,
        phone=user.phone,
        display_name=user.display_name,
        role=user.role,
        family_id=user.family_id,
    )


# ── Users ──────────────────────────────────────────────────────────────────────

@alfred_router.get("/users", response_model=list[UserOut])
def list_users(
    admin: AlfredUser = Depends(require_admin),
    session: Session = Depends(get_session),
):
    return repo.list_users(session)


@alfred_router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    admin: AlfredUser = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if repo.get_user_by_phone(session, body.phone):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "USER_ALREADY_EXISTS", "message": "Phone already registered"},
        )
    if body.family_id and not repo.get_family_by_id(session, body.family_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "FAMILY_NOT_FOUND", "message": f"Family {body.family_id} not found"},
        )
    try:
        return repo.create_user(session, body.phone, body.display_name, body.family_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "PHONE_INVALID", "message": str(exc)},
        )


@alfred_router.get("/users/{phone}", response_model=UserOut)
def get_user(
    phone: str,
    admin: AlfredUser = Depends(require_admin),
    session: Session = Depends(get_session),
):
    user = repo.get_user_by_phone(session, phone)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": f"No user found with phone {phone}"},
        )
    return user


@alfred_router.patch("/users/{phone}", response_model=UserOut)
def update_user(
    phone: str,
    body: UserUpdate,
    admin: AlfredUser = Depends(require_admin),
    session: Session = Depends(get_session),
):
    user = repo.get_user_by_phone(session, phone)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": f"No user found with phone {phone}"},
        )

    updates = body.model_dump(exclude_none=True)

    if "role" in updates:
        new_role = updates["role"]
        if new_role not in ("user", "admin"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "PHONE_INVALID", "message": "Role must be 'user' or 'admin'"},
            )
        if user.role == "admin" and new_role == "user":
            if admin.id == user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"code": "SELF_DEMOTE_FORBIDDEN", "message": "Cannot demote yourself"},
                )
            if repo.count_admins(session) <= 1:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": "LAST_ADMIN_PROTECTED",
                        "message": "Cannot demote the last admin",
                    },
                )

    if "family_id" in updates and updates["family_id"] is not None:
        if not repo.get_family_by_id(session, updates["family_id"]):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "FAMILY_NOT_FOUND",
                    "message": f"Family {updates['family_id']} not found",
                },
            )

    return repo.update_user(session, user, **updates)


@alfred_router.delete("/users/{phone}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    phone: str,
    admin: AlfredUser = Depends(require_admin),
    session: Session = Depends(get_session),
):
    user = repo.get_user_by_phone(session, phone)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": f"No user found with phone {phone}"},
        )
    if admin.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SELF_DELETE_FORBIDDEN", "message": "Cannot delete yourself"},
        )
    if user.role == "admin" and repo.count_admins(session) <= 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "LAST_ADMIN_PROTECTED", "message": "Cannot delete the last admin"},
        )
    repo.delete_user(session, user)


# ── Families ───────────────────────────────────────────────────────────────────

@alfred_router.get("/families", response_model=list[FamilyOut])
def list_families(
    admin: AlfredUser = Depends(require_admin),
    session: Session = Depends(get_session),
):
    return repo.list_families(session)


@alfred_router.post("/families", response_model=FamilyOut, status_code=status.HTTP_201_CREATED)
def create_family(
    body: FamilyCreate,
    admin: AlfredUser = Depends(require_admin),
    session: Session = Depends(get_session),
):
    return repo.create_family(session, body.name, created_by=admin.id)


@alfred_router.get("/families/{family_id}", response_model=FamilyDetailOut)
def get_family(
    family_id: str,
    admin: AlfredUser = Depends(require_admin),
    session: Session = Depends(get_session),
):
    family = repo.get_family_by_id(session, family_id)
    if not family:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "FAMILY_NOT_FOUND", "message": f"Family {family_id} not found"},
        )
    members = repo.get_family_members(session, family_id)
    return FamilyDetailOut(
        id=family.id,
        name=family.name,
        created_by=family.created_by,
        created_at=family.created_at,
        updated_at=family.updated_at,
        members=[UserOut.model_validate(m) for m in members],
    )


@alfred_router.patch("/families/{family_id}", response_model=FamilyOut)
def update_family(
    family_id: str,
    body: FamilyUpdate,
    admin: AlfredUser = Depends(require_admin),
    session: Session = Depends(get_session),
):
    family = repo.get_family_by_id(session, family_id)
    if not family:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "FAMILY_NOT_FOUND", "message": f"Family {family_id} not found"},
        )
    return repo.update_family(session, family, name=body.name)


@alfred_router.delete("/families/{family_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_family(
    family_id: str,
    admin: AlfredUser = Depends(require_admin),
    session: Session = Depends(get_session),
):
    family = repo.get_family_by_id(session, family_id)
    if not family:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "FAMILY_NOT_FOUND", "message": f"Family {family_id} not found"},
        )
    repo.delete_family(session, family)


# ── Danger zone ────────────────────────────────────────────────────────────────

@alfred_router.delete("/admin/clear-all-data", status_code=status.HTTP_204_NO_CONTENT)
def clear_all_data(
    admin: AlfredUser = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Response:
    """Clear all chat conversations, receipts, and notes. Preserves all user/family/admin records."""
    from app.repositories.chat_repository import delete_all_conversations
    from app.services.service_registry import ServiceRegistry

    # 1. Clear gateway chat
    delete_all_conversations(session)

    # 2. Clear OurCents receipts and income entries
    # 3. Clear nudge notes
    registry = ServiceRegistry()
    _clear_service(registry, intent="add_expense", path="/alfred/admin/clear")
    _clear_service(registry, intent="add_reminder", path="/alfred/admin/clear")

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@alfred_router.delete("/admin/clear-logs", status_code=status.HTTP_204_NO_CONTENT)
def clear_logs(
    admin: AlfredUser = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Response:
    """Clear all chat conversations and messages only. Preserves receipts, notes, and user records."""
    from app.repositories.chat_repository import delete_all_conversations
    delete_all_conversations(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _clear_service(registry, intent: str, path: str) -> None:
    svc = registry.find_service(intent)
    if not svc:
        return
    url = svc["url"].rstrip("/") + path
    try:
        r = httpx.delete(url, headers={"X-Alfred-Api-Key": svc["api_key"]}, timeout=10.0)
        if r.status_code not in (200, 204):
            logger.warning("clear_all_data: %s returned %d", url, r.status_code)
    except Exception as exc:
        logger.warning("clear_all_data: failed to reach %s: %s", url, exc)

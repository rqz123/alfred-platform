"""
OurCents REST API routes.

Wraps the existing service layer (services/, domain/, storage/) in FastAPI endpoints.
Business logic lives entirely in those layers — this file only handles
HTTP request/response plumbing and auth.
"""

import os
import sys
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

# Ensure shared package is importable (monorepo root on path)
_monorepo_root = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
if _monorepo_root not in sys.path:
    sys.path.insert(0, _monorepo_root)

from shared.auth import TokenPayload, create_access_token, make_verify_token

# Import service classes — sys.path is patched in main.py so bare imports work
from services.auth_service import AuthService
from services.dashboard_service import DashboardService
from services.receipt_ingestion_service import ReceiptIngestionService
from services.classification_rules_service import ClassificationRulesService
from models.schema import ExpenseCategory, DeductionType

router = APIRouter()
verify_token = make_verify_token("/api/ourcents/auth/login")


# ─────────────────────────────────────────────────────
# Dependency helpers
# ─────────────────────────────────────────────────────

def get_db(request: Request):
    return request.app.state.db


def get_file_storage(request: Request):
    return request.app.state.file_storage


# ─────────────────────────────────────────────────────
# Auth — public endpoints
# ─────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    family_id: int
    username: str
    family_name: str
    is_admin: bool


class RegisterRequest(BaseModel):
    family_name: str
    admin_username: str
    admin_email: str
    admin_password: str


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, db=Depends(get_db)):
    auth_svc = AuthService(db)
    user_info = auth_svc.authenticate(body.username, body.password)
    if user_info is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = create_access_token(
        subject=user_info["username"],
        extra_claims={
            "user_id": user_info["user_id"],
            "family_id": user_info["family_id"],
        },
    )
    return LoginResponse(
        access_token=token,
        user_id=user_info["user_id"],
        family_id=user_info["family_id"],
        username=user_info["username"],
        family_name=user_info["family_name"],
        is_admin=user_info["is_admin"],
    )


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db=Depends(get_db)):
    auth_svc = AuthService(db)
    try:
        family_id, user_id = auth_svc.create_family_with_admin(
            family_name=body.family_name,
            admin_username=body.admin_username,
            admin_email=body.admin_email,
            admin_password=body.admin_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return {"family_id": family_id, "user_id": user_id}


# ─────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────

@router.get("/dashboard")
def get_dashboard(
    period: str = "month",
    payload: TokenPayload = Depends(verify_token),
    db=Depends(get_db),
):
    family_id = payload.family_id
    if family_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No family context in token")
    svc = DashboardService(db)
    try:
        return svc.get_period_dashboard(family_id, period)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/dashboard/summary")
def get_dashboard_summary(
    payload: TokenPayload = Depends(verify_token),
    db=Depends(get_db),
):
    family_id = payload.family_id
    if family_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No family context in token")
    svc = DashboardService(db)
    return svc.get_family_dashboard(family_id)


# ─────────────────────────────────────────────────────
# Receipts
# ─────────────────────────────────────────────────────

@router.get("/receipts")
def list_receipts(
    status_filter: Optional[str] = None,
    category: Optional[str] = None,
    days_back: Optional[int] = None,
    payload: TokenPayload = Depends(verify_token),
    db=Depends(get_db),
):
    family_id = payload.family_id
    if family_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No family context in token")

    query = """
        SELECT r.id, r.merchant_name, r.purchase_date, r.total_amount,
               r.currency, r.category, r.status, r.confidence_score,
               u.username, uf.storage_path
        FROM receipts r
        JOIN users u ON u.id = r.user_id
        JOIN upload_files uf ON uf.id = r.upload_file_id
        WHERE r.family_id = ?
    """
    params: list = [family_id]

    if days_back:
        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days_back)).date().isoformat()
        query += " AND r.purchase_date >= ?"
        params.append(cutoff)

    if category:
        query += " AND r.category = ?"
        params.append(category)

    if status_filter == "pending":
        query += " AND r.status IN (?, ?)"
        params.extend(["pending_confirmation", "duplicate_suspected"])
    elif status_filter:
        query += " AND r.status = ?"
        params.append(status_filter)

    query += " ORDER BY r.created_at DESC"

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = [dict(row) for row in cursor.fetchall()]
    return rows


@router.get("/receipts/{receipt_id}")
def get_receipt(
    receipt_id: int,
    payload: TokenPayload = Depends(verify_token),
    db=Depends(get_db),
    file_storage=Depends(get_file_storage),
):
    family_id = payload.family_id
    if family_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No family context in token")
    svc = ReceiptIngestionService(db, file_storage)
    details = svc.get_receipt_details(family_id, receipt_id)
    if details is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    return details


@router.post("/receipts/upload")
async def upload_receipt(
    file: UploadFile = File(...),
    payload: TokenPayload = Depends(verify_token),
    db=Depends(get_db),
    file_storage=Depends(get_file_storage),
):
    family_id = payload.family_id
    user_id = payload.user_id
    if family_id is None or user_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No family/user context in token")

    content = await file.read()
    mime_type = file.content_type or "image/jpeg"

    svc = ReceiptIngestionService(db, file_storage)
    upload_status, receipt_id, extra = await svc.process_receipt_upload(
        family_id=family_id,
        user_id=user_id,
        file_content=content,
        filename=file.filename or "upload",
        mime_type=mime_type,
    )

    return {
        "status": upload_status,
        "receipt_id": receipt_id,
        "info": extra,
    }


class ConfirmReceiptRequest(BaseModel):
    merchant_name: str
    purchase_date: date
    total_amount: float
    category: str
    is_deductible: bool = False
    deduction_type: str = "none"
    deduction_evidence: str = ""
    items: Optional[List[dict]] = None
    notes: str = ""


@router.post("/receipts/{receipt_id}/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_receipt(
    receipt_id: int,
    body: ConfirmReceiptRequest,
    payload: TokenPayload = Depends(verify_token),
    db=Depends(get_db),
    file_storage=Depends(get_file_storage),
):
    family_id = payload.family_id
    if family_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No family context in token")

    try:
        category_enum = ExpenseCategory(body.category)
        deduction_type_enum = DeductionType(body.deduction_type)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    svc = ReceiptIngestionService(db, file_storage)
    try:
        svc.confirm_receipt(
            family_id=family_id,
            receipt_id=receipt_id,
            merchant_name=body.merchant_name,
            purchase_date_value=body.purchase_date,
            total_amount=body.total_amount,
            category=category_enum,
            is_deductible=body.is_deductible,
            deduction_type=deduction_type_enum,
            deduction_evidence=body.deduction_evidence,
            items=body.items,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ─────────────────────────────────────────────────────
# Settings — classification rules
# ─────────────────────────────────────────────────────

@router.get("/settings/rules")
def get_rules(
    payload: TokenPayload = Depends(verify_token),
    db=Depends(get_db),
):
    family_id = payload.family_id
    if family_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No family context in token")
    svc = ClassificationRulesService(db)
    return {
        "merchant_aliases": svc.list_merchant_aliases(family_id),
        "category_rules": svc.list_category_rules(family_id),
    }

"""
OurCents REST API routes.

Wraps the existing service layer (services/, domain/, storage/) in FastAPI endpoints.
Business logic lives entirely in those layers — this file only handles
HTTP request/response plumbing and auth.
"""

import logging
import os
import sys
import uuid as _uuid

import httpx

logger = logging.getLogger("ourcents.routes")
from datetime import date, datetime, timedelta
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
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

_DEFAULT_CURRENCY = os.environ.get("OURCENTS_DEFAULT_CURRENCY", "USD")
_CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$", "CNY": "¥", "EUR": "€", "GBP": "£", "HKD": "HK$", "JPY": "¥",
}


def _fmt_amount(amount: float, currency: str) -> str:
    sym = _CURRENCY_SYMBOLS.get(currency, currency)
    return f"{sym}{amount:.2f}"


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
        query += " AND r.status IN (?, ?, ?)"
        params.extend(["pending", "pending_confirmation", "duplicate_suspected"])
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


@router.get("/receipts/{receipt_id}/image")
def get_receipt_image(
    receipt_id: int,
    payload: TokenPayload = Depends(verify_token),
    db=Depends(get_db),
    file_storage=Depends(get_file_storage),
):
    from fastapi.responses import Response as FastResponse
    family_id = payload.family_id
    if family_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No family context in token")
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT uf.storage_path, uf.mime_type
               FROM receipts r JOIN upload_files uf ON uf.id = r.upload_file_id
               WHERE r.id = ? AND r.family_id = ?""",
            (receipt_id, family_id),
        ).fetchone()
    if not row or not row["storage_path"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    data = file_storage.get_file(row["storage_path"])
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image file missing")
    mime = row["mime_type"] or "image/jpeg"
    return FastResponse(content=data, media_type=mime)


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


# ─────────────────────────────────────────────────────
# Phone binding — link WhatsApp phone to OurCents family
# ─────────────────────────────────────────────────────

class PhoneBindRequest(BaseModel):
    phone: str


@router.get("/phone/bindings")
def list_phone_bindings(
    payload: TokenPayload = Depends(verify_token),
    db=Depends(get_db),
):
    """Return all phone numbers bound to the current family."""
    family_id = payload.family_id
    if family_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No family context in token")
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT pm.id, pm.phone, pm.created_at, u.username
            FROM phone_mappings pm
            JOIN users u ON u.id = pm.user_id
            WHERE pm.family_id = ?
            ORDER BY pm.created_at DESC
            """,
            (family_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/phone/bind", status_code=status.HTTP_204_NO_CONTENT)
def bind_phone(
    body: PhoneBindRequest,
    payload: TokenPayload = Depends(verify_token),
    db=Depends(get_db),
):
    """Bind the authenticated user's WhatsApp phone number to their family."""
    user_id = payload.user_id
    family_id = payload.family_id
    if user_id is None or family_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No user/family context in token")
    normalized = ''.join(c for c in body.phone if c.isdigit())
    if not normalized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid phone number")
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO phone_mappings (phone, user_id, family_id)
            VALUES (?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET user_id=excluded.user_id, family_id=excluded.family_id
            """,
            (normalized, user_id, family_id),
        )

    # Send a welcome message via Gateway (best-effort, don't fail the bind if push fails)
    _send_welcome(normalized)


def _send_welcome(phone: str) -> None:
    gateway_url = os.environ.get("GATEWAY_URL", "http://localhost:8000")
    api_key = os.environ.get("OURCENTS_API_KEY", "")
    welcome = (
        "👋 Welcome to Alfred! Your WhatsApp number is now linked.\n\n"
        "You can send me messages like:\n"
        "• \"Spent $12 on lunch\"\n"
        "• \"Income $500 freelance\"\n"
        "• \"What's my balance?\"\n"
        "• \"Remind me to pay rent on the 1st\""
    )
    try:
        with httpx.Client(timeout=8.0) as client:
            client.post(
                f"{gateway_url}/api/internal/push",
                json={"user_phone": phone, "message": welcome, "source_service": "ourcents"},
                headers={"X-Alfred-API-Key": api_key},
            )
    except Exception as exc:
        logger.warning("Welcome push failed for %s: %s", phone, exc)


@router.delete("/phone/bindings/{phone}", status_code=status.HTTP_204_NO_CONTENT)
def unbind_phone(
    phone: str,
    payload: TokenPayload = Depends(verify_token),
    db=Depends(get_db),
):
    """Remove a phone binding (only allowed within the same family)."""
    family_id = payload.family_id
    if family_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No family context in token")
    normalized = ''.join(c for c in phone if c.isdigit())
    with db.get_connection() as conn:
        result = conn.execute(
            "DELETE FROM phone_mappings WHERE phone=? AND family_id=?",
            (normalized, family_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Binding not found")


# ─────────────────────────────────────────────────────
# ASI (Alfred Service Interface) endpoints
# ─────────────────────────────────────────────────────

ALFRED_API_KEY = os.environ.get("OURCENTS_API_KEY", "") or os.environ.get("ALFRED_API_KEY", "")


def _verify_alfred_key(x_alfred_api_key: str | None = Header(default=None)) -> None:
    if not ALFRED_API_KEY or x_alfred_api_key != ALFRED_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Alfred API key")


class AlfredExecuteRequest(BaseModel):
    request_id: str
    user_id: str
    whatsapp_id: str
    intent: str
    entities: dict[str, Any] = {}
    session: dict = {}
    timestamp: str = ""


class AlfredExecuteResponse(BaseModel):
    request_id: str
    status: str
    message: str = ""
    data: Optional[Any] = None
    error_code: Optional[str] = None
    quick_replies: list[str] = []


@router.get("/health")
def health():
    return {"service": "ourcents", "status": "ok", "version": "1.0.0"}


@router.get("/alfred/capabilities", dependencies=[Depends(_verify_alfred_key)])
def capabilities():
    return {
        "service": "ourcents",
        "display_name": "OurCents Family Finance",
        "capabilities": [
            {
                "intent": "add_expense",
                "description": "Record an expense",
                "required_entities": [{"name": "amount", "type": "float", "prompt": "How much did you spend?"}],
                "optional_entities": [
                    {"name": "category", "type": "string", "prompt": "Category?"},
                    {"name": "date", "type": "date", "prompt": "Date (default: today)"},
                ],
            },
            {"intent": "add_income", "description": "Record income"},
            {"intent": "get_balance", "description": "Query this month's balance"},
            {"intent": "monthly_report", "description": "Monthly spending report"},
            {
                "intent": "set_budget",
                "description": "Set a monthly spending budget for a category",
                "required_entities": [{"name": "amount", "type": "float", "prompt": "What is the budget amount?"}],
                "optional_entities": [{"name": "category", "type": "string", "prompt": "Which category? (food/transport/shopping/medical/overall)"}],
            },
            {
                "intent": "process_receipt_image",
                "description": "Process a WhatsApp receipt image through AI OCR and store the expense",
                "required_entities": [
                    {"name": "image_data", "type": "string", "prompt": "Base64-encoded image bytes"},
                    {"name": "mime_type", "type": "string", "prompt": "Image MIME type"},
                ],
                "optional_entities": [
                    {"name": "filename", "type": "string", "prompt": "Original filename"},
                    {"name": "caption", "type": "string", "prompt": "User caption accompanying the image"},
                ],
            },
        ],
    }


@router.post("/alfred/execute", response_model=AlfredExecuteResponse, dependencies=[Depends(_verify_alfred_key)])
async def alfred_execute(req: AlfredExecuteRequest, db=Depends(get_db), file_storage=Depends(get_file_storage)):
    # Look up family by WhatsApp phone number
    normalized = ''.join(c for c in req.whatsapp_id if c.isdigit())
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT user_id, family_id FROM phone_mappings WHERE phone=?", (normalized,)
        ).fetchone()

    if not row:
        return AlfredExecuteResponse(
            request_id=req.request_id,
            status="error",
            error_code="UNAUTHORIZED",
            message="Your phone number is not linked to an OurCents account. Please log in to the web app and bind your number in Settings.",
        )

    family_id = row["family_id"]
    dash_svc = DashboardService(db)

    if req.intent == "get_balance":
        try:
            data = dash_svc.get_period_dashboard(family_id, "month")
            expense_total = data['total_amount']
            # Also query income for this month
            today = date.today()
            month_start = today.replace(day=1).isoformat()
            with db.get_connection() as conn:
                income_row = conn.execute(
                    "SELECT COALESCE(SUM(amount), 0) AS total FROM income_entries "
                    "WHERE family_id=? AND income_date >= ?",
                    (family_id, month_start),
                ).fetchone()
            income_total = income_row["total"] if income_row else 0.0
            net = income_total - expense_total
            sign = "+" if net >= 0 else ""
            msg = (
                f"This month\n"
                f"  Income:  ¥{income_total:.2f}\n"
                f"  Expense: ¥{expense_total:.2f} ({data['receipt_count']} txns)\n"
                f"  Net:     {sign}¥{net:.2f}"
            )
            top = list(data.get("category_breakdown", {}).items())[:3]
            if top:
                msg += "\nTop categories: " + ", ".join(f"{k} ¥{v:.0f}" for k, v in top)
            # Show budget progress per category if any budgets are set
            with db.get_connection() as conn:
                budget_rows = conn.execute(
                    "SELECT category, amount FROM budgets WHERE family_id=? AND period='monthly'",
                    (family_id,),
                ).fetchall()
            if budget_rows:
                cat_breakdown = data.get("category_breakdown", {})
                budget_lines = []
                for brow in budget_rows:
                    cat = brow["category"]
                    budget_amt = brow["amount"]
                    spent = cat_breakdown.get(cat, 0.0)
                    pct = int(spent / budget_amt * 100) if budget_amt else 0
                    budget_lines.append(f"  {cat}: ¥{spent:.0f}/¥{budget_amt:.0f} ({pct}%)")
                msg += "\nBudget:\n" + "\n".join(budget_lines)
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success", message=msg,
            )
        except Exception:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="SERVICE_ERROR", message="Query failed, please try again.",
            )

    if req.intent == "monthly_report":
        try:
            data = dash_svc.get_family_dashboard(family_id)
            today = date.today()
            month_start = today.replace(day=1).isoformat()
            with db.get_connection() as conn:
                inc_row = conn.execute(
                    "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS cnt "
                    "FROM income_entries WHERE family_id=? AND income_date >= ?",
                    (family_id, month_start),
                ).fetchone()
            income_total = inc_row["total"] if inc_row else 0.0
            income_cnt = inc_row["cnt"] if inc_row else 0
            net = income_total - data.total_expenses_month
            sign = "+" if net >= 0 else ""
            msg = (
                f"Monthly report\n"
                f"  Income:     ¥{income_total:.2f} ({income_cnt} txns)\n"
                f"  Expense:    ¥{data.total_expenses_month:.2f} / this week ¥{data.total_expenses_week:.2f}\n"
                f"  Net:        {sign}¥{net:.2f}\n"
                f"  Deductible: ¥{data.deductible_amount_month:.2f}"
            )
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success", message=msg,
            )
        except Exception:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="SERVICE_ERROR", message="Report generation failed, please try again.",
            )

    if req.intent == "add_expense":
        amount = req.entities.get("amount")
        if not amount:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="Please tell me the amount, e.g.: spent 50 on lunch",
            )

        user_id = row["user_id"]
        _category_map = {
            "food": "food",
            "transportation": "transportation", "transport": "transportation",
            "healthcare": "healthcare", "medical": "healthcare",
            "shopping": "shopping",
            "entertainment": "entertainment",
            "utilities": "utilities",
            "other": "other",
        }
        category_val = _category_map.get(req.entities.get("category", ""), "other")
        _date_kw = req.entities.get("date", "today")
        today = date.today()
        if _date_kw == "yesterday":
            purchase_date = (today - timedelta(days=1)).isoformat()
        elif _date_kw == "tomorrow":
            purchase_date = (today + timedelta(days=1)).isoformat()
        else:
            purchase_date = today.isoformat()

        try:
            with db.get_connection() as conn:
                file_hash = f"wa_{_uuid.uuid4().hex}"
                conn.execute(
                    "INSERT INTO upload_files "
                    "    (family_id, user_id, filename, content_hash, file_size, mime_type, storage_path) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (family_id, user_id, "whatsapp_quick_entry", file_hash,
                     0, "text/plain", "virtual://whatsapp"),
                )
                upload_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                currency = req.entities.get("currency") or _DEFAULT_CURRENCY
                conn.execute(
                    "INSERT INTO receipts "
                    "    (family_id, user_id, upload_file_id, merchant_name, merchant_normalized, "
                    "     purchase_date, total_amount, currency, category, status, confidence_score) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (family_id, user_id, upload_id, f"WA +{normalized}", "whatsapp_expense",
                     purchase_date, float(amount), currency, category_val, "confirmed", 1.0),
                )
                receipt_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute(
                    "INSERT INTO receipt_deductions "
                    "    (receipt_id, is_deductible, deduction_type, evidence_text, evidence_level, amount) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (receipt_id, False, "none", "", "none", 0.0),
                )
                conn.execute(
                    "INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, "create", "receipt", receipt_id,
                     f"WA +{normalized}: {amount:.2f}"),
                )
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message=f"Expense recorded: {_fmt_amount(float(amount), currency)} ({purchase_date}, {category_val})",
            )
        except Exception:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="SERVICE_ERROR", message="Failed to save, please try again.",
            )

    if req.intent == "add_income":
        amount = req.entities.get("amount")
        if not amount:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="Please tell me the income amount, e.g.: received salary 5000",
            )

        user_id = row["user_id"]
        _income_category_map = {
            "food": "other", "transport": "other",
            "medical": "other", "shopping": "other",
        }
        # Simple income category: salary if no specific category extracted
        income_category = req.entities.get("category", "salary")
        if income_category not in ("salary", "bonus", "other"):
            income_category = "other"
        _date_kw = req.entities.get("date", "today")
        today = date.today()
        if _date_kw == "yesterday":
            income_date = (today - timedelta(days=1)).isoformat()
        elif _date_kw == "tomorrow":
            income_date = (today + timedelta(days=1)).isoformat()
        else:
            income_date = today.isoformat()

        try:
            with db.get_connection() as conn:
                currency = req.entities.get("currency") or _DEFAULT_CURRENCY
                conn.execute(
                    "INSERT INTO income_entries "
                    "    (family_id, user_id, amount, currency, category, source, income_date, notes) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (family_id, user_id, float(amount), currency, income_category,
                     "whatsapp", income_date, "WhatsApp quick entry"),
                )
                entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute(
                    "INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, "create", "income_entry", entry_id,
                     f"WhatsApp quick income: {_fmt_amount(float(amount), currency)}"),
                )
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message=f"Income recorded: {_fmt_amount(float(amount), currency)} ({income_date}, {income_category})",
            )
        except Exception:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="SERVICE_ERROR", message="Failed to save, please try again.",
            )

    if req.intent == "set_budget":
        amount = req.entities.get("amount")
        if not amount:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="Please tell me the budget amount, e.g.: set food budget 1000",
            )
        user_id = row["user_id"]
        category = req.entities.get("category", "overall")
        try:
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO budgets (family_id, user_id, category, period, amount, currency, updated_at) "
                    "VALUES (?, ?, ?, 'monthly', ?, 'CNY', datetime('now')) "
                    "ON CONFLICT(family_id, category, period) "
                    "DO UPDATE SET amount=excluded.amount, updated_at=excluded.updated_at",
                    (family_id, user_id, category, float(amount)),
                )
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message=f"Budget set: {category} ¥{float(amount):.2f}/month",
            )
        except Exception:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="SERVICE_ERROR", message="Failed to save budget, please try again.",
            )

    if req.intent == "process_receipt_image":
        import base64
        image_b64 = req.entities.get("image_data")
        mime_type = req.entities.get("mime_type", "image/jpeg")
        filename = req.entities.get("filename", "receipt.jpg")
        if not image_b64:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA", message="No image data provided.",
            )
        try:
            image_bytes = base64.b64decode(image_b64)
        except Exception:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INVALID_VALUE", message="Image data could not be decoded.",
            )

        user_id = row["user_id"]
        svc = ReceiptIngestionService(db, file_storage)
        try:
            upload_status, receipt_id, extra = await svc.process_receipt_upload(
                family_id=family_id,
                user_id=user_id,
                file_content=image_bytes,
                filename=filename,
                mime_type=mime_type,
            )
        except Exception as exc:
            logger.error("Receipt image processing failed: %s", exc)
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="SERVICE_ERROR",
                message="Receipt processing failed. Please try uploading via the web app.",
            )

        if upload_status == "duplicate":
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message="This receipt looks like a duplicate — it may already be recorded.",
            )

        # Build a human-readable confirmation from the extracted data
        extraction = (extra or {}).get("extraction") or {}
        merchant = extraction.get("merchant_name") or extraction.get("merchant_normalized") or "Unknown merchant"
        amount = extraction.get("total_amount")
        category = extraction.get("category", "")
        if amount:
            msg_text = f"Receipt recorded: {merchant} ¥{float(amount):.2f}"
            if category:
                msg_text += f" ({category})"
        else:
            msg_text = f"Receipt received from {merchant}. Please review in the web app to confirm details."

        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=msg_text,
        )

    return AlfredExecuteResponse(
        request_id=req.request_id, status="error",
        error_code="NOT_FOUND", message="Unknown intent",
    )

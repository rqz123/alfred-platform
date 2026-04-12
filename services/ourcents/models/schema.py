"""
Data models and database schema for OurCents.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


# Enums
class UserRole(str, Enum):
    """User role within a family."""
    ADMIN = "admin"
    MEMBER = "member"


class ExpenseCategory(str, Enum):
    """Expense category classifications."""
    FOOD = "food"
    RESTAURANT = "restaurant"
    TOOLS = "tools"
    MAINTENANCE = "maintenance"
    UTILITIES = "utilities"
    HEALTHCARE = "healthcare"
    TRANSPORTATION = "transportation"
    ENTERTAINMENT = "entertainment"
    CLOTHING = "clothing"
    EDUCATION = "education"
    OTHER = "other"


class DeductionType(str, Enum):
    """Tax deduction types."""
    HOME_OFFICE = "home_office"
    MEDICAL = "medical"
    BUSINESS = "business"
    CHARITABLE = "charitable"
    EDUCATION = "education"
    NONE = "none"


class ReceiptStatus(str, Enum):
    """Receipt processing status."""
    PENDING = "pending"
    PROCESSING = "processing"
    CONFIRMED = "confirmed"
    DUPLICATE_SUSPECTED = "duplicate_suspected"
    DUPLICATE_CONFIRMED = "duplicate_confirmed"
    FAILED = "failed"


class EvidenceLevel(str, Enum):
    """Confidence level for deduction eligibility."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


# Pydantic Models for Data Transfer

class FamilyCreate(BaseModel):
    """Family creation request."""
    name: str = Field(..., min_length=1, max_length=100)
    admin_username: str = Field(..., min_length=3, max_length=50)
    admin_email: str = Field(..., pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
    admin_password: str = Field(..., min_length=8)


class UserCreate(BaseModel):
    """User creation request."""
    username: str = Field(..., min_length=3, max_length=50)
    email: str
    password: str = Field(..., min_length=8)
    family_id: int
    role: UserRole = UserRole.MEMBER


class UserLogin(BaseModel):
    """User login credentials."""
    username: str
    password: str


class ReceiptItemData(BaseModel):
    """Individual item in a receipt."""
    description: str
    quantity: Optional[float] = 1.0
    unit_price: Optional[float] = None
    total_price: float
    category: ExpenseCategory = ExpenseCategory.OTHER


class ReceiptExtractionResult(BaseModel):
    """AI extraction result from receipt image."""
    merchant_name: str
    purchase_date: datetime
    total_amount: float
    currency: str = "USD"
    items: List[ReceiptItemData] = []
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    category_suggestion: ExpenseCategory = ExpenseCategory.OTHER
    tax_deductible: bool = False
    deduction_type: DeductionType = DeductionType.NONE
    deduction_evidence: str = ""
    evidence_level: EvidenceLevel = EvidenceLevel.NONE


class ReceiptData(BaseModel):
    """Complete receipt data."""
    id: Optional[int] = None
    family_id: int
    user_id: int
    upload_file_id: int
    merchant_name: str
    merchant_normalized: str
    purchase_date: datetime
    total_amount: float
    currency: str = "USD"
    category: ExpenseCategory
    status: ReceiptStatus = ReceiptStatus.CONFIRMED
    confidence_score: float
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UploadFileData(BaseModel):
    """Upload file metadata."""
    id: Optional[int] = None
    family_id: int
    user_id: int
    filename: str
    content_hash: str
    file_size: int
    mime_type: str
    storage_path: str
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)


class DeductionData(BaseModel):
    """Tax deduction information."""
    id: Optional[int] = None
    receipt_id: int
    is_deductible: bool
    deduction_type: DeductionType
    evidence_text: str
    evidence_level: EvidenceLevel
    amount: float
    notes: Optional[str] = None


class DashboardStats(BaseModel):
    """Dashboard statistics."""
    total_expenses_week: float
    total_expenses_month: float
    category_breakdown: dict
    deductible_amount_month: float
    receipt_count_week: int
    receipt_count_month: int
    recent_receipts: List[dict]


# Database Schema Documentation
"""
SQLite Schema:

CREATE TABLE families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE family_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'member')),
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (family_id) REFERENCES families(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(family_id, user_id)
);

CREATE TABLE upload_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (family_id) REFERENCES families(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(content_hash, family_id)
);

CREATE TABLE receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    upload_file_id INTEGER NOT NULL,
    merchant_name TEXT NOT NULL,
    merchant_normalized TEXT NOT NULL,
    purchase_date DATE NOT NULL,
    total_amount REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    category TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'processing', 'confirmed', 
                                          'duplicate_suspected', 'duplicate_confirmed', 'failed')),
    confidence_score REAL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (family_id) REFERENCES families(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (upload_file_id) REFERENCES upload_files(id)
);

CREATE INDEX idx_receipts_lookup ON receipts(family_id, merchant_normalized, purchase_date, total_amount);
CREATE INDEX idx_receipts_date ON receipts(family_id, purchase_date);

CREATE TABLE receipt_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantity REAL DEFAULT 1.0,
    unit_price REAL,
    total_price REAL NOT NULL,
    category TEXT NOT NULL,
    FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE
);

CREATE TABLE receipt_deductions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id INTEGER NOT NULL,
    is_deductible BOOLEAN DEFAULT 0,
    deduction_type TEXT NOT NULL,
    evidence_text TEXT,
    evidence_level TEXT NOT NULL CHECK(evidence_level IN ('high', 'medium', 'low', 'none')),
    amount REAL NOT NULL,
    notes TEXT,
    FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE
);

CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""

"""
Database connection and initialization.
"""

import logging
import sqlite3
import os
from contextlib import contextmanager


logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager."""
    
    def __init__(self, db_path: str):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._memory_connection = None
        self._ensure_database_exists()
        self._initialize_schema()
    
    def _ensure_database_exists(self):
        """Ensure database directory and file exist."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
    
    @contextmanager
    def get_connection(self):
        """
        Context manager for database connections.
        
        Yields:
            sqlite3.Connection: Database connection
        """
        if self.db_path == ':memory:':
            if self._memory_connection is None:
                self._memory_connection = sqlite3.connect(self.db_path, check_same_thread=False)
                self._memory_connection.row_factory = sqlite3.Row
            conn = self._memory_connection
            should_close = False
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            should_close = True
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if should_close:
                conn.close()
    
    def _initialize_schema(self):
        """Initialize database schema if not exists."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Families table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS families (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Family members table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS family_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'member')),
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (family_id) REFERENCES families(id),
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(family_id, user_id)
                )
            """)
            
            # Upload files table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS upload_files (
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
                )
            """)
            
            # Receipts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS receipts (
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
                )
            """)
            
            # Create indices for receipts
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_receipts_lookup 
                ON receipts(family_id, merchant_normalized, purchase_date, total_amount)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_receipts_date 
                ON receipts(family_id, purchase_date)
            """)
            
            # Receipt items table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS receipt_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_id INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    quantity REAL DEFAULT 1.0,
                    unit_price REAL,
                    total_price REAL NOT NULL,
                    category TEXT NOT NULL,
                    FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE
                )
            """)
            
            # Receipt deductions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS receipt_deductions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_id INTEGER NOT NULL,
                    is_deductible BOOLEAN DEFAULT 0,
                    deduction_type TEXT NOT NULL,
                    evidence_text TEXT,
                    evidence_level TEXT NOT NULL CHECK(evidence_level IN ('high', 'medium', 'low', 'none')),
                    amount REAL NOT NULL,
                    notes TEXT,
                    FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE
                )
            """)
            
            # Audit logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id INTEGER,
                    details TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS merchant_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_id INTEGER NOT NULL,
                    alias_normalized TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    canonical_normalized TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 100,
                    created_by INTEGER,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (family_id) REFERENCES families(id),
                    FOREIGN KEY (created_by) REFERENCES users(id),
                    UNIQUE(family_id, alias_normalized)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS merchant_category_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_id INTEGER NOT NULL,
                    merchant_normalized TEXT NOT NULL,
                    merchant_display_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 100,
                    source TEXT NOT NULL CHECK(source IN ('admin', 'feedback')),
                    notes TEXT,
                    created_by INTEGER,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (family_id) REFERENCES families(id),
                    FOREIGN KEY (created_by) REFERENCES users(id),
                    UNIQUE(family_id, merchant_normalized, source)
                )
            """)

            # Phone mappings table — links WhatsApp phone numbers to OurCents families
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS phone_mappings (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone     TEXT UNIQUE NOT NULL,
                    user_id   INTEGER NOT NULL,
                    family_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (family_id) REFERENCES families(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS income_entries (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_id   INTEGER NOT NULL,
                    user_id     INTEGER NOT NULL,
                    amount      REAL NOT NULL,
                    currency    TEXT DEFAULT 'CNY',
                    category    TEXT NOT NULL DEFAULT 'other',
                    source      TEXT,
                    income_date DATE NOT NULL,
                    notes       TEXT,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (family_id) REFERENCES families(id),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_income_entries_date
                ON income_entries(family_id, income_date)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_merchant_aliases_lookup
                ON merchant_aliases(family_id, alias_normalized, priority)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_merchant_category_rules_lookup
                ON merchant_category_rules(family_id, merchant_normalized, priority)
            """)
            
            conn.commit()

    def reset_application_data(self) -> None:
        """Drop all application tables and recreate an empty schema."""
        logger.warning("Resetting all application data in database path=%s", self.db_path)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = OFF")

            tables = [
                'audit_logs',
                'merchant_category_rules',
                'merchant_aliases',
                'receipt_deductions',
                'receipt_items',
                'receipts',
                'upload_files',
                'family_members',
                'users',
                'families',
            ]

            for table_name in tables:
                cursor.execute(f"DROP TABLE IF EXISTS {table_name}")

            cursor.execute("DELETE FROM sqlite_sequence")
            cursor.execute("PRAGMA foreign_keys = ON")
            conn.commit()

        self._initialize_schema()
        logger.warning("Database reset complete path=%s", self.db_path)


def get_database() -> Database:
    """
    Get database instance.
    
    Returns:
        Database: Initialized database instance
    """
    db_path = os.getenv('DATABASE_PATH', './data/ourcents.db')
    return Database(db_path)

"""
Authentication service for user login and session management.
"""

import bcrypt
from typing import Optional, Tuple, Dict
from storage.database import Database
from models.schema import UserRole


class AuthService:
    """Handles user authentication and authorization."""
    
    def __init__(self, database: Database):
        """
        Initialize auth service.
        
        Args:
            database: Database instance
        """
        self.db = database
    
    def create_family_with_admin(
        self,
        family_name: str,
        admin_username: str,
        admin_email: str,
        admin_password: str
    ) -> Tuple[int, int]:
        """
        Create a new family with admin user.
        
        Args:
            family_name: Name of the family
            admin_username: Admin username
            admin_email: Admin email
            admin_password: Admin password (plain text)
            
        Returns:
            Tuple of (family_id, user_id)
            
        Raises:
            ValueError: If username already exists
        """
        # Hash password
        password_hash = self._hash_password(admin_password)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if username exists
            cursor.execute("SELECT id FROM users WHERE username = ?", (admin_username,))
            if cursor.fetchone():
                raise ValueError("Username already exists")
            
            # Create family
            cursor.execute(
                "INSERT INTO families (name) VALUES (?)",
                (family_name,)
            )
            family_id = cursor.lastrowid
            
            # Create admin user
            cursor.execute("""
                INSERT INTO users (username, email, password_hash)
                VALUES (?, ?, ?)
            """, (admin_username, admin_email, password_hash))
            user_id = cursor.lastrowid
            
            # Link user to family as admin
            cursor.execute("""
                INSERT INTO family_members (family_id, user_id, role)
                VALUES (?, ?, ?)
            """, (family_id, user_id, UserRole.ADMIN.value))
            
            # Log action
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, 'create', 'family', family_id, f"Created family '{family_name}'"))
            
            conn.commit()
            return family_id, user_id
    
    def create_family_member(
        self,
        family_id: int,
        username: str,
        email: str,
        password: str,
        creator_user_id: int
    ) -> int:
        """
        Create a new family member.
        
        Args:
            family_id: Family to add member to
            username: Member username
            email: Member email
            password: Member password (plain text)
            creator_user_id: User ID of admin creating the member
            
        Returns:
            New user ID
            
        Raises:
            ValueError: If username exists or creator is not admin
        """
        # Verify creator is admin
        if not self.is_family_admin(creator_user_id, family_id):
            raise ValueError("Only admins can add family members")
        
        password_hash = self._hash_password(password)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check username
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                raise ValueError("Username already exists")
            
            # Create user
            cursor.execute("""
                INSERT INTO users (username, email, password_hash)
                VALUES (?, ?, ?)
            """, (username, email, password_hash))
            user_id = cursor.lastrowid
            
            # Link to family
            cursor.execute("""
                INSERT INTO family_members (family_id, user_id, role)
                VALUES (?, ?, ?)
            """, (family_id, user_id, UserRole.MEMBER.value))
            
            # Log action
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details)
                VALUES (?, ?, ?, ?, ?)
            """, (creator_user_id, 'create', 'user', user_id, 
                  f"Added member '{username}' to family"))
            
            conn.commit()
            return user_id
    
    def authenticate(self, username: str, password: str) -> Optional[Dict]:
        """
        Authenticate user credentials.
        
        Args:
            username: Username
            password: Password (plain text)
            
        Returns:
            User info dict if authenticated, None otherwise
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get user
            cursor.execute("""
                SELECT id, username, email, password_hash
                FROM users
                WHERE username = ?
            """, (username,))
            
            user = cursor.fetchone()
            if not user:
                return None
            
            # Verify password
            if not self._verify_password(password, user['password_hash']):
                return None
            
            # Get family memberships
            cursor.execute("""
                SELECT fm.family_id, fm.role, f.name as family_name
                FROM family_members fm
                JOIN families f ON f.id = fm.family_id
                WHERE fm.user_id = ?
            """, (user['id'],))
            
            memberships = [dict(row) for row in cursor.fetchall()]
            
            if not memberships:
                return None  # User not in any family
            
            # Use first family (in future, could support multiple)
            primary_membership = memberships[0]
            
            return {
                'user_id': user['id'],
                'username': user['username'],
                'email': user['email'],
                'family_id': primary_membership['family_id'],
                'family_name': primary_membership['family_name'],
                'role': primary_membership['role'],
                'is_admin': primary_membership['role'] == UserRole.ADMIN.value
            }
    
    def is_family_admin(self, user_id: int, family_id: int) -> bool:
        """
        Check if user is admin of specified family.
        
        Args:
            user_id: User identifier
            family_id: Family identifier
            
        Returns:
            True if user is admin
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT role FROM family_members
                WHERE user_id = ? AND family_id = ?
            """, (user_id, family_id))
            
            result = cursor.fetchone()
            return result and result['role'] == UserRole.ADMIN.value
    
    def get_family_members(self, family_id: int) -> list:
        """
        Get all members of a family.
        
        Args:
            family_id: Family identifier
            
        Returns:
            List of member info dictionaries
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.id, u.username, u.email, fm.role, fm.joined_at
                FROM users u
                JOIN family_members fm ON fm.user_id = u.id
                WHERE fm.family_id = ?
                ORDER BY fm.joined_at ASC
            """, (family_id,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def _hash_password(self, password: str) -> str:
        """Hash password using bcrypt."""
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against hash."""
        return bcrypt.checkpw(
            password.encode('utf-8'),
            password_hash.encode('utf-8')
        )

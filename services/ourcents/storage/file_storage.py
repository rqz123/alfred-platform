"""
File storage management for receipt images.
"""

import os
import hashlib
import logging
import shutil
from pathlib import Path
from typing import Tuple, Optional
from datetime import datetime


logger = logging.getLogger(__name__)


class FileStorage:
    """Manages local file storage for receipt images."""
    
    def __init__(self, base_path: str):
        """
        Initialize file storage.
        
        Args:
            base_path: Base directory for file storage
        """
        self.base_path = Path(base_path)
        self.temp_path = Path(os.getenv('TEMP_UPLOAD_PATH', './data/temp'))
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Ensure storage directories exist."""
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.temp_path.mkdir(parents=True, exist_ok=True)
    
    def compute_file_hash(self, file_content: bytes) -> str:
        """
        Compute SHA-256 hash of file content.
        
        Args:
            file_content: Binary file content
            
        Returns:
            Hexadecimal hash string
        """
        return hashlib.sha256(file_content).hexdigest()
    
    def get_storage_path(
        self, 
        family_id: int, 
        upload_id: int,
        file_hash: str,
        extension: str
    ) -> str:
        """
        Generate organized storage path for receipt image.
        
        Structure: family_{family_id}/{year}/{month}/upload_{upload_id}_{hash_prefix}.{ext}
        
        Args:
            family_id: Family identifier
            upload_id: Upload file record ID
            file_hash: File content hash
            extension: File extension (without dot)
            
        Returns:
            Relative storage path
        """
        now = datetime.utcnow()
        year = now.strftime('%Y')
        month = now.strftime('%m')
        hash_prefix = file_hash[:12]
        
        filename = f"upload_{upload_id}_{hash_prefix}.{extension}"
        relative_path = os.path.join(
            f"family_{family_id}",
            year,
            month,
            filename
        )
        
        return relative_path
    
    def save_file(self, file_content: bytes, relative_path: str) -> str:
        """
        Save file to storage.
        
        Args:
            file_content: Binary file content
            relative_path: Relative path within storage
            
        Returns:
            Absolute path to saved file
        """
        absolute_path = self.base_path / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(absolute_path, 'wb') as f:
            f.write(file_content)
        
        return str(absolute_path)
    
    def save_temp_file(self, file_content: bytes, filename: str) -> Tuple[str, str]:
        """
        Save file to temporary storage.
        
        Args:
            file_content: Binary file content
            filename: Original filename
            
        Returns:
            Tuple of (temp_path, content_hash)
        """
        content_hash = self.compute_file_hash(file_content)
        temp_filename = f"{content_hash}_{filename}"
        temp_path = self.temp_path / temp_filename
        
        with open(temp_path, 'wb') as f:
            f.write(file_content)
        
        return str(temp_path), content_hash
    
    def move_from_temp(self, temp_path: str, target_relative_path: str) -> str:
        """
        Move file from temporary to permanent storage.
        
        Args:
            temp_path: Path to temporary file
            target_relative_path: Target relative path
            
        Returns:
            Absolute path to moved file
        """
        target_absolute = self.base_path / target_relative_path
        target_absolute.parent.mkdir(parents=True, exist_ok=True)
        
        os.rename(temp_path, target_absolute)
        return str(target_absolute)
    
    def get_file(self, relative_path: str) -> Optional[bytes]:
        """
        Retrieve file content.
        
        Args:
            relative_path: Relative path within storage
            
        Returns:
            File content as bytes, or None if not found
        """
        absolute_path = self.base_path / relative_path
        
        if not absolute_path.exists():
            return None
        
        with open(absolute_path, 'rb') as f:
            return f.read()
    
    def delete_file(self, relative_path: str) -> bool:
        """
        Delete file from storage.
        
        Args:
            relative_path: Relative path within storage
            
        Returns:
            True if deleted, False if not found
        """
        absolute_path = self.base_path / relative_path
        
        if not absolute_path.exists():
            return False
        
        absolute_path.unlink()
        
        # Clean up empty directories
        try:
            absolute_path.parent.rmdir()
        except OSError:
            pass  # Directory not empty
        
        return True
    
    def get_absolute_path(self, relative_path: str) -> str:
        """
        Convert relative to absolute path.
        
        Args:
            relative_path: Relative path within storage
            
        Returns:
            Absolute path
        """
        return str(self.base_path / relative_path)

    def clear_all_files(self) -> None:
        """Remove all stored receipt and temporary upload files."""
        logger.warning("Clearing file storage base_path=%s temp_path=%s", self.base_path, self.temp_path)

        for path in [self.base_path, self.temp_path]:
            if path.exists():
                for child in path.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()

        self._ensure_directories()
        logger.warning("File storage cleared base_path=%s temp_path=%s", self.base_path, self.temp_path)


def get_file_storage() -> FileStorage:
    """
    Get file storage instance.
    
    Returns:
        FileStorage: Initialized file storage instance
    """
    storage_path = os.getenv('RECEIPTS_STORAGE_PATH', './data/receipts')
    return FileStorage(storage_path)

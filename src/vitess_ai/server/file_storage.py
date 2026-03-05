"""
File Storage Service for Vitess AI Agent

Handles file uploads, storage, and retrieval for simulation input/output files.
Files are stored persistently and associated with thread_id for reuse across conversations.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from vitess_ai.core.log import get_logger
from vitess_ai.core.config import global_config
from vitess_ai.modules import get_upload_module_names

logger = get_logger(__name__)


class FileStorageService:
    """Service for managing uploaded files associated with threads."""

    # Safe fallback if catalog loading fails at runtime.
    FALLBACK_MODULE_TYPES = [
        "readin",
        "guide",
        "instrument",
        "monitor1d",
        "monitor2d",
        "writeout",
    ]

    def __init__(self):
        """Initialize file storage service."""
        self.root_path = Path(global_config.VITESS_PROJECT_PATH)
        self.max_file_size = global_config.MAX_FILE_SIZE
        self.allowed_extensions = [ext.strip().lower() for ext in global_config.ALLOWED_FILE_EXTENSIONS]
        
        # Ensure root directory exists
        self.root_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"File storage initialized at: {self.root_path}")
    
    def _get_upload_path(self, thread_id: str, module_type: str) -> Path:
        """Get upload path for a specific module type in a thread."""
        return self.root_path / thread_id / "uploads" / module_type

    def _get_allowed_module_types(self) -> list[str]:
        """
        Return allowed upload module types from the central module catalog.

        Falls back to static defaults if catalog loading fails.
        """
        try:
            return get_upload_module_names(include_auxiliary=True)
        except Exception as e:
            logger.warning(
                f"Failed to load upload module names from catalog, using fallback types: {e}"
            )
            return list(self.FALLBACK_MODULE_TYPES)
    
    def _get_module_path(self, thread_id: str, module_type: str) -> Path:
        """Get storage path for a specific module type in a thread (legacy method for compatibility)."""
        # Use new upload path structure
        return self._get_upload_path(thread_id, module_type)

    def _ensure_unique_filename(self, module_path: Path, filename: str) -> str:
        """Ensure uploaded filename is safe and collision-free without UUID prefixing."""
        safe_name = Path(filename).name
        if not safe_name:
            safe_name = "upload.dat"
        candidate = safe_name
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix
        index = 1
        while (module_path / candidate).exists():
            candidate = f"{stem}_{index}{suffix}"
            index += 1
        return candidate

    def _build_upload_metadata(
        self,
        file_path: Path,
        thread_id: str,
        module_type: str,
    ) -> Dict[str, Any]:
        """Build standardized metadata for one uploaded module file."""
        filename = file_path.name
        return {
            "file_id": filename,
            "filename": filename,
            "stored_filename": filename,
            "file_path": str(file_path),
            "server_path": str(file_path),
            "relative_path": str(file_path.relative_to(self.root_path)),
            "thread_id": thread_id,
            "module_type": module_type,
            "file_size": file_path.stat().st_size,
            "exists": True,
        }

    def _list_module_files(self, thread_id: str, module_type: str) -> List[Dict[str, Any]]:
        """List files for one upload module."""
        files: List[Dict[str, Any]] = []
        module_path = self._get_upload_path(thread_id, module_type)
        if not module_path.exists():
            return files

        for file_path in sorted(module_path.iterdir()):
            if not file_path.is_file():
                continue
            files.append(self._build_upload_metadata(file_path, thread_id, module_type))
        return files
    
    def _validate_file(self, filename: str, file_size: int) -> tuple[bool, Optional[str]]:
        """
        Validate file before upload.
        
        Args:
            filename: Name of the file
            file_size: Size of the file in bytes
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check file size
        if file_size > self.max_file_size:
            return False, f"File size {file_size} exceeds maximum {self.max_file_size} bytes"
        
        # Check file extension
        file_ext = Path(filename).suffix.lower()
        if file_ext not in self.allowed_extensions:
            return False, f"File extension {file_ext} not allowed. Allowed: {', '.join(self.allowed_extensions)}"
        
        return True, None
    
    def upload_file(
        self,
        file_content: bytes,
        filename: str,
        thread_id: str,
        module_type: str
    ) -> Dict[str, Any]:
        """
        Upload a file to storage.
        
        Args:
            file_content: File content as bytes
            filename: Original filename
            thread_id: Thread ID to associate file with
            module_type: Type of module (readin, guide, instrument, writeout)
            
        Returns:
            Dictionary with file metadata
        """
        # Validate module type
        allowed_module_types = self._get_allowed_module_types()
        if module_type not in allowed_module_types:
            raise ValueError(
                f"Invalid module_type: {module_type}. Must be one of {allowed_module_types}"
            )
        
        # Validate file
        is_valid, error_msg = self._validate_file(filename, len(file_content))
        if not is_valid:
            raise ValueError(error_msg)
        
        logger.info(f"Uploading file: filename={filename}, thread_id={thread_id}, module_type={module_type}, size={len(file_content)} bytes")
        
        # Get storage path for this thread and module (using upload path)
        module_path = self._get_upload_path(thread_id, module_type)
        module_path.mkdir(parents=True, exist_ok=True)
        
        # Use clean filename and add numeric suffix on collision
        stored_filename = self._ensure_unique_filename(module_path, filename)
        file_path = module_path / stored_filename
        
        # Write file
        try:
            file_path.write_bytes(file_content)
            logger.info(f"File uploaded successfully: {filename} (size: {len(file_content)} bytes)")
        except Exception as e:
            logger.error(f"Error writing file {file_path}: {e}", exc_info=True)
            raise
        
        # Return file metadata
        return {
            "file_id": stored_filename,
            "filename": stored_filename,
            "stored_filename": stored_filename,
            "file_path": str(file_path),
            "server_path": str(file_path),  # Full server path for MCP tools
            "relative_path": str(file_path.relative_to(self.root_path)),
            "thread_id": thread_id,
            "module_type": module_type,
            "file_size": len(file_content),
            "uploaded_at": datetime.now().isoformat()
        }
    
    def get_file_info(self, file_id: str, thread_id: str, module_type: str) -> Optional[Dict[str, Any]]:
        """
        Get file information by file ID.
        
        Args:
            file_id: File ID
            thread_id: Thread ID
            module_type: Module type
            
        Returns:
            File metadata dictionary or None if not found
        """
        module_path = self._get_upload_path(thread_id, module_type)
        
        # Search for file with this ID
        if not module_path.exists():
            logger.debug(f"Module path does not exist: {module_path}")
            return None

        exact_path = module_path / Path(file_id).name
        if exact_path.is_file():
            return self._build_upload_metadata(exact_path, thread_id, module_type)

        return None
    
    def list_files(self, thread_id: str, module_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List files for a thread, optionally filtered by module type.
        
        Args:
            thread_id: Thread ID
            module_type: Optional module type filter
            
        Returns:
            List of file metadata dictionaries
        """
        files = []
        
        if module_type:
            files.extend(self._list_module_files(thread_id, module_type))
        else:
            for mod_type in self._get_allowed_module_types():
                files.extend(self._list_module_files(thread_id, mod_type))
        
        logger.debug(f"Listed {len(files)} files for thread_id={thread_id}, module_type={module_type}")
        return files
    
    def delete_file(self, file_id: str, thread_id: str, module_type: str) -> bool:
        """
        Delete a file by file ID.
        
        Args:
            file_id: File ID
            thread_id: Thread ID
            module_type: Module type
            
        Returns:
            True if deleted, False if not found
        """
        module_path = self._get_upload_path(thread_id, module_type)
        
        # Find and delete file
        if not module_path.exists():
            logger.debug(f"Module path does not exist: {module_path}")
            return False

        exact_path = module_path / Path(file_id).name
        if exact_path.is_file():
            try:
                exact_path.unlink()
                logger.info(f"File deleted: {exact_path}")
                return True
            except Exception as e:
                logger.error(f"Error deleting file {exact_path}: {e}")
                return False

        return False
    
    def delete_thread_files(self, thread_id: str) -> int:
        """
        Delete all files for a thread.
        
        Args:
            thread_id: Thread ID
            
        Returns:
            Number of files deleted
        """
        thread_path = self.root_path / thread_id
        deleted_count = 0
        
        if thread_path.exists():
            for file_path in thread_path.rglob("*"):
                if file_path.is_file():
                    try:
                        file_path.unlink()
                        deleted_count += 1
                    except Exception as e:
                        logger.error(f"Error deleting file {file_path}: {e}")
            
            # Remove empty directories
            try:
                thread_path.rmdir()
            except OSError:
                # Directory not empty or doesn't exist
                pass
        
        logger.info(f"Deleted {deleted_count} files for thread {thread_id}")
        return deleted_count
    
    def get_file_paths_for_module(self, thread_id: str, module_type: str) -> List[str]:
        """
        Get list of file paths for a module in a thread.
        Used by MCP tools to access uploaded files.
        
        Args:
            thread_id: Thread ID
            module_type: Module type
            
        Returns:
            List of full server file paths
        """
        files = self.list_files(thread_id, module_type)
        file_paths = [f["server_path"] for f in files]
        
        # Verify paths exist
        existing_paths = []
        for path_str in file_paths:
            path = Path(path_str)
            if path.exists():
                existing_paths.append(path_str)
            else:
                logger.warning(f"File path does not exist: {path_str} (thread_id={thread_id}, module_type={module_type})")
        
        if existing_paths:
            logger.debug(f"Found {len(existing_paths)} existing files for thread_id={thread_id}, module_type={module_type}")
        else:
            logger.debug(f"No existing files found for thread_id={thread_id}, module_type={module_type}")
        
        return existing_paths
    
    def _get_output_path(self, thread_id: str) -> Path:
        """Get output path for a thread."""
        return self.root_path / thread_id / "outputs"
    
    def reinitialize(self) -> None:
        """
        Reinitialize file storage service with updated paths from global_config.
        Called when Vitess configuration is updated at runtime.
        """
        old_path = self.root_path
        self.root_path = Path(global_config.VITESS_PROJECT_PATH)
        self.root_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"File storage reinitialized: {old_path} -> {self.root_path}")
    
    def save_output_file(self, file_content: bytes, filename: str, thread_id: str) -> Dict[str, Any]:
        """
        Save an output file for a thread.
        
        Args:
            file_content: File content as bytes
            filename: Original filename
            thread_id: Thread ID
            
        Returns:
            Dictionary with file metadata
        """
        logger.debug(f"Saving output file: filename={filename}, thread_id={thread_id}, size={len(file_content)} bytes")
        
        output_path = self._get_output_path(thread_id)
        output_path.mkdir(parents=True, exist_ok=True)
        
        file_path = output_path / filename
        
        try:
            file_path.write_bytes(file_content)
            logger.info(f"Output file saved successfully: {filename} (size: {len(file_content)} bytes)")
        except Exception as e:
            logger.error(f"Error writing output file {file_path}: {e}", exc_info=True)
            raise
        
        return {
            "filename": filename,
            "file_path": str(file_path),
            "server_path": str(file_path),
            "relative_path": str(file_path.relative_to(self.root_path)),
            "thread_id": thread_id,
            "file_size": len(file_content),
            "saved_at": datetime.now().isoformat()
        }
    
    def list_output_files(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        List output files for a thread.
        
        Args:
            thread_id: Thread ID
            
        Returns:
            List of output file metadata dictionaries
        """
        logger.debug(f"Listing output files for thread_id={thread_id}")
        
        output_path = self._get_output_path(thread_id)
        files = []
        
        if output_path.exists():
            for file_path in output_path.iterdir():
                if file_path.is_file():
                    files.append({
                        "filename": file_path.name,
                        "file_path": str(file_path),
                        "server_path": str(file_path),
                        "relative_path": str(file_path.relative_to(self.root_path)),
                        "thread_id": thread_id,
                        "file_size": file_path.stat().st_size,
                        "exists": True
                    })
        
        return files
    
    def get_output_file_path(self, thread_id: str, filename: str) -> Optional[Path]:
        """
        Get path to an output file.
        
        Args:
            thread_id: Thread ID
            filename: Filename
            
        Returns:
            Path to file or None if not found
        """
        output_path = self._get_output_path(thread_id)
        file_path = output_path / filename
        
        if file_path.exists() and file_path.is_file():
            return file_path
        
        return None
    
    def delete_output_file(self, thread_id: str, filename: str) -> bool:
        """
        Delete an output file.
        
        Args:
            thread_id: Thread ID
            filename: Filename
            
        Returns:
            True if deleted, False if not found
        """
        output_path = self._get_output_path(thread_id)
        file_path = output_path / filename
        
        if file_path.exists() and file_path.is_file():
            try:
                file_path.unlink()
                logger.info(f"Output file deleted: {file_path}")
                return True
            except Exception as e:
                logger.error(f"Error deleting output file {file_path}: {e}")
                return False
        
        return False
    
    def delete_thread_outputs(self, thread_id: str) -> int:
        """
        Delete all output files and run folders for a thread.

        Args:
            thread_id: Thread ID

        Returns:
            Number of output files deleted
        """
        output_path = self._get_output_path(thread_id)
        deleted_count = 0

        if output_path.exists():
            for item in output_path.iterdir():
                try:
                    if item.is_file():
                        item.unlink()
                        deleted_count += 1
                    elif item.is_dir():
                        # Run folder: delete all files inside, then the folder
                        for f in item.iterdir():
                            if f.is_file():
                                try:
                                    f.unlink()
                                    deleted_count += 1
                                except OSError as e:
                                    logger.error(f"Error deleting output file {f}: {e}")
                        try:
                            item.rmdir()
                        except OSError:
                            pass
                except OSError as e:
                    logger.error(f"Error deleting output item {item}: {e}")

            try:
                output_path.rmdir()
            except OSError:
                pass

        logger.info(f"Deleted {deleted_count} output files for thread {thread_id}")
        return deleted_count


# Global instance
_file_storage_service: Optional[FileStorageService] = None


def get_file_storage_service() -> FileStorageService:
    """Get or create the global file storage service instance."""
    global _file_storage_service
    if _file_storage_service is None:
        _file_storage_service = FileStorageService()
    return _file_storage_service

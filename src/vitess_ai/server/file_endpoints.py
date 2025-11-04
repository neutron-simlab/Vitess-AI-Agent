"""
File upload and download endpoints.

This module provides endpoints for uploading files, managing file metadata,
and handling output files for simulation threads.
"""
import logging
from typing import Any
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from vitess_ai.server.file_storage import get_file_storage_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    thread_id: str = Form(...),
    module_type: str = Form(...)
) -> dict[str, Any]:
    """
    Upload a file for a specific module type in a thread.
    
    Args:
        file: The file to upload
        thread_id: Thread ID to associate file with
        module_type: Module type (readin, guide, instrument, writeout)
        
    Returns:
        Dictionary with file metadata
    """
    try:
        # Read file content
        file_content = await file.read()
        
        # Upload file
        storage_service = get_file_storage_service()
        file_metadata = storage_service.upload_file(
            file_content=file_content,
            filename=file.filename or "unknown",
            thread_id=thread_id,
            module_type=module_type
        )
        
        logger.info(f"File uploaded successfully: {file_metadata['filename']} (thread_id={thread_id}, module_type={module_type})")
        return {
            "status": "success",
            "file": file_metadata
        }
    except ValueError as e:
        logger.error(f"File upload validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"File upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")


@router.get("/files/{file_id}")
async def get_file_info(
    file_id: str,
    thread_id: str = Query(...),
    module_type: str = Query(...)
) -> dict[str, Any]:
    """
    Get file information by file ID.
    
    Args:
        file_id: File ID
        thread_id: Thread ID
        module_type: Module type
        
    Returns:
        Dictionary with file metadata
    """
    try:
        storage_service = get_file_storage_service()
        file_info = storage_service.get_file_info(file_id, thread_id, module_type)
        
        if file_info is None:
            raise HTTPException(status_code=404, detail="File not found")
        
        return {
            "status": "success",
            "file": file_info
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting file info: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get file info: {str(e)}")


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str,
    thread_id: str = Query(...),
    module_type: str = Query(...)
) -> dict[str, Any]:
    """
    Delete a file by file ID.
    
    Args:
        file_id: File ID
        thread_id: Thread ID
        module_type: Module type
        
    Returns:
        Dictionary with delete status
    """
    try:
        storage_service = get_file_storage_service()
        deleted = storage_service.delete_file(file_id, thread_id, module_type)
        
        if not deleted:
            raise HTTPException(status_code=404, detail="File not found")
        
        return {
            "status": "success",
            "message": "File deleted successfully",
            "file_id": file_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")


@router.get("/files/thread/{thread_id}")
async def list_thread_files(
    thread_id: str,
    module_type: str | None = Query(None, description="Optional module type filter")
) -> dict[str, Any]:
    """
    List files for a thread, optionally filtered by module type.
    
    Args:
        thread_id: Thread ID
        module_type: Optional module type filter
        
    Returns:
        Dictionary with list of file metadata
    """
    try:
        storage_service = get_file_storage_service()
        files = storage_service.list_files(thread_id, module_type)
        
        return {
            "status": "success",
            "thread_id": thread_id,
            "module_type": module_type,
            "file_count": len(files),
            "files": files
        }
    except Exception as e:
        logger.error(f"Error listing files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")


@router.delete("/files/thread/{thread_id}")
async def delete_thread_files(thread_id: str) -> dict[str, Any]:
    """
    Delete all files (uploads and outputs) for a thread.
    
    Args:
        thread_id: Thread ID
        
    Returns:
        Dictionary with delete status
    """
    try:
        storage_service = get_file_storage_service()
        deleted_count = storage_service.delete_thread_files(thread_id)
        deleted_outputs = storage_service.delete_thread_outputs(thread_id)
        
        return {
            "status": "success",
            "message": f"Deleted {deleted_count} upload files and {deleted_outputs} output files for thread {thread_id}",
            "thread_id": thread_id,
            "deleted_uploads": deleted_count,
            "deleted_outputs": deleted_outputs,
            "total_deleted": deleted_count + deleted_outputs
        }
    except Exception as e:
        logger.error(f"Error deleting thread files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete thread files: {str(e)}")


# ============================================================================
# OUTPUT FILE ENDPOINTS
# ============================================================================

@router.get("/files/thread/{thread_id}/outputs")
async def list_output_files(thread_id: str) -> dict[str, Any]:
    """
    List output files for a thread.
    
    Args:
        thread_id: Thread ID
        
    Returns:
        Dictionary with list of output file metadata
    """
    try:
        storage_service = get_file_storage_service()
        files = storage_service.list_output_files(thread_id)
        
        return {
            "status": "success",
            "thread_id": thread_id,
            "file_count": len(files),
            "files": files
        }
    except Exception as e:
        logger.error(f"Error listing output files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list output files: {str(e)}")


@router.post("/files/thread/{thread_id}/outputs")
async def save_output_file(
    thread_id: str,
    filename: str = Form(...),
    file: UploadFile = File(...)
) -> dict[str, Any]:
    """
    Save a simulation output file for a thread.
    
    Args:
        thread_id: Thread ID
        filename: Output filename
        file: The output file to save
        
    Returns:
        Dictionary with file metadata
    """
    try:
        # Read file content
        file_content = await file.read()
        
        # Save output file
        storage_service = get_file_storage_service()
        file_metadata = storage_service.save_output_file(
            file_content=file_content,
            filename=filename or file.filename or "output",
            thread_id=thread_id
        )
        
        logger.info(f"Output file saved: {filename} for thread {thread_id}")
        return {
            "status": "success",
            "file": file_metadata
        }
    except Exception as e:
        logger.error(f"Error saving output file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save output file: {str(e)}")


@router.delete("/files/thread/{thread_id}/outputs/{filename}")
async def delete_output_file(
    thread_id: str,
    filename: str
) -> dict[str, Any]:
    """
    Delete an output file.
    
    Args:
        thread_id: Thread ID
        filename: Output filename
        
    Returns:
        Dictionary with delete status
    """
    try:
        storage_service = get_file_storage_service()
        deleted = storage_service.delete_output_file(thread_id, filename)
        
        if not deleted:
            raise HTTPException(status_code=404, detail="Output file not found")
        
        return {
            "status": "success",
            "message": "Output file deleted successfully",
            "thread_id": thread_id,
            "filename": filename
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting output file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete output file: {str(e)}")


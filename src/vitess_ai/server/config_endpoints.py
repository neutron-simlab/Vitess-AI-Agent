"""
Vitess configuration endpoints.

This module provides endpoints for managing Vitess environment configuration
at runtime, including paths for modules, project, and logs.
"""
from typing import Any
from fastapi import APIRouter, HTTPException, Query

from vitess_ai.core.log import get_logger
from vitess_ai.core.config import global_config
from vitess_ai.server.file_storage import get_file_storage_service
from vitess_ai.server.agent_registry import DEFAULT_AGENT, get_agent_instance
from vitess_ai.server_agents.supervisor import SupervisorAgent

logger = get_logger(__name__)

router = APIRouter()


@router.get("/config/vitess")
async def get_vitess_config() -> dict[str, Any]:
    """
    Get current Vitess environment configuration.
    
    Returns:
        Dictionary with current Vitess environment variables
    """
    return {
        "status": "success",
        "config": {
            "VITESS_MODULES_PATH": global_config.VITESS_MODULES_PATH,
            "VITESS_PROJECT_PATH": global_config.VITESS_PROJECT_PATH,
            "VITESS_LOG_PATH": global_config.VITESS_LOG_PATH,
            "variables": global_config.get_vitess_variables()
        }
    }


@router.put("/config/vitess")
async def update_vitess_config(
    modules_path: str | None = Query(None, description="Vitess modules path (V)"),
    project_path: str | None = Query(None, description="Vitess project path (P)"),
    log_path: str | None = Query(None, description="Vitess log path (L)")
) -> dict[str, Any]:
    """
    Update Vitess environment configuration at runtime.
    
    Args:
        modules_path: New path for Vitess modules (V)
        project_path: New path for Vitess project (P)
        log_path: New path for Vitess logs (L)
    
    Returns:
        Dictionary with updated Vitess environment variables
    """
    try:
        # Update configuration
        updated_vars = global_config.update_vitess_config(
            modules_path=modules_path,
            project_path=project_path,
            log_path=log_path
        )
        
        # If project path changed, reinitialize file storage service
        if project_path is not None:
            try:
                # Reinitialize file storage service with new project path
                storage_service = get_file_storage_service()
                storage_service.reinitialize()
                logger.info(f"Vitess config updated. File storage reinitialized with new project path: {project_path}")
            except Exception as e:
                logger.warning(f"File storage service reinitialization failed: {e}")
        
        logger.info(f"Vitess configuration updated: {updated_vars}")
        
        return {
            "status": "success",
            "message": "Vitess configuration updated successfully",
            "config": {
                "VITESS_MODULES_PATH": global_config.VITESS_MODULES_PATH,
                "VITESS_PROJECT_PATH": global_config.VITESS_PROJECT_PATH,
                "VITESS_LOG_PATH": global_config.VITESS_LOG_PATH,
                "variables": updated_vars
            }
        }
    except Exception as e:
        logger.error(f"Error updating Vitess config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update Vitess config: {str(e)}")


@router.post("/config/vitess/reset")
async def reset_vitess_config() -> dict[str, Any]:
    """
    Reset Vitess environment configuration to defaults from environment variables.
    
    Returns:
        Dictionary with reset Vitess environment variables
    """
    try:
        reset_vars = global_config.reset_vitess_config()
        
        logger.info(f"Vitess configuration reset to defaults: {reset_vars}")
        
        return {
            "status": "success",
            "message": "Vitess configuration reset to defaults",
            "config": {
                "VITESS_MODULES_PATH": global_config.VITESS_MODULES_PATH,
                "VITESS_PROJECT_PATH": global_config.VITESS_PROJECT_PATH,
                "VITESS_LOG_PATH": global_config.VITESS_LOG_PATH,
                "variables": reset_vars
            }
        }
    except Exception as e:
        logger.error(f"Error resetting Vitess config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to reset Vitess config: {str(e)}")


@router.get("/config/modules")
async def get_modules_config(agent_id: str = DEFAULT_AGENT) -> dict[str, Any]:
    """
    Get module information from the supervisor agent.
    
    Returns module metadata including name, display_name, description, and order
    for all registered modules. This allows the UI to dynamically display
    module names and colors.
    
    Args:
        agent_id: Agent identifier (defaults to "supervisor")
    
    Returns:
        Dictionary with module information including:
        - status: "success" or "error"
        - modules: List of module info dictionaries with name, display_name, description, order
    """
    try:
        # Try to get agent instance from registry
        agent_instance = get_agent_instance(agent_id)
        
        if agent_instance is None:
            # If no agent exists yet, we can't get module info
            # Return empty list - UI will use fallback values
            logger.warning(f"Agent '{agent_id}' not found in registry. Returning empty module list.")
            return {
                "status": "success",
                "modules": [],
                "message": "Agent not initialized yet. Module info will be available after first agent call."
            }
        
        # Check if agent is a SupervisorAgent (has list_modules method)
        if not isinstance(agent_instance, SupervisorAgent):
            logger.warning(f"Agent '{agent_id}' is not a SupervisorAgent. Cannot get module info.")
            return {
                "status": "success",
                "modules": [],
                "message": f"Agent '{agent_id}' does not support module listing."
            }
        
        # Get module information from supervisor
        modules_info = agent_instance.list_modules()
        
        logger.info(f"Retrieved {len(modules_info)} modules from supervisor")
        
        return {
            "status": "success",
            "modules": modules_info
        }
    except Exception as e:
        logger.error(f"Error getting module config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get module config: {str(e)}")


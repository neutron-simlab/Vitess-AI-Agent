"""
Module tracking utilities for detecting the current module from state and node paths.

This module provides utilities for extracting module information from LangGraph
state and node paths, enabling proper module labeling for color coding in the UI.
"""

import logging
from typing import Any, Optional
from langgraph.graph.state import CompiledStateGraph
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


class ModuleTracker:
    """
    Utility class for tracking the current module from state and node paths.
    
    Extracts module information from:
    1. Unified state's current_module field
    2. Node paths (e.g., "readin_welcome" -> "readin")
    3. Supervisor node detection
    """
    
    # Known module prefixes for extraction from node paths
    KNOWN_MODULES = ['readin', 'guide', 'writeout']
    SUPERVISOR_KEYWORD = 'supervisor'
    
    @staticmethod
    async def get_current_module(
        agent: CompiledStateGraph,
        config: RunnableConfig,
        node_path: str | None = None
    ) -> Optional[str]:
        """
        Get the current module from state or node path.
        
        Args:
            agent: The compiled state graph
            config: The runnable config for state access
            node_path: Optional node path to extract module from
            
        Returns:
            Module name or None if not detected
        """
        # Try to get module from state first
        try:
            state: Any = await agent.aget_state(config=config)
            if state and hasattr(state, 'values') and state.values:
                current_module = state.values.get('current_module')
                if current_module:
                    return current_module
        except Exception as e:
            logger.debug(f"Could not get module from state: {e}")
        
        # Fallback to node path extraction
        if node_path:
            return ModuleTracker._extract_from_node_path(node_path)
        
        return None
    
    @staticmethod
    def _extract_from_node_path(node_path: str) -> Optional[str]:
        """
        Extract module name from node path.
        
        Examples:
            "readin_welcome" -> "readin"
            "supervisor_welcome" -> "supervisor"
            "guide_params_config" -> "guide"
            
        Args:
            node_path: The node path string
            
        Returns:
            Module name or None if not detected
        """
        if not isinstance(node_path, str):
            return None
        
        # Check for supervisor first
        if ModuleTracker.SUPERVISOR_KEYWORD in node_path:
            return 'supervisor'
        
        # Extract module from path parts
        parts = node_path.split('_')
        if parts and parts[0] in ModuleTracker.KNOWN_MODULES:
            return parts[0]
        
        return None
    
    @staticmethod
    def get_module_for_message(
        current_module: Optional[str],
        node_path: Optional[str],
        default: str = 'supervisor'
    ) -> str:
        """
        Get module name for a message, with fallback logic.
        
        Args:
            current_module: Current module from state
            node_path: Node path for extraction
            default: Default module name if none detected
            
        Returns:
            Module name to use for the message
        """
        if current_module:
            return current_module
        
        if node_path:
            extracted = ModuleTracker._extract_from_node_path(node_path)
            if extracted:
                return extracted
        
        return default
    
    @staticmethod
    def is_supervisor_node(node_path: str) -> bool:
        """Check if a node path represents a supervisor node."""
        if not isinstance(node_path, str):
            return False
        return ModuleTracker.SUPERVISOR_KEYWORD in node_path
    
    @staticmethod
    def is_internal_node(node_path: str) -> bool:
        """Check if a node path represents an internal (non-user-facing) node."""
        if not isinstance(node_path, str):
            return False
        
        # Internal nodes that don't emit user-facing messages
        internal_keywords = ['supervisor_summarize']
        return any(keyword in node_path for keyword in internal_keywords)


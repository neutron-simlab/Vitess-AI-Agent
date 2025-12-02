"""
Custom exceptions for the Vitess AI Agent server.

This module defines custom exception classes for better error handling
and more specific error messages throughout the service layer.
"""

from typing import Any, Optional


class VitessServerError(Exception):
    """Base exception for all Vitess server errors."""
    
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AgentNotFoundError(VitessServerError):
    """Raised when a requested agent is not found or cannot be created."""
    
    def __init__(self, agent_id: str, details: dict[str, Any] | None = None):
        message = f"Agent '{agent_id}' not found or could not be created"
        super().__init__(message, details)
        self.agent_id = agent_id


class StreamingError(VitessServerError):
    """Raised when an error occurs during streaming operations."""
    
    def __init__(self, message: str, stream_mode: Optional[str] = None, details: dict[str, Any] | None = None):
        super().__init__(message, details)
        self.stream_mode = stream_mode


class InterruptError(VitessServerError):
    """
    Raised when an error occurs during interrupt handling.
    
    DEPRECATED: This exception is deprecated as of the react-agent architecture refactoring.
    The react-agent architecture uses the END pattern instead of interrupts.
    Use StateError instead for state-related errors.
    """
    
    def __init__(self, message: str, thread_id: Optional[str] = None, details: dict[str, Any] | None = None):
        import warnings
        warnings.warn(
            "InterruptError is deprecated. Use StateError instead. "
            "The react-agent architecture uses END pattern, not interrupts.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(message, details)
        self.thread_id = thread_id


class StateError(VitessServerError):
    """Raised when an error occurs during state operations."""
    
    def __init__(self, message: str, operation: Optional[str] = None, details: dict[str, Any] | None = None):
        super().__init__(message, details)
        self.operation = operation


class MessageProcessingError(VitessServerError):
    """Raised when an error occurs during message processing."""
    
    def __init__(self, message: str, message_type: Optional[str] = None, details: dict[str, Any] | None = None):
        super().__init__(message, details)
        self.message_type = message_type


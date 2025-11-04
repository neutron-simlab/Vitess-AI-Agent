"""
FastAPI service for Vitess AI Agent.

This module sets up the FastAPI application and registers all endpoint routers.
"""
import logging
import warnings
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langchain_core._api import LangChainBetaWarning

from vitess_ai.schema.server import HealthStatus
from vitess_ai.server.api_endpoints import router as api_router
from vitess_ai.server.file_endpoints import router as file_router
from vitess_ai.server.config_endpoints import router as config_router

warnings.filterwarnings("ignore", category=LangChainBetaWarning)
logger = logging.getLogger(__name__)


def _setup_service_logging():
    """Setup logging for the service"""
    # Only add handler if logger doesn't have one (avoid duplicates)
    if not logger.handlers:
        # Create console handler
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        # Prevent propagation to avoid duplicate logs
        logger.propagate = False


# Setup logging when module is imported
_setup_service_logging()
logger.info("Service logging initialized")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Simple lifespan for in-memory only operation.
    """
    # No database/store initialization needed for in-memory operation
    yield


app = FastAPI(lifespan=lifespan)

# Register all routers
app.include_router(api_router)
app.include_router(file_router)
app.include_router(config_router)


@app.get("/health")
async def health_check() -> HealthStatus:
    """Health check endpoint."""
    return HealthStatus(
        status="ok",
        version="0.1.0",
        details={"service": "vitess-ai-agent", "uptime": "running"}
    )

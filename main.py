import os
import uvicorn


def main():
    """Run the FastAPI server using uvicorn."""
    # Disable reload in production (Docker) by default, enable via RELOAD env var
    reload = os.getenv("RELOAD", "false").lower() == "true"
    
    uvicorn.run(
        "vitess_ai.server.service:app",  # Import string for reload support
        host="0.0.0.0",
        port=8000,
        reload=reload,  # Enable auto-reload only if RELOAD=true
        log_level="info"
    )


if __name__ == "__main__":
    main()
import uvicorn


def main():
    """Run the FastAPI server using uvicorn."""
    uvicorn.run(
        "vitess_ai.server.service:app",  # Import string for reload support
        host="0.0.0.0",
        port=8000,
        reload=True,  # Enable auto-reload for development
        log_level="info"
    )


if __name__ == "__main__":
    main()
#!/bin/bash
set -e

# Function to handle shutdown
cleanup() {
    echo "Shutting down services..."
    kill $STREAMLIT_PID 2>/dev/null || true
    exit 0
}

# Trap signals for graceful shutdown
trap cleanup SIGTERM SIGINT EXIT

# Start Streamlit in the background
echo "Starting Streamlit on port 8501..."
uv run streamlit run app/streamlit_app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    &
STREAMLIT_PID=$!

# Start FastAPI in the foreground (so we see logs and it's the main process)
echo "Starting FastAPI on port 8000..."
uv run python main.py


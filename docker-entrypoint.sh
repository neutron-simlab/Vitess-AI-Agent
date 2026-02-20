#!/bin/bash
set -e

# Array to store MCP server PIDs
MCP_PIDS=()

# Function to handle shutdown
cleanup() {
    echo "Shutting down services..."
    # Kill MCP servers
    for pid in "${MCP_PIDS[@]}"; do
        kill $pid 2>/dev/null || true
    done
    kill $STREAMLIT_PID 2>/dev/null || true
    exit 0
}

# Trap signals for graceful shutdown
trap cleanup SIGTERM SIGINT EXIT

# Verify Vitess environment variables are set
if [ -z "$VITESS_MODULES_PATH" ]; then
    echo "⚠️  Warning: VITESS_MODULES_PATH not set, using default"
    export VITESS_MODULES_PATH=${VITESS_MODULES_PATH:-/vitess/MODULES}
fi

if [ -z "$VITESS_PROJECT_PATH" ]; then
    echo "⚠️  Warning: VITESS_PROJECT_PATH not set, using default"
    export VITESS_PROJECT_PATH=${VITESS_PROJECT_PATH:-/data/projects}
fi

if [ -z "$VITESS_LOG_PATH" ]; then
    echo "⚠️  Warning: VITESS_LOG_PATH not set, using default"
    export VITESS_LOG_PATH=${VITESS_LOG_PATH:-/data/logs/logfile.log}
fi

# Verify Vitess modules directory is accessible
if [ -d "$VITESS_MODULES_PATH" ]; then
    module_count=$(find "$VITESS_MODULES_PATH" -type f -executable 2>/dev/null | wc -l || echo "0")
    echo "✅ Vitess modules directory found: $VITESS_MODULES_PATH ($module_count executables)"
else
    echo "⚠️  Warning: Vitess modules directory not found: $VITESS_MODULES_PATH"
    echo "   Make sure the vitess service is running and volumes are properly mounted"
fi

# Create required directories
# Note: VITESS_LOG_PATH is a file path, not a directory
VITESS_LOG_DIR=$(dirname "$VITESS_LOG_PATH")
mkdir -p "$VITESS_PROJECT_PATH" "$VITESS_LOG_DIR"
# Create the log file if it doesn't exist
touch "$VITESS_LOG_PATH"
echo "✅ Project directory: $VITESS_PROJECT_PATH"
echo "✅ Log file: $VITESS_LOG_PATH"

# Activate virtual environment if it exists
if [ -f "/app/.venv/bin/activate" ]; then
    echo "Activating virtual environment..."
    source /app/.venv/bin/activate
fi

# Load environment file (production: /etc/vitess-ai/.env, development: .env in project root)
if [ -f "/etc/vitess-ai/.env" ]; then
    export VITESS_ENV_PATH=/etc/vitess-ai/.env
    echo "✅ Using production environment file: /etc/vitess-ai/.env"
else
    echo "ℹ️  Production env file not found, using default .env location"
fi

# Start MCP servers if HTTP transport mode is enabled
MCP_TRANSPORT_MODE=${MCP_TRANSPORT_MODE:-http}
if [ "$MCP_TRANSPORT_MODE" = "http" ]; then
    echo "Starting MCP servers in HTTP mode..."
    
    # Set default ports if not provided
    MCP_SUPERVISOR_PORT=${MCP_SUPERVISOR_PORT:-9005}
    MCP_HOST=${MCP_HOST:-0.0.0.0}
    
    # Export MCP configuration for server scripts
    export MCP_TRANSPORT_MODE=http
    export MCP_HOST=$MCP_HOST
    
    # Set MCP tool paths (use env vars if provided, otherwise use defaults)
    SUPERVISOR_MCP_PATH=${SUPERVISOR_MCP_PATH:-src/vitess_ai/mcp/supervisor_tools.py}
    
    # Start Supervisor MCP server
    echo "  Starting Supervisor MCP server on port $MCP_SUPERVISOR_PORT..."
    export MCP_SUPERVISOR_PORT=$MCP_SUPERVISOR_PORT
    uv run python "$SUPERVISOR_MCP_PATH" > /tmp/mcp_supervisor.log 2>&1 &
    MCP_PIDS+=($!)
    echo "    PID: $!"
    
    # Wait a moment for servers to start
    echo "  Waiting for MCP servers to initialize..."
    sleep 3
    
    # Check if servers are still running
    running_count=0
    for pid in "${MCP_PIDS[@]}"; do
        if kill -0 $pid 2>/dev/null; then
            running_count=$((running_count + 1))
        else
            echo "  ⚠️  Warning: MCP server with PID $pid is not running"
        fi
    done
    
    if [ $running_count -ge 1 ]; then
        echo "✅ MCP server started successfully (PIDs: ${MCP_PIDS[*]})"
    else
        echo "⚠️  Warning: NO MCP server started"
        echo "   Check logs in /tmp/mcp_*.log for details"
    fi
else
    echo "ℹ️  MCP transport mode is '$MCP_TRANSPORT_MODE', skipping HTTP server startup"
fi

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


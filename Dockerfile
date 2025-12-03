FROM python:3.13-slim

# Install system dependencies including bash for entrypoint script
RUN apt-get update && apt-get install -y \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files and package source first for better layer caching
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# Install dependencies using uv
RUN uv sync --frozen

# Copy the rest of the application (excluding vitess/ which is handled separately)
COPY . .

# Make entrypoint script executable
RUN chmod +x docker-entrypoint.sh

# Create directories for shared data (will be mounted as volumes in docker-compose)
RUN mkdir -p /data/projects /data/logs /vitess/MODULES

# Expose ports
EXPOSE 8000 8501 9001 9002 9003 9004 9005

# Set entrypoint
ENTRYPOINT ["./docker-entrypoint.sh"]


FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
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

# Copy the rest of the application
COPY . .

# Make entrypoint script executable
RUN chmod +x docker-entrypoint.sh

# Expose ports
EXPOSE 8000 8501

# Set entrypoint
ENTRYPOINT ["./docker-entrypoint.sh"]


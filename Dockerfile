# Multi-stage build: Stage 1 clones and builds Vitess; Stage 2 is the app and copies only MODULES.
# Vitess is built from the official repo at image build time (no submodule).

# -----------------------------------------------------------------------------
# Stage 1: Clone and build Vitess from source (same approach as vitess .gitlab-ci compile-ubuntu)
# -----------------------------------------------------------------------------
FROM ubuntu:22.04 AS vitess-build

ENV DEBIAN_FRONTEND=noninteractive

# Build dependencies (same as .gitlab-ci.yml compile-ubuntu before_script)
RUN apt-get update && apt-get install -y \
    make \
    gcc \
    g++ \
    libxpm-dev \
    libpng-dev \
    libgd-dev \
    zlib1g-dev \
    git \
    unzip \
    cmake \
    libxml2-dev \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG VITESS_REPO=https://iffgit.fz-juelich.de/vitess/vitess.git
ARG VITESS_REF=develop

RUN git clone --depth 1 --branch "${VITESS_REF}" "${VITESS_REPO}" /vitess-src

WORKDIR /vitess-src/SRC

RUN mkdir -p ../MODULES && \
    make all LTO=1 && \
    make install

# -----------------------------------------------------------------------------
# Stage 2: Vitess AI Agent application
# -----------------------------------------------------------------------------
FROM python:3.13-slim

# Install system dependencies including bash for entrypoint script
RUN apt-get update && apt-get install -y \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy Vitess MODULES from build stage (no submodule)
COPY --from=vitess-build /vitess-src/MODULES /vitess/MODULES

# Vitess installs as name_Linux_arch (e.g. read_in_Linux_aarch64). Create short-name symlinks
# so scripts can call /vitess/MODULES/read_in etc. regardless of architecture.
RUN set -e; for f in /vitess/MODULES/*_Linux_*; do \
      [ -f "$f" ] || continue; \
      base="${f%_Linux_*}"; base="${base##*/}"; \
      [ -e "/vitess/MODULES/$base" ] || ln -s "$(basename "$f")" "/vitess/MODULES/$base"; \
    done

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

# Create directories for shared data (will be mounted as volumes in docker-compose)
RUN mkdir -p /data/projects /data/logs

# Expose ports
EXPOSE 8000 8501 9001 9002 9003 9004 9005

# Set entrypoint
ENTRYPOINT ["./docker-entrypoint.sh"]

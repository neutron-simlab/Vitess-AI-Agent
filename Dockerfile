# Multi-stage build: Stage 1 clones and builds Vitess; Stage 2 is the app and copies only MODULES.
# Vitess is built from the official repo at image build time (no submodule).

# -----------------------------------------------------------------------------
# Stage 1: Download prebuilt Vitess on amd64, otherwise build from source
# -----------------------------------------------------------------------------
FROM ubuntu:22.04 AS vitess-build

ENV DEBIAN_FRONTEND=noninteractive

ARG TARGETARCH

# Build dependencies (same as .gitlab-ci.yml compile-ubuntu before_script)
RUN set -eux; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    apt-get update; \
    if [ "${arch}" = "amd64" ]; then \
      apt-get install -y --no-install-recommends \
        curl \
        ca-certificates; \
    else \
      apt-get install -y --no-install-recommends \
        curl \
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
        ca-certificates; \
    fi; \
    rm -rf /var/lib/apt/lists/*

ARG VITESS_REPO=https://iffgit.fz-juelich.de/vitess/vitess.git
ARG VITESS_REF=develop
ARG VITESS_TARBALL_URL=https://iffgit.fz-juelich.de/vitess/vitess/-/jobs/1074589/artifacts/raw/Downloads/Vitess3.7-Ubuntu-x86_64.tar.gz

RUN set -eux; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    if [ "${arch}" = "amd64" ] && [ -n "${VITESS_TARBALL_URL}" ]; then \
      echo "Using prebuilt Vitess for ${arch}"; \
      mkdir -p /vitess-src/MODULES; \
      curl -fsSL "${VITESS_TARBALL_URL}" -o /tmp/vitess.tar.gz; \
      mkdir -p /tmp/vitess; \
      tar -xzf /tmp/vitess.tar.gz -C /tmp/vitess; \
      modules_dir="$(find /tmp/vitess -type d -name MODULES | head -n 1)"; \
      test -n "${modules_dir}"; \
      cp -a "${modules_dir}/." /vitess-src/MODULES/; \
    else \
      echo "Building Vitess from source for ${arch}"; \
      git clone --depth 1 --branch "${VITESS_REF}" "${VITESS_REPO}" /vitess-src; \
      cd /vitess-src/SRC; \
      mkdir -p ../MODULES; \
      make all LTO=1; \
      make install; \
    fi

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

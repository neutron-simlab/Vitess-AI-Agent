# One image, two commands: the MCP service runs the VITESS binaries, the
# application runs the API and the UI, and both mount the same project volume
# at the same path. Building one image rather than two is what guarantees the
# file layouts match (03-VITESS-V2.md, CP3).
#
# The build context is the PARENT of this repository, not this repository, so
# every source path below is prefixed with a directory name. It has to be:
# juena-core is a sibling path dependency, and a build context cannot reach
# outside itself. See docker-compose.yml's `context: ..`.
#
# Because the context root is the parent, Docker reads `Dockerfile.dockerignore`
# beside this file. This repository has no `.dockerignore` and would not be
# consulted if it had one.

# -----------------------------------------------------------------------------
# Stage 1: VITESS itself. Prebuilt on amd64, compiled from source elsewhere.
# -----------------------------------------------------------------------------
FROM ubuntu:22.04 AS vitess-build

ENV DEBIAN_FRONTEND=noninteractive

ARG TARGETARCH
ARG VITESS_REPO=https://iffgit.fz-juelich.de/vitess/vitess.git
ARG VITESS_REF=develop
ARG VITESS_TARBALL_URL=https://iffgit.fz-juelich.de/vitess/vitess/-/jobs/1074589/artifacts/raw/Downloads/Vitess3.7-Ubuntu-x86_64.tar.gz

RUN set -eux; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    apt-get update; \
    if [ "${arch}" = "amd64" ]; then \
      apt-get install -y --no-install-recommends curl ca-certificates; \
    else \
      apt-get install -y --no-install-recommends \
        curl make gcc g++ libxpm-dev libpng-dev libgd-dev zlib1g-dev git \
        unzip cmake libxml2-dev python3 ca-certificates; \
    fi; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    if [ "${arch}" = "amd64" ] && [ -n "${VITESS_TARBALL_URL}" ]; then \
      echo "Using prebuilt VITESS for ${arch}"; \
      mkdir -p /vitess-src/MODULES; \
      curl -fsSL "${VITESS_TARBALL_URL}" -o /tmp/vitess.tar.gz; \
      mkdir -p /tmp/vitess; \
      tar -xzf /tmp/vitess.tar.gz -C /tmp/vitess; \
      modules_dir="$(find /tmp/vitess -type d -name MODULES | head -n 1)"; \
      test -n "${modules_dir}"; \
      cp -a "${modules_dir}/." /vitess-src/MODULES/; \
    else \
      echo "Compiling VITESS from source for ${arch}"; \
      git clone --depth 1 --branch "${VITESS_REF}" "${VITESS_REPO}" /vitess-src; \
      cd /vitess-src/SRC; \
      mkdir -p ../MODULES; \
      make all LTO=1; \
      make install; \
    fi

# -----------------------------------------------------------------------------
# Stage 2: the application image
# -----------------------------------------------------------------------------
FROM python:3.11-slim

# curl is the health check; libstdc++ and libgcc are what the monitor binaries
# link against (`ldd monitor2D`), and nothing else in MODULES needs more than
# libc and libm.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl bash libstdc++6 libgcc-s1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY --from=vitess-build /vitess-src/MODULES /vitess/MODULES

# VITESS installs as name_Linux_arch (read_in_Linux_aarch64). The catalog stores
# plain basenames (CP2) and `resolve_executable` refuses anything with a slash,
# so the short names have to exist in the directory itself.
RUN set -eux; \
    for binary in /vitess/MODULES/*_Linux_*; do \
      [ -f "${binary}" ] || continue; \
      short="${binary%_Linux_*}"; short="${short##*/}"; \
      [ -e "/vitess/MODULES/${short}" ] || ln -s "$(basename "${binary}")" "/vitess/MODULES/${short}"; \
    done; \
    test -x /vitess/MODULES/read_in

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"

# Lockfile and project metadata first, for layer caching.
COPY Vitess-AI-Agent-v2/pyproject.toml Vitess-AI-Agent-v2/uv.lock Vitess-AI-Agent-v2/README.md ./

# The VITESS documentation submodule: a path dependency, so `uv sync` fails
# without it. Its `data/` markdown is what CP6 indexes into Chroma.
COPY Vitess-AI-Agent-v2/rag/vitess-rag/ ./rag/vitess-rag/

# juena-core, the sibling source this application consumes. `[tool.uv.sources]`
# declares it as `{ path = "../juena-core" }`, and uv resolves that relative to
# the project directory -- which is /app here, so core must land at /juena-core.
COPY juena-core/ /juena-core/

RUN uv sync --frozen --no-dev --no-install-project

COPY Vitess-AI-Agent-v2/src/ ./src/

RUN uv sync --frozen --no-dev

# The project volume is mounted here in both services. Creating it in the image
# with the runtime user's ownership is what makes a fresh named volume writable
# without running as root: Docker copies this directory's mode and owner into an
# empty volume the first time it is mounted.
RUN useradd --create-home --uid 10001 vitess \
    && mkdir -p /data/projects \
    && chown -R vitess:vitess /data/projects

USER vitess

# 9005: the FastMCP server. Reachable on the Compose network only; the compose
# file publishes no port for it, because MCP has no authentication.
EXPOSE 9005

CMD ["python", "-m", "vitess_ai.mcp.server"]

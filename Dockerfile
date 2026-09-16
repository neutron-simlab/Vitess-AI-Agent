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
# Stage 1: VITESS itself. Every architecture builds the same pinned revision.
# -----------------------------------------------------------------------------
ARG VITESS_COMMIT=6bd0e0066c4667444368dd2492f77821ff8a5609
ARG UV_VERSION=0.12.15

FROM ubuntu:22.04 AS vitess-build

ENV DEBIAN_FRONTEND=noninteractive

ARG VITESS_REPO=https://iffgit.fz-juelich.de/vitess/vitess.git
ARG VITESS_COMMIT

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      make gcc g++ libxpm-dev libpng-dev libgd-dev zlib1g-dev git \
      unzip cmake libxml2-dev python3 ca-certificates; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    git init /vitess-src; \
    git -C /vitess-src remote add origin "${VITESS_REPO}"; \
    git -C /vitess-src fetch --depth 1 origin "${VITESS_COMMIT}"; \
    git -C /vitess-src checkout --detach FETCH_HEAD; \
    test "$(git -C /vitess-src rev-parse HEAD)" = "${VITESS_COMMIT}"; \
    cd /vitess-src/SRC; \
    mkdir -p ../MODULES; \
    make all LTO=1; \
    make install

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-build

# -----------------------------------------------------------------------------
# Stage 2: the application image
# -----------------------------------------------------------------------------
FROM python:3.11-slim

ARG VITESS_COMMIT
LABEL de.fz-juelich.vitess.source-revision="${VITESS_COMMIT}"

# curl is the health check; libstdc++ and libgcc are what the monitor binaries
# link against (`ldd monitor2D`), and nothing else in MODULES needs more than
# libc and libm.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl bash libstdc++6 libgcc-s1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv-build /uv /usr/local/bin/uv

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

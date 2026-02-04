# VITESS AI Agent

<div align="center">
  <img src="app/assets/logo.png" alt="VITESS AI Agent Logo" width="200"/>
</div>

**VITESS AI Agent** is part of **Jülich Neutron AI Agents (JüNA)**, an agentic AI system designed to assist researchers in accessing and utilizing JCNS's extensive knowledge base in neutron science. This specific agent focuses on [VITESS](https://vitess.fz-juelich.de), an open-source software package for simulating neutron scattering experiments.

> **⚠️ Testing/Preview Version**: This is a testing version of VITESS AI Agent. While functional, it is not yet production-ready. We welcome feedback and testing via Docker. The application can be tested using Docker Compose as described below.

## Key Features

- **LangGraph-Based Architecture**: Multi-agent system built on LangGraph for orchestration
- **Multi-Agent Architecture**: Specialized AI agents for different simulation modules
- **RESTful API Server**: FastAPI-based server for programmatic access
- **Web Interface**: Streamlit-based chat interface with comprehensive configuration options
- **Real-time Streaming**: Server-Sent Events (SSE) for live conversation streaming
- **Multiple LLM Providers**: Support for OpenAI and Blablador (OpenAI-compatible API)
- **File Management**: Upload and manage files for different VITESS modules
- **Runtime Configuration**: Dynamic VITESS environment configuration
- **Docker Support**: Complete Docker setup with VITESS included - no manual installation required

## Architecture

The system uses LangGraph to orchestrate specialized module agents in a unified workflow.

<div align="center">
  <img src="app/assets/vitess-ai-arch.png" alt="VITESS AI Agent Architecture" width="600"/>
</div>

## Prerequisites

- **Docker** and **Docker Compose** installed on your system
  - Docker Desktop (macOS/Windows) or Docker Engine (Linux)
  - Docker Compose v2.0+ (included with Docker Desktop)
- **API Key** for at least one LLM provider:
  - OpenAI API key ([Get one here](https://platform.openai.com/api-keys))
  - OR Blablador API key ([Take a look here](https://sdlaml.pages.jsc.fz-juelich.de/ai/guides/blablador_api_access/))

> **Note**: VITESS is automatically built and included in the Docker image. You do not need to install VITESS separately on your system.

## Quick Start

### 1. Clone the Repository

```bash
git clone <repository-url>
cd Vitess-AI-Agent
```

### 2. Configure Environment Variables

Copy the example environment file and configure your API keys:

```bash
cp env.example .env
```

Edit `.env` and set at least one LLM provider API key:

```bash
# For OpenAI
OPENAI_API_KEY=sk-your-openai-api-key-here
DEFAULT_PROVIDER=openai

# OR for Blablador
BLABLADOR_API_KEY=your-blablador-api-key-here
BLABLADOR_BASE_URL=https://api.helmholtz-blablador.fz-juelich.de/v1/
DEFAULT_PROVIDER=blablador
```

See the [Configuration](#configuration) section below for more details.

### 3. Start with Docker Compose

```bash
docker compose up
```

This will:
- Build the Docker image (includes VITESS compilation - may take several minutes on first run)
- Start the FastAPI server on `http://localhost:8000`
- Start the Streamlit web interface on `http://localhost:8501`
- Start MCP servers on ports 9001-9005

### 4. Access the Services

- **Web Interface**: Open `http://localhost:8501` in your browser
- **API Server**: `http://localhost:8000`
- **API Documentation**: `http://localhost:8000/docs`

To run in detached mode (background):

```bash
docker compose up -d
```

To view logs:

```bash
docker compose logs -f
```

To stop the services:

```bash
docker compose down
```

## Configuration

### Environment Variables

The `.env` file contains all configuration options. Key settings:

#### Required: LLM Provider API Keys

Configure at least one provider:

**OpenAI:**
```bash
OPENAI_API_KEY=sk-your-key-here
DEFAULT_PROVIDER=openai
```

**Blablador:**
```bash
BLABLADOR_API_KEY=your-key-here
BLABLADOR_BASE_URL=https://api.helmholtz-blablador.fz-juelich.de/v1/
DEFAULT_PROVIDER=blablador
```

#### Optional: LLM Settings

```bash
MAX_TOKENS=10000
TIMEOUT_SECONDS=60
MAX_RETRIES=3
```

#### Optional: LangSmith Tracing

```bash
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=your-key-here
LANGSMITH_PROJECT=Vitess-AI-Agent
```

> **Note**: VITESS paths (`VITESS_MODULES_PATH`, `VITESS_PROJECT_PATH`, `VITESS_LOG_PATH`) are automatically configured in Docker and do not need to be set manually.

For detailed configuration options, see `env.example` which includes comprehensive comments for each setting.

### Supported LLM Providers

**OpenAI**: Models `gpt-4o-mini`, `gpt-4o`, `gpt-4-turbo`, `gpt-3.5-turbo`
- Default: `gpt-4o-mini`
- Requires `OPENAI_API_KEY`

**Blablador**: OpenAI-compatible API
- Default model: `alias-fast-code` (or as configured)
- Requires `BLABLADOR_API_KEY` and `BLABLADOR_BASE_URL`

## Usage

### Web Interface (Streamlit)

Access the interactive chat interface at `http://localhost:8501`:

- Chat with AI agents using natural language
- Switch between LLM providers and models
- Manage conversation threads
- Upload files for VITESS modules
- Configure VITESS environment settings
- View real-time streaming responses

### API Server (FastAPI)

The API server runs on `http://localhost:8000`:

- Interactive API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

See [API Endpoints](#api-endpoints) below for available endpoints.

## API Endpoints

The default agent is `"supervisor"`. You can specify the agent ID in the path or omit it to use the default.

### Agent Endpoints

- **POST `/{agent_id}/invoke`** or **POST `/invoke`** - Send message and get complete response
- **POST `/{agent_id}/stream`** or **POST `/stream`** - Real-time streaming response
- **POST `/{agent_id}/restart`** or **POST `/restart`** - Restart agent with new configuration

### File Management

- **POST `/files/upload`** - Upload a file for a specific module
- **GET `/files/{file_id}`** - Get file information
- **GET `/files/thread/{thread_id}`** - List all files for a thread
- **DELETE `/files/{file_id}`** - Delete a file
- **GET `/files/{file_id}/download`** - Download a file

### Configuration

- **GET `/config/vitess`** - Get current VITESS environment configuration
- **PUT `/config/vitess`** - Update VITESS environment configuration
- **POST `/config/vitess/reset`** - Reset VITESS configuration to defaults

### Health Check

- **GET `/health`** - Health check endpoint

See `/docs` for interactive API documentation with request/response schemas.

## Available Agents

- **SupervisorAgent**: Orchestrates the entire simulation workflow
- **ReadInAgent**: Configures neutron input parameters and initial conditions
- **GuideAgent**: Handles neutron guide specifications and geometry
- **WriteoutAgent**: Manages output settings and data formats
- **MonitorsAgent**: Generate plot of 1D and 2D data

## Docker Details

### Ports

The following ports are exposed:

- **8000**: FastAPI server (main API)
- **8501**: Streamlit web interface
- **9001-9005**: MCP servers (ReadIn, Guide, Writeout, Monitor, Supervisor)

### Volumes

- **`vitess-projects`**: Persistent storage for VITESS project files (`/data/projects`)
- Logs are stored in `/data/logs` inside the container

### VITESS Integration

VITESS is automatically built from source during the Docker image build process. The compiled modules are available at `/vitess/MODULES` inside the container. No manual VITESS installation is required.

### Troubleshooting

**Container won't start:**
```bash
# Check logs
docker compose logs

# Verify .env file exists and has valid API keys
cat .env | grep API_KEY
```

**Port already in use:**
```bash
# Change ports in docker-compose.yml or stop conflicting services
# Edit ports section:
# ports:
#   - "8001:8000"  # Use different host port
```

**Build fails:**
```bash
# Clean build (no cache)
docker compose build --no-cache

# Check Docker has enough resources (memory, disk space)
docker system df
```

**API key errors:**
```bash
# Verify API keys are set correctly
docker compose exec vitess-ai-agent env | grep API_KEY

# Check .env file is loaded
docker compose config | grep OPENAI_API_KEY
```

## Project Structure

```
vitess-ai-agent/
├── app/                    # Streamlit web interface
├── src/vitess_ai/
│   ├── clients/            # API client library
│   ├── server/             # FastAPI server and endpoints
│   │   └── streaming/      # Streaming event processors
│   ├── server_agents/      # Server-optimized agents
│   ├── mcp/                # MCP validation tools
│   ├── prompts/            # Agent prompts
│   ├── schema/             # Pydantic schemas
│   └── core/               # Core utilities
├── main.py                 # Server entry point
├── docker-compose.yml      # Docker Compose configuration
├── Dockerfile              # Docker image definition
└── pyproject.toml          # Python project configuration
```

## Contributing

Areas for contribution:
- New module agents for additional VITESS simulation modules
- API enhancements and new endpoints
- Client libraries for different languages
- Documentation improvements
- Test coverage for agents and API endpoints
- Additional LLM provider support

## License

MIT License - Copyright © 2025-2026

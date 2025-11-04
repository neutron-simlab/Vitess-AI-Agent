# VITESS AI Agent

<div align="center">
  <img src="app/assets/logo.png" alt="VITESS AI Agent Logo" width="200"/>
</div>

**VITESS AI Agent** is part of **Jülich Neutron AI Agents (JüNA)**, an agentic AI system designed to assist researchers in accessing and utilizing JCNS's extensive knowledge base in neutron science. This specific agent focuses on [VITESS](https://vitess.fz-juelich.de), an open-source software package for simulating neutron scattering experiments.

## Key Features

- **Multi-Agent Architecture**: Specialized AI agents for different simulation modules
- **RESTful API Server**: FastAPI-based server for programmatic access
- **Web Interface**: Streamlit-based chat interface with comprehensive configuration options
- **Real-time Streaming**: Server-Sent Events (SSE) for live conversation streaming
- **Multiple LLM Providers**: Support for OpenAI and Blablador (OpenAI-compatible API)
- **Automated Configuration**: Guide users through neutron simulation parameters
- **CLI Generation**: Automatic generation of VITESS command-line parameters
- **Interrupt Handling**: Support for interactive agent interruptions and resumption
- **File Management**: Upload and manage files for different VITESS modules
- **Runtime Configuration**: Dynamic VITESS environment configuration

## Prerequisites

### VITESS Software Installation
**Critical Requirement**: You must have [VITESS](https://vitess.fz-juelich.de) installed on your system.

- Install VITESS following the official documentation
- Ensure `vitess` command is available in your system PATH

### System Requirements
- Python 3.13+
- Compatible with Windows, macOS, and Linux

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Server Layer                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   REST API      │  │   SSE Stream    │  │  Health Check   │ │
│  │   /invoke       │  │   /stream       │  │   /health       │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │  File Upload    │  │  File Download  │  │  Config Mgmt    │ │
│  │  /files/upload  │  │  /files/{id}    │  │  /config/vitess │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────┐    ┌──────────────────┐    ┌────────────────┐
│  SupervisorAgent│────│  BaseModuleAgent │────│ Specialized    │
│  (Orchestrator) │    │  (Abstract Base) │    │ Module Agents  │
└─────────────────┘    └──────────────────┘    └────────────────┘
         │                        │                       │
         │              ┌─────────┼─────────┐            │
         │              │         │         │            │
         ▼              ▼         ▼         ▼            ▼
┌─────────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐
│ Simulation  │ │ ReadIn   │ │ Guide   │ │ Writeout │
│ Execution   │ │ Agent    │ │ Agent   │ │ Agent    │
└─────────────┘ └──────────┘ └─────────┘ └──────────┘
```

## Installation

### Using uv (Recommended)
```bash
uv pip install .
```

### Using pip
```bash
pip install .
```

The project uses `pyproject.toml` for dependency management.

## API Server

### Starting the Server
```bash
python main.py
```
Server runs on `http://localhost:8000` with auto-reload and interactive docs at `/docs`.

### API Endpoints

The API uses agent-specific endpoints. The default agent is `"supervisor"`. You can either specify the agent ID in the path or omit it to use the default.

#### Agent Endpoints

**POST `/{agent_id}/invoke`** or **POST `/invoke`** - Send message and get complete response
```bash
# Using default supervisor agent
curl -X POST "http://localhost:8000/invoke" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Configure a neutron simulation",
    "thread_id": "sim_001",
    "provider": "openai",
    "model": "gpt-4o-mini"
  }'

# Using specific agent
curl -X POST "http://localhost:8000/supervisor/invoke" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Configure a neutron simulation",
    "thread_id": "sim_001",
    "provider": "openai",
    "model": "gpt-4o-mini"
  }'
```

**POST `/{agent_id}/stream`** or **POST `/stream`** - Real-time streaming response
```bash
curl -X POST "http://localhost:8000/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Start simulation",
    "thread_id": "sim_002",
    "stream_tokens": true,
    "provider": "openai",
    "model": "gpt-4o-mini"
  }'
```

**POST `/{agent_id}/restart`** or **POST `/restart`** - Restart agent with new configuration
```bash
curl -X POST "http://localhost:8000/restart" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "openai",
    "model": "gpt-4o"
  }'
```

#### File Management Endpoints

**POST `/files/upload`** - Upload a file for a specific module
```bash
curl -X POST "http://localhost:8000/files/upload" \
  -F "file=@simulation.inp" \
  -F "thread_id=sim_001" \
  -F "module_type=readin"
```

**GET `/files/{file_id}`** - Get file information
```bash
curl "http://localhost:8000/files/{file_id}?thread_id=sim_001&module_type=readin"
```

**GET `/files/thread/{thread_id}`** - List all files for a thread
```bash
curl "http://localhost:8000/files/thread/sim_001"
```

**DELETE `/files/{file_id}`** - Delete a file
```bash
curl -X DELETE "http://localhost:8000/files/{file_id}?thread_id=sim_001&module_type=readin"
```

**GET `/files/{file_id}/download`** - Download a file
```bash
curl "http://localhost:8000/files/{file_id}/download?thread_id=sim_001&module_type=readin" -o output.dat
```

#### Configuration Endpoints

**GET `/config/vitess`** - Get current VITESS environment configuration
```bash
curl "http://localhost:8000/config/vitess"
```

**PUT `/config/vitess`** - Update VITESS environment configuration
```bash
curl -X PUT "http://localhost:8000/config/vitess?modules_path=/path/to/modules&project_path=/path/to/project&log_path=/path/to/logs"
```

**POST `/config/vitess/reset`** - Reset VITESS configuration to defaults
```bash
curl -X POST "http://localhost:8000/config/vitess/reset"
```

#### Health Check

**GET `/health`** - Health check
```bash
curl -X GET "http://localhost:8000/health"
```

### Python Client Usage

The recommended way to interact with the API is through the `AgentClient` class:

```python
from vitess_ai.clients.client import AgentClient

# Initialize client (defaults to supervisor agent)
client = AgentClient(base_url="http://localhost:8000", agent="supervisor")

# Simple invoke - get complete response
response = client.invoke(
    message="Configure neutron beam",
    thread_id="thread_123",
    provider="openai",
    model="gpt-4o-mini"
)
print(response.content)

# Streaming response
for chunk in client.stream(
    message="Run simulation",
    thread_id="thread_123",
    stream_tokens=True,
    provider="openai",
    model="gpt-4o-mini"
):
    if hasattr(chunk, 'content'):
        print(chunk.content, end='', flush=True)
    elif isinstance(chunk, dict) and chunk.get("type") == "token":
        print(chunk.get("content", ""), end='', flush=True)

# Respond to module interrupt (uses regular stream endpoint)
for chunk in client.respond_to_module_interrupt(
    message="Yes, proceed",
    thread_id="thread_123",
    stream_tokens=True
):
    # Process streaming chunks
    pass

# Restart agent with new configuration
client.restart(provider="openai", model="gpt-4o")
```

### Async Usage

```python
import asyncio
from vitess_ai.clients.client import AgentClient

async def main():
    client = AgentClient(base_url="http://localhost:8000", agent="supervisor")
    
    # Async invoke
    response = await client.ainvoke(
        message="Configure neutron simulation",
        thread_id="thread_123",
        provider="openai",
        model="gpt-4o-mini"
    )
    print(response.content)
    
    # Async streaming
    async for chunk in client.astream(
        message="Run simulation",
        thread_id="thread_123",
        stream_tokens=True,
        provider="openai",
        model="gpt-4o-mini"
    ):
        # Process chunks
        pass

asyncio.run(main())
```

## Streamlit Web Interface

The project includes a comprehensive Streamlit-based web interface for interactive conversations with the AI agent.

### Starting the Streamlit App

First, ensure the FastAPI server is running (see API Server section above), then:

```bash
streamlit run app/streamlit_app.py
```

The app will be available at `http://localhost:8501` (default Streamlit port).

### Features

- **Interactive Chat Interface**: Real-time conversation with the AI agent
- **LLM Configuration**: Switch between OpenAI and Blablador providers with model selection
- **Thread Management**: Create new threads or continue existing conversations
- **Real-time Streaming**: See responses stream in real-time as they are generated
- **Module Interrupts**: Handle interactive prompts from specialized module agents
- **Server Configuration**: Configure and check server connection status
- **VITESS Configuration**: Configure VITESS environment paths (V, P, L) at runtime
- **File Management**: Upload, view, and delete files for different VITESS modules (readin, guide, instrument, writeout)
- **Debug Mode**: Option to view system messages for debugging
- **Auto-welcome**: Automatic welcome message when connecting to the server

The Streamlit app connects to the FastAPI server running on `http://localhost:8000` by default. You can change the server URL in the sidebar configuration.

## Configuration

Create `.env` file:

```env
# LLM Provider (openai or blablador)
DEFAULT_PROVIDER=openai
DEFAULT_MODEL=gpt-4o-mini

# OpenAI API Configuration
OPENAI_API_KEY=your_openai_key_here

# Blablador API Configuration (OpenAI-compatible)
BLABLADOR_API_KEY=your_blablador_key_here
BLABLADOR_BASE_URL=https://your-blablador-endpoint.com
BLABLADOR_DEFAULT_MODEL=alias-function-call

# Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# VITESS Environment Variables (optional, can be configured at runtime)
VITESS_MODULES_PATH=/path/to/vitess/modules
VITESS_PROJECT_PATH=/path/to/vitess/project
VITESS_LOG_PATH=/path/to/vitess/logs
```

### Supported LLM Providers

#### OpenAI
- **Models**: `gpt-4o-mini`, `gpt-4o`, `gpt-4-turbo`, `gpt-3.5-turbo`
- **Default**: `gpt-4o-mini`
- **Required**: `OPENAI_API_KEY`

#### Blablador
- **Models**: `alias-function-call`, `alias-code`
- **Default**: `alias-function-call`
- **Required**: `BLABLADOR_API_KEY`, `BLABLADOR_BASE_URL`
- **Note**: Blablador is an OpenAI-compatible API that requires function calling support

## Available Agents

- **SupervisorAgent**: Orchestrates the entire simulation workflow
- **ReadInAgent**: Configures neutron input parameters and initial conditions
- **GuideAgent**: Handles neutron guide specifications and geometry
- **WriteoutAgent**: Manages output settings and data formats

## Direct Usage

### Basic Supervisor Usage

For direct usage without the API server:

```python
import asyncio
from vitess_ai.server_agents.supervisor import create_default_server_supervisor

async def main():
    supervisor = await create_default_server_supervisor()
    # Use the supervisor's graph directly
    result = await supervisor.app.ainvoke(
        {"messages": [{"role": "user", "content": "Configure neutron simulation"}]},
        config={"configurable": {"thread_id": "simulation_001"}}
    )
    print(f"Result: {result}")

asyncio.run(main())
```

Note: The recommended way to use the system is through the FastAPI server (see API Server section above).

## Production Deployment

### Using Gunicorn
```bash
pip install gunicorn
gunicorn vitess_ai.server.service:app \
  --host 0.0.0.0 --port 8000 --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker
```

### Docker
```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY . .
RUN pip install .
EXPOSE 8000
CMD ["python", "main.py"]
```

## Project Structure

```
vitess-ai-agent/
├── app/
│   ├── streamlit_app.py      # Streamlit web interface entry point
│   ├── sidebar.py            # Sidebar configuration UI
│   ├── chat_interface.py     # Main chat interface
│   ├── file_management.py    # File management utilities
│   ├── ui_components.py      # UI components
│   └── assets/
│       └── logo.png
├── src/vitess_ai/
│   ├── clients/
│   │   └── client.py         # API client library
│   ├── server/
│   │   ├── service.py        # FastAPI application
│   │   ├── api_endpoints.py  # Agent endpoints
│   │   ├── file_endpoints.py # File management endpoints
│   │   ├── config_endpoints.py # Configuration endpoints
│   │   ├── streaming.py     # SSE streaming implementation
│   │   └── file_storage.py  # File storage service
│   ├── server_agents/        # Server-optimized agents
│   │   ├── supervisor.py    # Supervisor agent
│   │   ├── readin_module_agent.py
│   │   ├── guide_module_agent.py
│   │   └── writeout_module_agent.py
│   ├── mcp/                  # MCP validation tools
│   │   ├── readin_module_tools.py
│   │   ├── guide_module_tools.py
│   │   └── writeout_module_tools.py
│   ├── prompts/              # Agent prompts
│   ├── schema/               # Pydantic schemas
│   │   ├── server.py
│   │   ├── llm_models.py
│   │   └── ...
│   └── core/                 # Core utilities
│       ├── config.py         # Configuration management
│       └── llms_providers.py # LLM provider management
├── main.py                   # Server entry point
├── pyproject.toml            # Project dependencies
└── README.md
```

## Contributing

Areas for contribution:
- **New Module Agents**: Add support for additional VITESS simulation modules
- **API Enhancements**: Improve server performance and add new endpoints
- **Client Libraries**: Develop client libraries for different languages
- **Documentation**: Improve guides and examples
- **Testing**: Add test coverage for agents and API endpoints
- **LLM Providers**: Add support for additional LLM providers (Anthropic, Google, etc.)

## License

MIT License - Copyright © 2025

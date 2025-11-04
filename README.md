# VITESS AI Agent

<div align="center">
  <img src="app/assets/logo.png" alt="VITESS AI Agent Logo" width="200"/>
</div>

**VITESS AI Agent** is part of **Jülich Neutron AI Agents (JüNA)**, an agentic AI system designed to assist researchers in accessing and utilizing JCNS's extensive knowledge base in neutron science. This specific agent focuses on [VITESS](https://vitess.fz-juelich.de), an open-source software package for simulating neutron scattering experiments.

## Key Features

- **Multi-Agent Architecture**: Specialized AI agents for different simulation modules
- **RESTful API Server**: FastAPI-based server for programmatic access
- **Web Interface**: Streamlit-based chat interface for interactive conversations
- **Real-time Streaming**: Server-Sent Events (SSE) for live conversation streaming
- **Automated Configuration**: Guide users through neutron simulation parameters
- **CLI Generation**: Automatic generation of VITESS command-line parameters
- **Interrupt Handling**: Support for interactive agent interruptions and resumption

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

**POST `/{agent_id}/invoke`** or **POST `/invoke`** - Send message and get complete response
```bash
# Using default supervisor agent
curl -X POST "http://localhost:8000/invoke" \
  -H "Content-Type: application/json" \
  -d '{"message": "Configure a neutron simulation", "thread_id": "sim_001"}'

# Using specific agent
curl -X POST "http://localhost:8000/supervisor/invoke" \
  -H "Content-Type: application/json" \
  -d '{"message": "Configure a neutron simulation", "thread_id": "sim_001"}'
```

**POST `/{agent_id}/stream`** or **POST `/stream`** - Real-time streaming response
```bash
curl -X POST "http://localhost:8000/stream" \
  -H "Content-Type: application/json" \
  -d '{"message": "Start simulation", "thread_id": "sim_002", "stream_tokens": true}'
```

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
    thread_id="thread_123"
)
print(response.content)

# Streaming response
for chunk in client.stream(
    message="Run simulation",
    thread_id="thread_123",
    stream_tokens=True
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
        thread_id="thread_123"
    )
    print(response.content)
    
    # Async streaming
    async for chunk in client.astream(
        message="Run simulation",
        thread_id="thread_123",
        stream_tokens=True
    ):
        # Process chunks
        pass

asyncio.run(main())
```

## Streamlit Web Interface

The project includes a Streamlit-based web interface for interactive conversations with the AI agent.

### Starting the Streamlit App

First, ensure the FastAPI server is running (see API Server section above), then:

```bash
streamlit run app/streamlit_app.py
```

The app will be available at `http://localhost:8501` (default Streamlit port).

### Features

- **Interactive Chat Interface**: Real-time conversation with the AI agent
- **Thread Management**: Create new threads or continue existing conversations
- **Real-time Streaming**: See responses stream in real-time as they are generated
- **Module Interrupts**: Handle interactive prompts from specialized module agents
- **Server Configuration**: Configure and check server connection status
- **Debug Mode**: Option to view system messages for debugging

The Streamlit app connects to the FastAPI server running on `http://localhost:8000` by default. You can change the server URL in the sidebar configuration.

## Direct Usage

### Basic Supervisor Usage

For direct usage without the API server:

```python
import asyncio
from vitess_ai.server_agents.server_supervisor import create_default_server_supervisor

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

## Configuration

Create `.env` file:
```env
# LLM Provider
DEFAULT_PROVIDER=anthropic
DEFAULT_MODEL=claude-3-5-sonnet-20241022

# API Keys
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here

# Server
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
```

## Available Agents

- **SupervisorAgent**: Orchestrates the entire simulation workflow
- **ReadInAgent**: Configures neutron input parameters and initial conditions
- **GuideAgent**: Handles neutron guide specifications and geometry
- **WriteoutAgent**: Manages output settings and data formats

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
│   ├── streamlit_app.py    # Streamlit web interface
│   └── assets/
│       └── logo.png
├── src/vitess_ai/
│   ├── agents/             # AI Agent implementations
│   ├── clients/            # API client library
│   ├── server/             # API Server (FastAPI)
│   ├── server_agents/      # Server-optimized agents
│   ├── mcp/                # MCP validation tools
│   ├── schema/             # Pydantic schemas
│   └── core/              # Core utilities
├── main.py                 # Server entry point
└── pyproject.toml
```

## Contributing

Areas for contribution:
- **New Module Agents**: Add support for additional VITESS simulation modules
- **API Enhancements**: Improve server performance and add new endpoints
- **Client Libraries**: Develop client libraries for different languages
- **Documentation**: Improve guides and examples
- **Testing**: Add test coverage for agents and API endpoints

## License

MIT License - Copyright © 2025
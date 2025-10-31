# VITESS AI Agent 🤖

**VITESS AI Agent** is part of **Jülich Neutron AI Agents (JüNA)**, an agentic AI system designed to assist researchers in accessing and utilizing JCNS's extensive knowledge base in neutron science. This specific agent focuses on [VITESS](https://vitess.fz-juelich.de), an open-source software package for simulating neutron scattering experiments.

## ✨ Key Features

- **Multi-Agent Architecture**: Specialized AI agents for different simulation modules
- **RESTful API Server**: FastAPI-based server for programmatic access
- **Real-time Streaming**: Server-Sent Events (SSE) for live conversation streaming
- **Automated Configuration**: Guide users through neutron simulation parameters
- **CLI Generation**: Automatic generation of VITESS command-line parameters
- **Interrupt Handling**: Support for interactive agent interruptions and resumption

## 📋 Prerequisites

### VITESS Software Installation
**Critical Requirement**: You must have [VITESS](https://vitess.fz-juelich.de) installed on your system.

- Install VITESS following the official documentation
- Ensure `vitess` command is available in your system PATH

### System Requirements
- Python 3.13+
- Compatible with Windows, macOS, and Linux

## 🏗️ Architecture

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

## 🔧 Installation

### Using uv (Recommended)
```bash
uv pip install -r requirements.txt
# or
uv pip install .
```

### Using pip
```bash
pip install -r requirements.txt
# or
pip install .
```

## 🌐 API Server

### Starting the Server
```bash
python main.py
```
Server runs on `http://localhost:8000` with auto-reload and interactive docs at `/docs`.

### API Endpoints

**POST `/invoke`** - Send message and get complete response
```bash
curl -X POST "http://localhost:8000/invoke" \
  -H "Content-Type: application/json" \
  -d '{"message": "Configure a neutron simulation", "thread_id": "sim_001"}'
```

**POST `/stream`** - Real-time streaming response
```bash
curl -X POST "http://localhost:8000/stream" \
  -H "Content-Type: application/json" \
  -d '{"message": "Start simulation", "thread_id": "sim_002"}'
```

**GET `/health`** - Health check
```bash
curl -X GET "http://localhost:8000/health"
```

### Python Usage
```python
import requests

# Simple invoke
response = requests.post(
    "http://localhost:8000/invoke",
    json={"message": "Configure neutron beam", "thread_id": "thread_123"}
)
print(response.json()["content"])

# Streaming (async)
import asyncio
import aiohttp

async def stream_response():
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "http://localhost:8000/stream",
            json={"message": "Run simulation", "thread_id": "workflow_001"}
        ) as response:
            async for line in response.content:
                if line.startswith(b'data: '):
                    data = line[6:].decode('utf-8').strip()
                    if data != '[DONE]':
                        print(data)
```

## 🚀 Direct Usage

### Basic Supervisor Usage
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

## ⚙️ Configuration

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

## 🤖 Available Agents

- **SupervisorAgent**: Orchestrates the entire simulation workflow
- **ReadInAgent**: Configures neutron input parameters and initial conditions
- **GuideAgent**: Handles neutron guide specifications and geometry
- **WriteoutAgent**: Manages output settings and data formats

## 🚀 Production Deployment

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
RUN pip install -r requirements.txt
EXPOSE 8000
CMD ["python", "main.py"]
```

## 📂 Project Structure

```
vitess-ai-agent/
├── src/vitess_ai/
│   ├── agents/           # AI Agent implementations
│   ├── server/           # API Server (FastAPI)
│   ├── server_agents/    # Server-optimized agents
│   ├── mcp/              # MCP validation tools
│   ├── schema/           # Pydantic schemas
│   └── core/             # Core utilities
├── main.py               # Server entry point
└── pyproject.toml
```

## 🤝 Contributing

Areas for contribution:
- **New Module Agents**: Add support for additional VITESS simulation modules
- **API Enhancements**: Improve server performance and add new endpoints
- **Client Libraries**: Develop client libraries for different languages
- **Documentation**: Improve guides and examples
- **Testing**: Add test coverage for agents and API endpoints

## 📄 License

MIT License - Copyright © 2025
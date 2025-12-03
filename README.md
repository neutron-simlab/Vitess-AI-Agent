# VITESS AI Agent

<div align="center">
  <img src="app/assets/logo.png" alt="VITESS AI Agent Logo" width="200"/>
</div>

**VITESS AI Agent** helps researchers work with [VITESS](https://vitess.fz-juelich.de), a software package for simulating neutron scattering experiments. It's part of the **Jülich Neutron AI Agents (JüNA)** project.

## What It Does

- **AI-Powered Assistance**: Chat with AI agents to configure and run VITESS simulations
- **Web Interface**: Easy-to-use chat interface in your browser
- **Multiple AI Models**: Works with OpenAI or Blablador
- **File Management**: Upload and manage simulation files
- **Real-time Responses**: See AI responses as they're generated

## Requirements

- Python 3.13 or higher
- [VITESS](https://vitess.fz-juelich.de) installed on your system
- An API key from OpenAI or Blablador

## Quick Setup

### 1. Install Dependencies

**Install uv (package manager):**
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Install project:**
```bash
uv sync
```

### 2. Configure API Keys

Copy the example environment file and add your API key:

```bash
cp env.example .env
```

Then edit `.env` and add your `OPENAI_API_KEY` or `BLABLADOR_API_KEY`.

### 3. Start the Application

**Start the API server:**
```bash
python main.py
```
API runs at `http://localhost:8000`

**Start the web interface (in another terminal):**
```bash
streamlit run app/streamlit_app.py
```
Web interface runs at `http://localhost:8501`

## Using the Application

### Web Interface

Open `http://localhost:8501` in your browser to start chatting with the AI agents. You can:
- Ask questions about VITESS configuration
- Upload simulation files
- Get help with neutron scattering experiments

### API Usage

You can also use the API programmatically. See the interactive documentation at `http://localhost:8000/docs` for all available endpoints.

**Example Python code:**
```python
from vitess_ai.clients.client import AgentClient

client = AgentClient(base_url="http://localhost:8000", agent="supervisor")
response = client.invoke(
    message="Help me configure a neutron beam",
    thread_id="my-thread"
)
print(response.content)
```

## Available Agents

- **Supervisor**: Coordinates the entire simulation workflow
- **ReadIn**: Sets up input parameters
- **Guide**: Configures neutron guides
- **Writeout**: Manages output settings
- **Monitor**: Creates plots and visualizations

## Production Deployment

For production, we use Docker and deploy to Digital Ocean with automated CI/CD.

**Quick setup:**
1. Set up GitHub Secrets with your API keys and server details
2. Push to `main` branch - deployment happens automatically
3. See [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) for detailed instructions

**Manual deployment:**
```bash
# On your server
cd /opt/vitess-ai
docker-compose up -d
```

## Project Structure

```
vitess-ai-agent/
├── app/              # Web interface
├── src/vitess_ai/
│   ├── clients/            # API client library
│   ├── server/             # FastAPI server and endpoints
│   │   └── streaming/      # Streaming event processors
│   ├── server_agents/      # Server-optimized agents
│   ├── mcp/                # MCP validation tools
│   ├── prompts/            # Agent prompts
│   ├── schema/             # Pydantic schemas
│   └── core/               # Core utilities
├── main.py           # API server entry point
└── scripts/          # Deployment scripts
```

## Contributing

We welcome contributions! Areas where help is needed:
- New VITESS module agents
- Documentation improvements
- Additional AI model support
- Bug fixes and enhancements

## License

MIT License - Copyright © 2025

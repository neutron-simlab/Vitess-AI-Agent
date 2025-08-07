# VITESS AI Agent 🤖

**VITESS AI Agent** is part of **Jülich Neutron AI Agents (JüNA)**, an agentic AI system designed to assist researchers in accessing and utilizing JCNS's (Jülich Centre for Neutron Science at Forschungszentrum Jülich) extensive knowledge base in neutron science. This specific agent focuses on [VITESS](https://vitess.fz-juelich.de), an open-source software package for simulating neutron scattering experiments. The system uses conversational AI to guide users through complex neutron simulation configurations and automate the entire simulation workflow.

---

## ✨ Key Features

- **Multi-Agent Architecture**: Specialized AI agents for different simulation modules
- **Conversational Interface**: LangGraph-based conversational AI (FastHTML UI in development)
- **Automated Configuration**: Guide users through neutron simulation parameters
- **Parameter Validation**: Built-in validation using MCP (Model Context Protocol) tools
- **CLI Generation**: Automatic generation of VITESS command-line parameters
- **Plug-and-Play Modules**: Easy addition of custom simulation modules
- **Simulation Execution**: Direct VITESS simulation orchestration and execution

---

## 📋 Prerequisites

### VITESS Software Installation
**Critical Requirement**: You must have [VITESS](https://vitess.fz-juelich.de) installed on your system before using this project.

- Install VITESS following the official documentation
- Ensure `vitess` command is available in your system PATH

### System Requirements
- Python 3.13+
- Compatible with Windows, macOS, and Linux

---

## 🏗️ Architecture Overview

The VITESS AI Agent uses a sophisticated multi-agent architecture:

```
┌─────────────────┐    ┌──────────────────┐    ┌────────────────┐
│  SupervisorAgent│────│  BaseModuleAgent │────│ Specialized    │
│  (Orchestrator) │    │  (Abstract Base) │    │ Module Agents  │
└─────────────────┘    └──────────────────┘    └────────────────┘
         │                        │                       │
         │              ┌─────────┼─────────┐            │
         │              │         │         │            │
         ▼              ▼         ▼         ▼            ▼
┌─────────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐
│ Simulation  │ │ ReadIn   │ │ Guide   │ │ Writeout │ │ Filter   │
│ Execution   │ │ Agent    │ │ Agent   │ │ Agent    │ │ Agent    │
└─────────────┘ └──────────┘ └─────────┘ └──────────┘ └──────────┘
```

**Key Components:**
- **LangGraph**: Manages conversational flows and agent state
- **MCP Tools**: Provides parameter validation and CLI generation
- **Memory System**: Maintains conversation context across interactions
- **Module Registry**: Dynamic registration and management of simulation modules

---

## 🤖 Available Module Agents

### Core Simulation Modules

#### **ReadInAgent**
Configures neutron input parameters and initial simulation conditions:
- Neutron beam specifications
- Source parameters and geometry
- Input file configurations
- Initial conditions and boundary settings

#### **GuideAgent** 
Handles neutron guide specifications and geometry:
- Guide dimensions (width, height, length)
- Reflectivity parameters (m-value)
- Guide geometry and curvature
- Surface properties and specifications

#### **WriteoutAgent**
Manages output settings and data formats:
- Output directory and file specifications
- Data format preferences (HDF5, ASCII, binary)
- Neutron detection and recording settings
- Post-processing and analysis options

#### **FilterAgent**
Configures neutron filter parameters:
- Filter dimensions and positioning
- Transmission properties
- Multi-filter configurations

#### **SupervisorAgent**
Orchestrates the entire simulation workflow:
- Module execution coordination
- Parameter validation across modules
- CLI command generation
- VITESS simulation execution
- Result collection and analysis

---

## 🔧 Installation

### Using [uv](https://pypi.org/project/uv/) (Recommended)

Install dependencies using **uv** for faster performance:

```bash
uv pip install -r requirements.txt
```

Or install the package directly:

```bash
uv pip install .
```

### Using pip

Alternatively, use standard pip:

```bash
pip install -r requirements.txt
```

Or install locally:

```bash
pip install .
```

---

## 🚀 Usage Examples

### Basic Supervisor Usage

Run the complete simulation workflow with default modules:

```python
import asyncio
from vitess_ai.agents.supervisor_agent import create_default_supervisor

async def main():
    # Create supervisor with default modules (readin, guide, writeout)
    supervisor = await create_default_supervisor()
    
    # Run complete simulation configuration and execution
    result = await supervisor.run("simulation_001")
    
    print("Simulation Results:")
    print(f"Status: {result['status']}")
    print(f"Completed Modules: {result['completed_modules']}")
    print(f"CLI Command: {result.get('cli_command')}")

asyncio.run(main())
```

### Individual Agent Usage

Use specific agents independently:

```python
import asyncio
from vitess_ai.agents.readin_module_agent import create_readin_agent

async def main():
    # Create and use ReadIn agent
    readin_agent = await create_readin_agent()
    result = await readin_agent.run("Configure neutron beam parameters", "thread_1")
    
    print("ReadIn Parameters:", result)

asyncio.run(main())
```

### Configuration Modes

Each agent supports two configuration modes:

- **Default Setup**: Uses optimal default values, minimal user input required
- **Customize**: Step-by-step configuration of all parameters

```python
# Example interaction:
# Agent: "Choose your configuration mode: Default Setup or Customize?"
# User: "Default Setup"  # Quick configuration with defaults
# User: "Customize"      # Full parameter customization
```

---

## ➕ Adding New Modules

The system supports plug-and-play module development using the `BaseModuleAgent` architecture.

### Step 1: Create Your Module Agent

```python
from typing import List
from langchain.tools import BaseTool
from vitess_ai.agents.base_module_agent import BaseModuleAgent
from vitess_ai.schema.your_module import InitialResponseYourModule

class YourModuleAgent(BaseModuleAgent[InitialResponseYourModule]):
    """Your custom module agent"""
    
    def __init__(self, provider: str, model: str, tools: List[BaseTool] = []):
        super().__init__(provider, model, tools)
    
    # Required abstract methods
    @property
    def name(self) -> str:
        return "Your Module Agent"
    
    @property  
    def module_name(self) -> str:
        return "your_module"
    
    @property
    def welcome_message(self) -> str:
        return "Welcome to your custom module configuration!"
    
    @property
    def system_prompt(self) -> str:
        return "You are a helpful agent for configuring custom parameters."
    
    def get_initial_response_schema(self):
        return InitialResponseYourModule
    
    def get_result_key(self) -> str:
        return "your_module_params"
```

### Step 2: Create Schema and Prompts

```python
# your_module_schema.py
from pydantic import BaseModel

class InitialResponseYourModule(BaseModel):
    response: str  # User's configuration choice
```

### Step 3: Register with Supervisor

```python
from vitess_ai.agents.supervisor_agent import SupervisorAgent
from vitess_ai.agents.base_module_agent import ModuleBuilder

# Create supervisor
supervisor = SupervisorAgent()

# Add your custom module
supervisor.add_custom_module(
    name="your_module",
    display_name="Your Custom Module", 
    description="Description of what your module does",
    agent_class=YourModuleAgent,
    order=4,  # Execution order
    config_path="path/to/your/mcp/tools.py",  # Optional MCP tools
    optional=False  # Required or optional module
)

# Initialize and run
await supervisor.initialize()
result = await supervisor.run()
```

### Step 4: MCP Tools (Optional)

Create validation tools for your module:

```python
# your_mcp_tools.py
from langchain_mcp_adapters.server import create_server_tool

@create_server_tool
def validate_your_parameters(parameters: dict) -> dict:
    """Validate your module parameters"""
    # Your validation logic
    return {
        "validation_status": True,
        "validated_params": parameters,
        "cli_parameters": "--your-param value"
    }
```

---

## 🛠️ Development Guide

### BaseModuleAgent Architecture

All module agents inherit from `BaseModuleAgent` which provides:

- **Standardized Graph Structure**: LangGraph nodes and routing
- **Memory Management**: Conversation persistence across sessions
- **Tool Integration**: Automatic MCP tools binding
- **Logging System**: Comprehensive logging for debugging
- **Error Handling**: Robust error management and recovery

### Required Methods

When creating custom agents, implement these abstract methods:

```python
@property
def name(self) -> str: 
    """Human-readable agent name"""

@property  
def module_name(self) -> str:
    """Unique module identifier (lowercase, no spaces)"""

@property
def welcome_message(self) -> str:
    """Initial message shown to users"""

@property
def system_prompt(self) -> str:
    """LLM system prompt for the module"""

def get_initial_response_schema(self):
    """Pydantic schema for parsing user responses"""

def get_result_key(self) -> str:
    """Key for storing module results"""
```

### Optional Customizations

Override these methods for custom behavior:

```python
def get_default_setup_message(self) -> str:
    """Message for default configuration mode"""

def get_customize_setup_message(self) -> str:  
    """Message for customize configuration mode"""

def get_completion_message(self) -> str:
    """Message shown on successful completion"""

def validate_config_mode(self, config_mode: str) -> bool:
    """Custom validation for configuration modes"""
```

---

## 📂 Project Structure

```
vitess-ai-agent/
├── src/
│   └── vitess_ai/
│       ├── __init__.py
│       ├── agents/                    # AI Agent implementations
│       │   ├── __init__.py
│       │   ├── base_module_agent.py   # Abstract base class
│       │   ├── supervisor_agent.py    # Main orchestrator
│       │   ├── readin_module_agent.py # Neutron input parameters
│       │   ├── guide_module_agent.py  # Guide specifications
│       │   ├── writeout_module_agent.py # Output configuration
│       │   └── filter_module_agent.py # Filter parameters
│       ├── core/                      # Core utilities
│       │   ├── __init__.py
│       │   ├── config.py             # Global configuration
│       │   ├── logging.py            # Logging setup
│       │   ├── llms_providers.py     # LLM provider management
│       │   └── registry.py           # Module registry system
│       ├── mcp_tools/                # MCP validation tools
│       │   ├── __init__.py
│       │   ├── supervisor_mcp_tools.py
│       │   ├── readin_mcp_tools.py
│       │   ├── guide_mcp_tools.py
│       │   └── writeout_mcp_tools.py
│       ├── prompts/                  # Agent prompts
│       │   ├── __init__.py
│       │   ├── readin_module.py
│       │   ├── guide_module.py
│       │   ├── writeout_module.py
│       │   └── filter_module.py
│       └── schema/                   # Pydantic schemas
│           ├── __init__.py
│           ├── base.py              # Base schemas
│           ├── supervisor_modules.py # Supervisor schemas
│           ├── readin_module.py     # ReadIn schemas
│           ├── guide_module.py      # Guide schemas
│           ├── writeout_module.py   # Writeout schemas
│           └── filter_module.py     # Filter schemas
├── tests/                           # Test suite
├── .env.example                     # Environment template
├── .gitignore
├── .python-version
├── pyproject.toml
├── README.md
├── uv.lock
└── LICENSE
```

---

## ⚙️ Configuration

### Environment Setup

The project uses environment variables for configuration. Copy the example file and customize:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# LLM Provider Configuration
DEFAULT_PROVIDER=anthropic  # or openai, ollama, etc.
DEFAULT_MODEL=claude-3-5-sonnet-20241022

# API Keys (add as needed)
ANTHROPIC_API_KEY=your_anthropic_key_here
OPENAI_API_KEY=your_openai_key_here

# MCP Tools Paths
READIN_MCP_PATH=src/vitess_ai/mcp_tools/readin_mcp_tools.py
GUIDE_MCP_PATH=src/vitess_ai/mcp_tools/guide_mcp_tools.py  
WRITEOUT_MCP_PATH=src/vitess_ai/mcp_tools/writeout_mcp_tools.py
FILTER_MCP_PATH=src/vitess_ai/mcp_tools/filter_mcp_tools.py
SUPERVISOR_MCP_PATH=src/vitess_ai/mcp_tools/supervisor_mcp_tools.py

# Logging Configuration
LOG_LEVEL=INFO
```

### Supported LLM Providers

- **Anthropic**: Claude models (recommended)
- **OpenAI**: GPT models (recommended)
- **Ollama**: Local models
- **Blablador**: Extensible through LangChain

---

## 🤝 Contributing

Contributions are welcome! Areas for contribution:

- **New Module Agents**: Add support for additional VITESS simulation modules
- **UI Development**: Help develop the Streamlit interface
- **Documentation**: Improve guides and examples
- **Testing**: Add test coverage for agents and workflows
- **Performance**: Optimize conversation flows and memory usage

Please open an issue to discuss ideas, report bugs, or suggest improvements.

---

## 📄 License

The code is licensed under the [MIT license](./LICENSE). Copyright © 2025.

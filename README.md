# Vitess AI Agent 🚧

> **⚠️ Work in Progress**  
> This project is under active development and not yet ready for production use.

**Vitess AI Agent** is an intelligent assistant for [Vitess](https://vitess.fz-juelich.de), an open-source software package for simulating neutron scattering experiments. It aims to help users **run simulations** and **analyze results** more easily through AI-driven tools and conversational interfaces.

---

## ✨ Goals

- Run Vitess simulations from a conversational interface
- Summarize and visualize simulation results
- Help users set up Vitess input files
- Automate repetitive simulation tasks
- Lower the barrier for researchers working with neutron scattering simulations

---

## 🚧 Project Status

This project is currently in early development and includes:

- Basic project structure
- Initial integration for running Vitess processes
- Early experiments with parsing simulation outputs
- Placeholder modules for analysis and plotting

Functionality is incomplete and under active development.

---

## 🔧 Installation

### Using [uv](https://pypi.org/project/uv/) (Recommended)

Install dependencies using **uv** for faster performance:

```bash
uv pip install -r requirements.txt
```
Or install the package directly via `pyproject.toml`:

```bash
uv pip install .
```

### Using pip

Alternatively, you can use classic pip:

```bash
pip install -r requirements.txt
```
Or install the package locally:
```bash
pip install .
```

## 🚀 Usage
>  **⚠️ Work in Progress** 

## 📂 Project Structure
```
vitess-ai-agent/
├── src/
│   └── vitess_ai/
│       ├── __init__.py
│       ├── agents/
│       │   ├── __init__.py
│       │   └── filter_module_agent.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py
│       │   └── logging.py
│       ├── mcp/
│       │   ├── __init__.py
│       │   └── validation_server.py
│       ├── prompts/
│       │   ├── __pycache__/
│       │   └── filter_module.py
│       └── schema/
│           ├── __pycache__/
│           ├── __init__.py
│           └── filter_module.py
├── tests/                     # Test suite
├── .gitignore
├── .python-version
├── .env.example
├── main.py
├── pyproject.toml
├── README.md
├── uv.lock
├── LICENSE
```

## 🤝 Contributing
Contributions are welcome! Please open an issue to discuss ideas, report bugs, or suggest improvements.

## License
The code is licensed under the [MIT license](./LICENSE). Copyright © 2025.

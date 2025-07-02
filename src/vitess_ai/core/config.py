from pydantic_settings import BaseSettings
from pathlib import Path
from typing import Optional

class Settings(BaseSettings):
    """Application settings."""
    
    # App settings
    app_name: str = "Vitess AI Chatbot"
    debug: bool = False
    log_level: str = "INFO"
    
    # MCP settings
    mcp_server_timeout: int = 30
    validation_server_path: str = "src/vitess_ai/mcp/validation_server.py"
    
    # File paths
    config_output_dir: Path = Path("configs")
    logs_dir: Path = Path("logs")
    
    # LLM settings
    llm_provider: str =  "openai"
    llm_model: str = "gpt-4o-mini-2024-07-18"
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# Global settings instance
settings = Settings()
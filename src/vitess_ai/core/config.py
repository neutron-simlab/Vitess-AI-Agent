import os
from dotenv import load_dotenv

# Load environment variables from .env file
path_env = os.getenv("VITESS_ENV_PATH")
load_dotenv(path_env)

class Config:
    """Essential configuration for Vitess AI Agent project"""
    
    # =============================================================================
    # REQUIRED SETTINGS
    # =============================================================================
    
    # OpenAI API Key (required)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    
    # =============================================================================
    # LANGSMITH SETTINGS (Optional but recommended)
    # =============================================================================
    
    # LangSmith tracing configuration
    LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
    LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT")
    LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
    LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT")
    
    # =============================================================================
    # LLM PROVIDER CONFIGURATION
    # =============================================================================
    
    # Provider selection
    DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "blablador")
    FALLBACK_PROVIDER = os.getenv("FALLBACK_PROVIDER", "openai")
    
    # Default model (uses provider-specific default if not set)
    # For Blablador: alias-function-call, alias-code (only models with function calling support)
    # For OpenAI: gpt-4o-mini, gpt-4o, etc.
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", os.getenv("BLABLADOR_DEFAULT_MODEL", "alias-function-call"))
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "10000"))
    TIMEOUT_SECONDS = int(os.getenv("TIMEOUT_SECONDS", "60"))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    
    # Blablador (OpenAI-compatible API)
    BLABLADOR_API_KEY = os.getenv("BLABLADOR_API_KEY")
    BLABLADOR_BASE_URL = os.getenv("BLABLADOR_BASE_URL")
    BLABLADOR_DEFAULT_MODEL = os.getenv("BLABLADOR_DEFAULT_MODEL")
    
    
    # =============================================================================
    # MCP TOOL PATHS
    # =============================================================================
    
    # MCP tool paths for different modules (with defaults)
    READIN_MCP_PATH = os.getenv("READIN_MCP_PATH", "src/vitess_ai/mcp/readin_module_tools.py")
    GUIDE_MCP_PATH = os.getenv("GUIDE_MCP_PATH", "src/vitess_ai/mcp/guide_module_tools.py")
    WRITEOUT_MCP_PATH = os.getenv("WRITEOUT_MCP_PATH", "src/vitess_ai/mcp/writeout_module_tools.py")
    MONITOR_MCP_PATH = os.getenv("MONITOR_MCP_PATH", "src/vitess_ai/mcp/monitor_module_tools.py")
    # Supervisor CLI tools path
    SUPERVISOR_MCP_PATH = os.getenv("SUPERVISOR_MCP_PATH", "src/vitess_ai/mcp/supervisor_tools.py")
    
    # =============================================================================
    # MCP TRANSPORT CONFIGURATION
    # =============================================================================
    
    # Transport mode: "stdio" for development, "http" for production
    MCP_TRANSPORT_MODE = os.getenv("MCP_TRANSPORT_MODE", "http").lower()
    
    # MCP server host (for client connections, use "localhost" in Docker, "127.0.0.1" for local)
    MCP_HOST = os.getenv("MCP_HOST", "localhost")
    
    # MCP server ports (defaults match the ports configured in server files)
    MCP_READIN_PORT = int(os.getenv("MCP_READIN_PORT", "9001"))
    MCP_GUIDE_PORT = int(os.getenv("MCP_GUIDE_PORT", "9002"))
    MCP_WRITEOUT_PORT = int(os.getenv("MCP_WRITEOUT_PORT", "9003"))
    MCP_MONITOR_PORT = int(os.getenv("MCP_MONITOR_PORT", "9004"))
    MCP_SUPERVISOR_PORT = int(os.getenv("MCP_SUPERVISOR_PORT", "9005"))
    
    # MCP server URLs (constructed from host and ports)
    @classmethod
    def get_mcp_url(cls, module_name: str) -> str:
        """Get MCP server URL for a module"""
        port_map = {
            "readin": cls.MCP_READIN_PORT,
            "guide": cls.MCP_GUIDE_PORT,
            "writeout": cls.MCP_WRITEOUT_PORT,
            "monitor1d": cls.MCP_MONITOR_PORT,
            "monitor2d": cls.MCP_MONITOR_PORT,
            "supervisor": cls.MCP_SUPERVISOR_PORT,
        }
        
        port = port_map.get(module_name)
        if port is None:
            raise ValueError(f"No MCP port configured for module: {module_name}")
        
        # Allow override via environment variable
        url_env_key = f"MCP_{module_name.upper()}_URL"
        url_override = os.getenv(url_env_key)
        if url_override:
            return url_override
        
        # FastMCP HTTP servers use /mcp as the endpoint path
        return f"http://{cls.MCP_HOST}:{port}/mcp"
    
    # =============================================================================
    # VITESS SIMULATION ENVIRONMENT
    # =============================================================================
    
    # Default Vitess environment variables (from your script)
    # These can be updated at runtime via update_vitess_config()
    VITESS_MODULES_PATH = os.getenv("VITESS_MODULES_PATH", "/usr/local/vitess/bin")
    VITESS_PROJECT_PATH = os.getenv("VITESS_PROJECT_PATH", "/tmp/vitess_project")
    VITESS_LOG_PATH = os.getenv("VITESS_LOG_PATH", "/tmp/vitess_logs")
    
    @classmethod
    def update_vitess_config(
        cls,
        modules_path: str | None = None,
        project_path: str | None = None,
        log_path: str | None = None
    ) -> dict[str, str]:
        """
        Update Vitess environment configuration at runtime.
        
        Args:
            modules_path: New path for Vitess modules (V)
            project_path: New path for Vitess project (P)
            log_path: New path for Vitess logs (L)
            
        Returns:
            Dictionary with updated Vitess environment variables
        """
        if modules_path is not None:
            cls.VITESS_MODULES_PATH = modules_path
        if project_path is not None:
            cls.VITESS_PROJECT_PATH = project_path
        if log_path is not None:
            cls.VITESS_LOG_PATH = log_path
        
        return cls.get_vitess_variables()
    
    @classmethod
    def reset_vitess_config(cls) -> dict[str, str]:
        """
        Reset Vitess environment configuration to defaults from environment variables.
        
        Returns:
            Dictionary with reset Vitess environment variables
        """
        cls.VITESS_MODULES_PATH = os.getenv("VITESS_MODULES_PATH", "/usr/local/vitess/bin")
        cls.VITESS_PROJECT_PATH = os.getenv("VITESS_PROJECT_PATH", "/tmp/vitess_project")
        cls.VITESS_LOG_PATH = os.getenv("VITESS_LOG_PATH", "/tmp/vitess_logs")
        
        return cls.get_vitess_variables()
    
    # =============================================================================
    # FILE UPLOAD CONFIGURATION
    # =============================================================================
    
    # Note: File storage structure is now organized by thread_id:
    # - {VITESS_PROJECT_PATH}/{thread_id}/uploads/{module_type}/  - Input files
    # - {VITESS_PROJECT_PATH}/{thread_id}/outputs/                 - Output files
    # UPLOAD_DIR is no longer used as files are organized under thread_id directories
    
    # Maximum file size in bytes (default: 100MB)
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "104857600"))
    
    # Allowed file types/extensions
    ALLOWED_FILE_EXTENSIONS = os.getenv(
        "ALLOWED_FILE_EXTENSIONS", 
        ".dat,.txt,.csv,.nxs,.h5,.inf,.out"
    ).split(",")
    
    # =============================================================================
    # ENVIRONMENT
    # =============================================================================
    
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    @classmethod
    def validate_required(cls):
        """Validate that required environment variables are set"""
        errors = []
        
        # Validate based on default provider
        if cls.DEFAULT_PROVIDER.lower() == "blablador":
            if not cls.BLABLADOR_API_KEY:
                errors.append("BLABLADOR_API_KEY is required when using Blablador as default provider")
            if not cls.BLABLADOR_BASE_URL:
                errors.append("BLABLADOR_BASE_URL is required when using Blablador as default provider")
        elif cls.DEFAULT_PROVIDER.lower() == "openai":
            if not cls.OPENAI_API_KEY:
                errors.append("OPENAI_API_KEY is required when using OpenAI as default provider")
        else:
            # For unknown providers, at least check for OpenAI as fallback
            if not cls.OPENAI_API_KEY and not (cls.BLABLADOR_API_KEY and cls.BLABLADOR_BASE_URL):
                errors.append("Either OPENAI_API_KEY or (BLABLADOR_API_KEY and BLABLADOR_BASE_URL) must be configured")
        
        if cls.LANGSMITH_TRACING and not cls.LANGSMITH_API_KEY:
            errors.append("LANGSMITH_API_KEY is required when LANGSMITH_TRACING is enabled")
        
        if errors:
            raise ValueError(f"Missing required environment variables: {', '.join(errors)}")
    
    
    @classmethod
    def setup_langsmith(cls):
        """Setup LangSmith tracing if enabled"""
        if cls.LANGSMITH_TRACING and cls.LANGSMITH_API_KEY:
            os.environ["LANGSMITH_TRACING_V2"] = "true"
            os.environ["LANGSMITH_ENDPOINT"] = cls.LANGSMITH_ENDPOINT
            os.environ["LANGSMITH_API_KEY"] = cls.LANGSMITH_API_KEY
            os.environ["LANGSMITH_PROJECT"] = cls.LANGSMITH_PROJECT
            return True
        return False
    
    @classmethod
    def get_mcp_path(cls, module_name: str) -> str:
        """Get MCP tool path for a module"""
        path_map = {
            "readin": cls.READIN_MCP_PATH,
            "guide": cls.GUIDE_MCP_PATH,
            "writeout": cls.WRITEOUT_MCP_PATH,
            "monitor1d": cls.MONITOR_MCP_PATH,
            "monitor2d": cls.MONITOR_MCP_PATH,
            "supervisor": cls.SUPERVISOR_MCP_PATH
        }
        
        path = path_map.get(module_name)
        if not path:
            raise ValueError(f"No MCP path configured for module: {module_name}")
        
        return path
    
    @classmethod
    def is_mcp_http_mode(cls) -> bool:
        """Check if MCP is configured to use HTTP transport"""
        return cls.MCP_TRANSPORT_MODE == "http"
    
    @classmethod
    def get_vitess_variables(cls) -> dict:
        """Get default Vitess environment variables"""
        return {
            "V": cls.VITESS_MODULES_PATH,
            "P": cls.VITESS_PROJECT_PATH, 
            "L": cls.VITESS_LOG_PATH
        }
    
    
    @classmethod
    def initialize(cls):
        """Initialize configuration - call once at startup"""
        cls.validate_required()
        langsmith_enabled = cls.setup_langsmith()
        
        print(f"✅ Configuration initialized")
        print(f"✅ Environment: {cls.ENVIRONMENT}")
        print(f"✅ LangSmith: {'enabled' if langsmith_enabled else 'disabled'}")
        print(f"✅ Vitess Modules: {cls.VITESS_MODULES_PATH}")
        print(f"✅ Vitess Project: {cls.VITESS_PROJECT_PATH}")
        
        return cls

# Initialize configuration on import
global_config = Config.initialize()
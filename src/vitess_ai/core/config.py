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
    DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER")
    FALLBACK_PROVIDER = os.getenv("FALLBACK_PROVIDER")
    
    # OpenAI
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL")
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4000"))
    TIMEOUT_SECONDS = int(os.getenv("TIMEOUT_SECONDS", "60"))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    
    # Blablador (OpenAI-compatible API)
    BLABLADOR_API_KEY = os.getenv("BLABLADOR_API_KEY")
    BLABLADOR_BASE_URL = os.getenv("BLABLADOR_BASE_URL")
    BLABLADOR_DEFAULT_MODEL = os.getenv("BLABLADOR_DEFAULT_MODEL")
    
    
    # =============================================================================
    # MCP TOOL PATHS
    # =============================================================================
    
    # MCP tool paths for different modules
    READIN_MCP_PATH = os.getenv("READIN_MCP_PATH")
    GUIDE_MCP_PATH = os.getenv("GUIDE_MCP_PATH") 
    WRITEOUT_MCP_PATH = os.getenv("WRITEOUT_MCP_PATH")
    FILTER_MCP_PATH = os.getenv("FILTER_MCP_PATH")
    # Supervisor CLI tools path
    SUPERVISOR_MCP_PATH = os.getenv("SUPERVISOR_MCP_PATH")
    
    # =============================================================================
    # VITESS SIMULATION ENVIRONMENT
    # =============================================================================
    
    # Default Vitess environment variables (from your script)
    VITESS_MODULES_PATH = os.getenv("VITESS_MODULES_PATH")
    VITESS_PROJECT_PATH = os.getenv("VITESS_PROJECT_PATH")
    VITESS_LOG_PATH = os.getenv("VITESS_LOG_PATH")
    
    # =============================================================================
    # ENVIRONMENT
    # =============================================================================
    
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    @classmethod
    def validate_required(cls):
        """Validate that required environment variables are set"""
        errors = []
        
        if not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY is required")
        
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
            "supervisor": cls.SUPERVISOR_CLI_MCP_PATH
        }
        
        path = path_map.get(module_name)
        if not path:
            raise ValueError(f"No MCP path configured for module: {module_name}")
        
        return path
    
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
"""
Base Module Agent - Base class for module agents

This class provides the foundation for agents that use react-agent
architecture with unified state management. Module agents are created
as react-agents using LangChain's create_agent and integrated
into the supervisor graph as nodes.
"""

from typing import List, Type, Optional, Any
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from langchain.tools import BaseTool
from langchain.agents import create_agent
from vitess_ai.core.llms_providers import create_llm_with_fallback
from vitess_ai.core.log import get_logger


class ModuleMetadata(BaseModel):
    """Definition of a registerable module"""
    name: str = Field(..., description="Module name (e.g., 'readin')")
    display_name: str = Field(..., description="Human-readable name (e.g., 'Read-in Parameters')")
    description: str = Field(..., description="Module description")
    agent_class: Type[Any] = Field(..., description="Agent class for this module (BaseModuleAgent)")
    optional: bool = Field(default=False, description="Whether module can be skipped")
    config_path: Optional[str] = Field(None, description="Path to MCP tools configuration")
    order: int = Field(default=100, description="Execution order (1, 2, 3, etc.)")
    
    class Config:
        arbitrary_types_allowed = True


class ModuleBuilder:
    """Simple helper to create module definitions"""
    
    @staticmethod
    def create(
        name: str,
        display_name: str, 
        description: str,
        agent_class: Type[Any],
        config_path: str = None,
        optional: bool = False,
        order: int = 100
    ) -> ModuleMetadata:
        """
        Create a module definition - that's it!
        
        Args:
            name: Short name like "readin", "guide"
            display_name: Pretty name like "Read-in Parameters"  
            description: What this module does
            agent_class: Your agent class (inherits BaseModuleAgent)
            config_path: Path to MCP tools (optional)
            optional: Can user skip this? (default False)
            order: Execution order - 1, 2, 3, etc. (default 100)
        """
        return ModuleMetadata(
            name=name,
            display_name=display_name,
            description=description,
            agent_class=agent_class,
            config_path=config_path,
            optional=optional,
            order=order
        )


class BaseModuleAgent(ABC):
    """
    Abstract base class for module agents using react-agent architecture.
    
    This class provides:
    - React-agent creation using LangChain's create_agent
    - Unified state management
    - Dynamic prompt handling with welcome and config mode selection
    - Template method pattern for customization
    - Structured logging throughout
    """
    
    def __init__(self, provider: str, model: str, tools: List[BaseTool] = []):
        """
        Initialize the base agent
        
        Args:
            provider: LLM provider (e.g., 'openai', 'anthropic')
            model: Model name (e.g., 'gpt-4', 'claude-3')
            tools: List of MCP tools for the agent
        """
        self.provider = provider
        self.model = model
        self.tools = tools
        self.llm = create_llm_with_fallback(provider=self.provider, model=self.model)
        
        # Setup logging
        self.logger = get_logger(f"vitess_ai.server_agents.{self.module_name}")
        
        # Log initialization
        self.logger.info(f"Initializing {self.name} agent with model {model}")
        if tools:
            self.logger.info(f"Loaded {len(tools)} MCP tools")
        
        # Setup agent-specific configurations
        self._setup_llm()
        
        self.logger.info(f"{self.name} agent initialization completed")
    
    # =================
    # ABSTRACT PROPERTIES & METHODS
    # =================
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Agent name - must be implemented by subclasses"""
        pass
    
    @property
    @abstractmethod
    def module_name(self) -> str:
        """Module name (lowercase, no spaces) - used for keys and identification"""
        pass
    
    @property
    @abstractmethod
    def welcome_message(self) -> str:
        """Welcome message for the module"""
        pass
    
    @property
    @abstractmethod
    def default_prompt(self) -> str:
        """Default prompt for the module - used for default setup flow"""
        pass
    
    @property
    @abstractmethod
    def custom_prompt(self) -> str:
        """Custom prompt for the module - used for customize flow"""
        pass
    
    @abstractmethod
    def get_result_key(self) -> str:
        """Return the key name for storing results (e.g., 'readin_params')"""
        pass
    
    # =================
    # TEMPLATE METHODS (Override as needed)
    # =================
    
    def _get_next_module_name(self, state: dict = None) -> Optional[str]:
        """
        Helper method to determine the next module name from state.
        
        Args:
            state: State dictionary or UnifiedState object
            
        Returns:
            Next module name or None if no next module (should proceed to simulation)
        """
        if not state:
            return None
        
        try:
            # Check if state has get_next_module method (UnifiedState has this)
            # Note: Can't use isinstance() because UnifiedState extends TypedDict
            if hasattr(state, 'get_next_module') and callable(getattr(state, 'get_next_module')):
                next_module = state.get_next_module()
                
                # If it returns current module, get next one in order
                if next_module == self.module_name:
                    execution_order = state.execution_order if hasattr(state, 'execution_order') else []
                    try:
                        current_index = execution_order.index(self.module_name)
                        if current_index < len(execution_order) - 1:
                            return execution_order[current_index + 1]
                    except (ValueError, IndexError):
                        pass
                return next_module
            
            # Handle dict state (or state that behaves like a dict)
            if hasattr(state, 'get') or isinstance(state, dict):
                execution_order = state.get('execution_order', [])
                module_results = state.get('module_results', {})
                
                # Fallback: If execution_order is empty, use standard order
                if not execution_order:
                    standard_order = ['readin', 'guide', 'writeout']
                    self.logger.warning(f"Execution order not in state, using fallback: {standard_order}")
                    execution_order = standard_order
                
                # Get list of completed modules
                completed = []
                for name, result in module_results.items():
                    stage = getattr(result, 'stage', None) if hasattr(result, 'stage') else result.get('stage') if isinstance(result, dict) else None
                    # Handle both FillingStage object and dict/string
                    if hasattr(stage, 'stage'):
                        stage_value = stage.stage
                    elif isinstance(stage, dict):
                        stage_value = stage.get('stage')
                    else:
                        stage_value = stage
                    if stage_value == "completed":
                        completed.append(name)
                
                # Find first module in execution order that isn't current and isn't completed
                current_module = self.module_name
                for module in execution_order:
                    if module != current_module and module not in completed:
                        return module
                        
        except Exception as e:
            self.logger.error(f"Error in _get_next_module_name: {e}", exc_info=True)
        
        return None
    
    def get_completion_message(self, state: dict = None) -> str:
        """Message shown on successful completion - override if needed
        
        Args:
            state: Optional state dictionary to determine next module dynamically
        """
        return f"\n{self.name} configuration completed successfully!"
    
    # =================
    # PRIVATE SETUP METHODS
    # =================
    
    def _setup_llm(self):
        """Setup LLM with tools if available"""
        if self.tools:
            self.llm = self.llm.bind_tools(self.tools, parallel_tool_calls=False)
    
    # =================
    # REACT-AGENT CREATION
    # =================
    
    def get_module_prompt(self, config_mode: str = None, include_welcome: bool = True) -> str:
        """
        Get the module-specific prompt for react-agent.
        
        This combines welcome message with the appropriate prompt based on config_mode.
        The prompt is designed to handle the full flow: welcome → config mode selection → configuration.
        
        Args:
            config_mode: Configuration mode ('Default Setup' or 'Customize'/'Custom')
                         If None, the prompt will include instructions to detect it from conversation
            include_welcome: Whether to include welcome message in the prompt
            
        Returns:
            Combined prompt string for the react-agent
        """
        self.logger.debug(f"[PROMPT] Generating prompt for {self.module_name}: config_mode={config_mode}, include_welcome={include_welcome}")
        
        prompt_parts = []
        
        # Add welcome message if requested
        if include_welcome:
            prompt_parts.append(self.welcome_message)
            prompt_parts.append("""
**CONFIGURATION MODE SELECTION:**
After greeting the user, you need to determine their configuration preference:
- If they choose "Default Setup" or similar, use the DEFAULT SETUP instructions below
- If they choose "Customize" or "Custom" or want to modify parameters, use the CUSTOMIZE instructions below
- Parse their response to determine which mode they prefer
""")
        
        # Add appropriate prompt based on config mode
        if config_mode and config_mode in ['Customize', 'Custom']:
            prompt_parts.append("**CURRENT MODE: CUSTOMIZE**")
            prompt_parts.append(self.custom_prompt)
            self.logger.info(f"[PROMPT] Using CUSTOMIZE prompt for {self.module_name}")
        elif config_mode == 'Default Setup':
            prompt_parts.append("**CURRENT MODE: DEFAULT SETUP**")
            prompt_parts.append(self.default_prompt)
            self.logger.info(f"[PROMPT] Using DEFAULT SETUP prompt for {self.module_name}")
        else:
            # Include both prompts with instructions to use the appropriate one
            prompt_parts.append("""
**INSTRUCTIONS FOR CONFIGURATION MODE:**
Based on the user's response to the welcome message, use the appropriate section below:

1. If user chooses "Default Setup" or wants minimal configuration:
   → Use the DEFAULT SETUP section below

2. If user chooses "Customize" or wants to modify specific parameters:
   → Use the CUSTOMIZE section below

**DEFAULT SETUP SECTION:**
""")
            prompt_parts.append(self.default_prompt)
            prompt_parts.append("""
**CUSTOMIZE SECTION:**
""")
            prompt_parts.append(self.custom_prompt)
            self.logger.info(f"[PROMPT] Using DYNAMIC prompt (both modes) for {self.module_name} - will detect from conversation")
        
        final_prompt = "\n\n".join(prompt_parts)
        prompt_length = len(final_prompt)
        self.logger.debug(f"[PROMPT] Generated prompt for {self.module_name}: length={prompt_length} characters")
        
        return final_prompt
    
    def create_module_react_agent(self, config_mode: str = None, middleware: Optional[List[Any]] = None):
        """
        Create a react-agent for this module using LangChain's create_agent.
        
        The react-agent will:
        - Start with welcome message and handle config mode selection
        - Loop between agent → tools → agent until task complete
        - END when user input is needed (no tool calls, task incomplete)
        - Resume from checkpoint when invoked again
        
        Args:
            config_mode: Optional configuration mode. If provided, uses that mode.
                        If None, the prompt will handle mode selection from conversation.
            middleware: Optional list of middleware to apply to the agent.
                       Middleware can filter messages, add logging, etc.
        
        Returns:
            Compiled react-agent graph
        """
        self.logger.info(f"[REACT_AGENT] Creating react-agent for {self.module_name} with config_mode={config_mode}, provider={self.provider}, model={self.model}")
        
        # Get comprehensive prompt that includes welcome and handles config mode
        prompt = self.get_module_prompt(config_mode=config_mode, include_welcome=True)
        
        # Log tool information
        tool_names = [tool.name if hasattr(tool, 'name') else str(type(tool).__name__) for tool in self.tools]
        self.logger.debug(f"[REACT_AGENT] Tools for {self.module_name}: {tool_names}")
        
        # Prepare middleware list
        middleware_list = list(middleware) if middleware else []
        if middleware_list:
            middleware_names = [m.__class__.__name__ if hasattr(m, '__class__') else str(type(m).__name__) for m in middleware_list]
            self.logger.debug(f"[REACT_AGENT] Middleware for {self.module_name}: {middleware_names}")
        
        # Create react-agent with LLM, tools, module-specific prompt, and middleware
        react_agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=prompt,
            name=f"{self.module_name}_agent",
            middleware=middleware_list if middleware_list else None
        )
        
        self.logger.info(f"[REACT_AGENT] React-agent created successfully for {self.module_name}: {len(self.tools)} tools, prompt_length={len(prompt)}, middleware_count={len(middleware_list)}")
        return react_agent
    


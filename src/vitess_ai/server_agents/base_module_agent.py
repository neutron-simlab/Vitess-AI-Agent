"""
Base Module Agent - Base class for module agents

This class provides the foundation for agents that use react-agent
architecture with unified state management. Module agents are created
as react-agents using LangChain's create_agent and integrated
into the supervisor graph as nodes.
"""

import json
from typing import List, Type, Optional, Any
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from langchain.tools import BaseTool
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from vitess_ai.core.llms_providers import create_llm_with_fallback
from vitess_ai.core.log import get_logger
from vitess_ai.server_agents.unified_state import UnifiedState, ModuleResult
from vitess_ai.schema.base import FillingStage
from vitess_ai.server_agents.module_middleware import (
    MessageFilterMiddleware,
    DynamicModelMiddleware,
)
from vitess_ai.core.config import global_config


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
    
    @classmethod
    @abstractmethod
    def register_with_supervisor(cls, supervisor, config_path: str = None) -> None:
        """
        Register this module with the supervisor.
        
        This classmethod should create a ModuleMetadata object with module-specific
        information and register it with the supervisor.
        
        Args:
            supervisor: SupervisorAgent instance to register with
            config_path: Optional path to MCP tools configuration (overrides default)
        """
        pass
    
    # =================
    # TEMPLATE METHODS (Override as needed)
    # =================
    
    def _is_module_completed(self, result: Any) -> bool:
        """
        Helper method to check if a module result indicates completion.
        
        Args:
            result: ModuleResult object or dict
            
        Returns:
            True if module is completed, False otherwise
        """
        if not result:
            return False
        
        stage = getattr(result, 'stage', None) if hasattr(result, 'stage') else result.get('stage') if isinstance(result, dict) else None
        if not stage:
            return False
        
        # Handle both FillingStage object and dict/string
        if hasattr(stage, 'stage'):
            stage_value = stage.stage
        elif isinstance(stage, dict):
            stage_value = stage.get('stage')
        else:
            stage_value = stage
        
        return stage_value == "completed"
    
    def _normalize_params(self, params: Any) -> dict:
        """
        Normalize parameters to dict format.
        
        Args:
            params: Pydantic model, dict, or other type
            
        Returns:
            Dictionary of parameters
        """
        if hasattr(params, 'model_dump'):
            return params.model_dump()
        elif isinstance(params, dict):
            return params
        else:
            return params
    
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
                    if self._is_module_completed(result):
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
    # AGENT INSTANCE SETUP (Class Method)
    # =================
    
    @classmethod
    async def setup_agent_instance(
        cls, 
        module_metadata: 'ModuleMetadata',
        provider: str,
        model: str,
        logger
    ) -> 'BaseModuleAgent':
        """
        Setup an agent instance for a module with MCP tools.
        
        This class method handles:
        - Setting up MCP tools if config_path is provided
        - Creating the agent instance with the appropriate tools
        - Logging the initialization process
        
        Args:
            module_metadata: ModuleMetadata object containing module information
            provider: LLM provider (e.g., 'openai', 'anthropic')
            model: Model name (e.g., 'gpt-4', 'claude-3')
            logger: Logger instance for logging
            
        Returns:
            Initialized BaseModuleAgent instance
        """
        # Setup MCP tools if config path provided
        tools = []
        if module_metadata.config_path:
            try:
                from langchain_mcp_adapters.client import MultiServerMCPClient
                import os
                
                # Check transport mode
                if global_config.is_mcp_http_mode():
                    # Use HTTP transport (streamable-http for FastMCP compatibility)
                    mcp_url = global_config.get_mcp_url(module_metadata.name)
                    client = MultiServerMCPClient({
                        "validation": {
                            "url": mcp_url,
                            "transport": "streamable_http",
                            "headers": {
                                "Content-Type": "application/json",
                                "Accept": "application/json,text/event-stream",
                                "MCP-Protocol-Version": "2024-11-05"
                            }
                        }
                    })
                    logger.info(f"Connecting to {module_metadata.name} MCP server via HTTP: {mcp_url}")
                else:
                    # Use stdio transport (development mode)
                    # Prepare environment variables for MCP subprocess
                    # Include current environment plus THREAD_ID and VITESS_THREAD_ID if available
                    env = os.environ.copy()
                    # Note: thread_id will be set dynamically when tools are called via service.py
                    # The environment variables are passed at subprocess creation time
                    # We'll pass current env vars, and service.py will update them before tool calls
                    
                    client = MultiServerMCPClient({
                        "validation": {
                            "command": "python",
                            "args": [module_metadata.config_path],
                            "transport": "stdio",
                            "env": env  # Pass environment variables to subprocess
                        }
                    })
                    logger.debug(f"MCP client created with environment variables: THREAD_ID={env.get('THREAD_ID', 'not set')}, VITESS_THREAD_ID={env.get('VITESS_THREAD_ID', 'not set')}")
                
                tools = await client.get_tools()
                logger.info(f"Loaded {len(tools)} MCP tools for {module_metadata.name}")
            except Exception as e:
                logger.warning(f"Failed to load MCP tools for {module_metadata.name}: {e}")
        
        # Create agent instance
        agent = module_metadata.agent_class(
            provider=provider, 
            model=model, 
            tools=tools
        )
        
        logger.info(f"Initialized agent for module: {module_metadata.name}")
        return agent
    
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
        
        # Prepare middleware list: dynamic model first (so provider/model from configurable are used)
        middleware_list = [DynamicModelMiddleware()] + (list(middleware) if middleware else [])
        if middleware_list:
            middleware_names = [
                getattr(m, "__name__", None) or type(m).__name__
                for m in middleware_list
            ]
            self.logger.debug(f"[REACT_AGENT] Middleware for {self.module_name}: {middleware_names}")
        
        # Create react-agent with LLM, tools, module-specific prompt, and middleware
        react_agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=prompt,
            name=f"{self.module_name}_agent",
            middleware=middleware_list,
        )
        
        self.logger.info(f"[REACT_AGENT] React-agent created successfully for {self.module_name}: {len(self.tools)} tools, prompt_length={len(prompt)}, middleware_count={len(middleware_list)}")
        return react_agent
    
    # =================
    # MODULE WRAPPER NODE CREATION
    # =================
    
    def create_module_wrapper_node(self, react_agent, message_filter: MessageFilterMiddleware):
        """
        Create a wrapper around react-agent to handle state updates.
        
        This wrapper:
        - Checks if welcome message needs to be shown
        - Pre-filters messages using the same middleware logic (for consistency)
        - Invokes the react-agent (middleware will also filter during LLM calls)
        - Checks for module completion from tool results
        - Updates ModuleResult in state when complete
        - Manages current_active_module
        
        Args:
            react_agent: The react-agent instance
            message_filter: MessageFilterMiddleware instance to use for pre-filtering
        
        Returns:
            A wrapper node function that can be used in a LangGraph workflow
        """
        module_name = self.module_name
        
        async def wrapper_node(
            state: UnifiedState, config: Optional[RunnableConfig] = None
        ):
            """Wrapper node that invokes react-agent and handles state updates.
            Passes parent config (with configurable provider/model) so DynamicModelMiddleware can use it.
            """
            self.logger.info(f"[MODULE ENTRY] Entering module: {module_name}")
            
            messages = state.get('messages', [])
            current_active = state.get('current_active_module')
            
            # Determine if this is a new module entry or resuming the same module
            is_new_module = not current_active or current_active != module_name
            
            if is_new_module:
                self.logger.info(f"[MODULE ENTRY] New module entry detected for {module_name} (previous active: {current_active})")
                # Reset module-specific state when entering a new module
                state_updates = {
                    'current_active_module': module_name,
                    'current_module': module_name,
                }
                self.logger.info(f"[STATE RESET] Reset module-specific state for {module_name} (config_mode will be module-specific)")
            else:
                self.logger.info(f"[MODULE RESUME] Resuming module: {module_name}")
                state_updates = {'current_module': module_name}
            
            # Check if this is the first time entering this module
            # If no messages from this module yet, add welcome message
            if is_new_module:
                has_module_welcome = False
                for msg in messages:
                    if hasattr(msg, 'additional_kwargs') and msg.additional_kwargs.get('module_name') == module_name:
                        has_module_welcome = True
                        break
                    # Also check if welcome message content is present
                    if hasattr(msg, 'content') and self.welcome_message in str(msg.content):
                        has_module_welcome = True
                        break
                
                # Add welcome message if not present
                if not has_module_welcome:
                    welcome_msg = AIMessage(
                        content=self.welcome_message,
                        additional_kwargs={"module_name": module_name}
                    )
                    state_updates['messages'] = messages + [welcome_msg]
                    self.logger.info(f"[WELCOME] Added welcome message for module: {module_name}")
            
            # Get module-specific config_mode from module_config_modes dict
            # Prepare invoke state (with any updates we've made)
            invoke_state = {**state, **state_updates} if state_updates else state
            
            # Get or initialize module_config_modes
            module_config_modes = invoke_state.get('module_config_modes', {})
            if not isinstance(module_config_modes, dict):
                module_config_modes = {}
            
            # Get config_mode for this specific module
            config_mode = module_config_modes.get(module_name, '')
            
            # If config_mode is not set but we have messages, try to detect it from CURRENT module only
            if not config_mode:
                all_messages = invoke_state.get('messages', [])
                # Filter to only messages from the current module (simplified logic)
                module_messages = [
                    msg for msg in all_messages
                    if (hasattr(msg, 'additional_kwargs') and 
                        msg.additional_kwargs.get('module_name') == module_name) or
                       (not hasattr(msg, 'additional_kwargs') or 
                        not msg.additional_kwargs.get('module_name'))
                ]
                
                self.logger.debug(f"[CONFIG_MODE] Searching for config_mode in {len(module_messages)} messages from module {module_name}")
                
                # Look for user responses indicating config mode choice in module-specific messages
                for msg in reversed(module_messages):
                    if hasattr(msg, 'content'):
                        content = str(msg.content).lower()
                        if 'default' in content and 'setup' in content:
                            config_mode = 'Default Setup'
                            module_config_modes[module_name] = config_mode
                            state_updates['module_config_modes'] = module_config_modes
                            invoke_state['module_config_modes'] = module_config_modes
                            self.logger.info(f"[CONFIG_MODE] Detected config_mode='{config_mode}' for module {module_name}")
                            break
                        elif 'customize' in content or 'custom' in content:
                            config_mode = 'Customize'
                            module_config_modes[module_name] = config_mode
                            state_updates['module_config_modes'] = module_config_modes
                            invoke_state['module_config_modes'] = module_config_modes
                            self.logger.info(f"[CONFIG_MODE] Detected config_mode='{config_mode}' for module {module_name}")
                            break
                
                if not config_mode:
                    self.logger.debug(f"[CONFIG_MODE] No config_mode detected for module {module_name}, will use dynamic detection in prompt")
            else:
                self.logger.info(f"[CONFIG_MODE] Using existing config_mode='{config_mode}' for module {module_name}")
            
            # Invoke react-agent
            try:
                # Pre-filter messages using the same MessageFilterMiddleware logic that will be used
                # during LLM calls. This ensures consistency - we use the middleware's filter method
                # to pre-filter, and the middleware will also filter during execution.
                # This way, the react-agent sees filtered messages from the start, and the middleware
                # provides an additional safety filter during LLM calls.
                all_messages = invoke_state.get('messages', [])
                filtered_messages = message_filter._filter_module_messages(all_messages)
                
                self.logger.info(f"[PRE_FILTER] Using middleware filter: {len(all_messages)} -> {len(filtered_messages)} messages for module {module_name}")
                
                # Create filtered invoke_state with pre-filtered messages
                filtered_invoke_state = {**invoke_state, 'messages': filtered_messages}
                
                # React-agent expects messages in state (already pre-filtered by MessageFilterMiddleware)
                # The middleware will also filter during LLM calls as an additional safety measure
                messages_to_agent = filtered_invoke_state.get('messages', [])
                self.logger.info(f"[REACT_AGENT] Invoking react-agent for module {module_name} with {len(messages_to_agent)} pre-filtered messages")
                # Pass parent config (with configurable provider/model) so get_config() in DynamicModelMiddleware sees it
                configurable = (
                    getattr(config, "configurable", None) or {}
                    if config else {}
                )
                invoke_config = RunnableConfig(
                    recursion_limit=50,
                    configurable=dict(configurable),
                )
                result = await react_agent.ainvoke(filtered_invoke_state, config=invoke_config)
                
                # Check if module is complete by examining tool results in messages
                # IMPORTANT: Only check result_messages (from current invocation) to avoid picking up validation from previous modules
                result_messages = result.get('messages', [])
                
                # Annotate the last AIMessage with module_name for MessageFilterMiddleware
                # This allows the middleware to properly filter inactive modules
                if (result_messages and 
                    isinstance(result_messages, list) and 
                    result_messages != '_end_' and
                    len(result_messages) > 0):
                    last_message = result_messages[-1]
                    if isinstance(last_message, AIMessage):
                        # Ensure additional_kwargs exists
                        if not hasattr(last_message, 'additional_kwargs') or last_message.additional_kwargs is None:
                            last_message.additional_kwargs = {}
                        # Annotate with module_name for MessageFilterMiddleware
                        last_message.additional_kwargs['module_name'] = module_name
                        self.logger.debug(f"[ANNOTATION] Annotated last AIMessage with module_name={module_name}")
                
                self.logger.debug(f"[VALIDATION] Checking validation status for module {module_name}: {len(result_messages)} new messages from current invocation")
                
                module_complete = False
                validated_params = {}
                cli_params = ""
                validation_attempted = False
                validation_failed = False
                
                # Map module names to their validation tool name patterns
                module_validation_tools = {
                    'readin': 'validate_readin_module',
                    'guide': 'validate_guide_parameters',
                    'writeout': 'validate_writeout_module',
                    'monitor1d': 'validate_monitor1d_module',
                    'monitor2d': 'validate_monitor2d_module',
                }
                expected_tool_pattern = module_validation_tools.get(module_name, '')
                
                # Look for validation tool results indicating completion or failure
                # Only check result_messages from current invocation to ensure we're checking the right module
                for msg in reversed(result_messages):
                    if isinstance(msg, ToolMessage):
                        try:
                            # Parse tool result to check for validation success/failure
                            tool_result = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                            if isinstance(tool_result, dict):
                                validation_status = tool_result.get('validation_status', None)
                                
                                # Check if this is a validation tool result
                                if 'validation_status' in tool_result:
                                    validation_attempted = True
                                    # Try to identify the tool name from the tool_call_id
                                    # Find the corresponding AIMessage with this tool_call_id
                                    tool_name = None
                                    tool_call_id = getattr(msg, 'tool_call_id', None)
                                    if tool_call_id:
                                        # Look for the AIMessage that has this tool_call_id
                                        for ai_msg in reversed(result_messages):
                                            if hasattr(ai_msg, 'tool_calls') and ai_msg.tool_calls:
                                                for tc in ai_msg.tool_calls:
                                                    if tc.get('id') == tool_call_id:
                                                        tool_name = tc.get('name', '')
                                                        break
                                                if tool_name:
                                                    break
                                    
                                    # Check if tool belongs to this module
                                    tool_matches = (not expected_tool_pattern or 
                                                   (tool_name and expected_tool_pattern in tool_name))
                                    
                                    if not tool_matches:
                                        self.logger.debug(f"[VALIDATION] Validation result found but tool '{tool_name}' doesn't match expected pattern '{expected_tool_pattern}' for module {module_name}")
                                        continue
                                    
                                    self.logger.debug(f"[VALIDATION] Found validation_status={validation_status} for tool '{tool_name}' (expected pattern: '{expected_tool_pattern}')")
                                    
                                    # Handle validation success
                                    if validation_status is True:
                                        validated_params_raw = tool_result.get('validated_params', {})
                                        cli_params_raw = tool_result.get('cli_parameters', '')
                                        
                                        validated_params = self._normalize_params(validated_params_raw)
                                        cli_params = cli_params_raw if cli_params_raw else ''
                                        
                                        # Check if parameters are actually present
                                        has_params = bool(
                                            validated_params and 
                                            (isinstance(validated_params, dict) and len(validated_params) > 0 or 
                                             not isinstance(validated_params, dict) and validated_params)
                                        )
                                        
                                        if has_params:
                                            # Module validation succeeded - module is complete
                                            module_complete = True
                                            tool_name_display = tool_name or 'unknown'
                                            params_count = len(validated_params) if isinstance(validated_params, dict) else 'N/A'
                                            cli_length = len(cli_params) if cli_params else 0
                                            self.logger.info(f"[VALIDATION] Module {module_name} validation succeeded (tool: {tool_name_display}, params_count: {params_count}, cli_length: {cli_length})")
                                            break
                                        else:
                                            self.logger.debug(f"[VALIDATION] Validation result found but validated_params is empty for module {module_name}")
                                    # Handle validation failure
                                    elif validation_status is False:
                                        validation_failed = True
                                        tool_name_display = tool_name or 'unknown'
                                        error_message = tool_result.get('errors', tool_result.get('message', 'Validation failed'))
                                        self.logger.info(f"[VALIDATION] Module {module_name} validation failed (tool: {tool_name_display}): {error_message}")
                                        break
                        except (json.JSONDecodeError, AttributeError, TypeError) as e:
                            # Not a validation result, continue
                            self.logger.debug(f"[VALIDATION] Skipping non-validation tool message: {type(e).__name__}")
                            continue
                
                # Get existing module result if any
                existing_results = state.get('module_results', {})
                existing_result = existing_results.get(module_name)
                
                # Update module result based on validation status
                if module_complete:
                    validated_params_dict = self._normalize_params(validated_params)
                    
                    module_result = ModuleResult(
                        module_name=module_name,
                        stage=FillingStage(stage='completed'),
                        parameters=validated_params_dict,
                        cli_parameters=cli_params,
                        thread_id=state.get('thread_id'),
                        user_id=state.get('user_id')
                    )
                    updated_results = state.get('module_results', {}).copy()
                    updated_results[module_name] = module_result
                    
                    params_count = len(validated_params_dict) if isinstance(validated_params_dict, dict) else 0
                    cli_length = len(cli_params) if cli_params else 0
                    self.logger.info(f"[MODULE COMPLETE] Module {module_name} completed successfully: {params_count} parameters validated, cli_parameters length={cli_length}")
                    
                    state_updates.update({
                        'module_results': updated_results,
                        'current_active_module': None,  # Clear active module
                        'module_stage': FillingStage(stage='completed')
                    })
                    self.logger.info(f"[STATE UPDATE] Cleared current_active_module, set module_stage=completed for {module_name}")
                else:
                    # Module still processing - validation not complete or failed
                    # Always create/update ModuleResult with stage='processing' to track state
                    updated_results = existing_results.copy()
                    
                    # Preserve existing parameters if available (from previous successful validation)
                    existing_params = None
                    existing_cli = None
                    if existing_result:
                        existing_params = existing_result.parameters
                        existing_cli = existing_result.cli_parameters
                    
                    # Create/update ModuleResult with processing stage
                    processing_result = ModuleResult(
                        module_name=module_name,
                        stage=FillingStage(stage='processing'),
                        parameters=existing_params,  # Keep existing params if any
                        cli_parameters=existing_cli,  # Keep existing CLI if any
                        thread_id=state.get('thread_id'),
                        user_id=state.get('user_id')
                    )
                    updated_results[module_name] = processing_result
                    
                    if validation_failed:
                        self.logger.info(f"[MODULE PROCESSING] Module {module_name} validation failed - setting stage to 'processing'")
                    elif validation_attempted:
                        self.logger.debug(f"[MODULE PROCESSING] Module {module_name} validation attempted but not successful - setting stage to 'processing'")
                    else:
                        self.logger.debug(f"[MODULE PROCESSING] Module {module_name} validation not yet attempted - setting stage to 'processing'")
                    
                    state_updates.update({
                        'module_results': updated_results,
                        'module_stage': FillingStage(stage='processing')
                    })
                    self.logger.debug(f"[MODULE PROCESSING] Module {module_name} still processing, module_stage=processing, ModuleResult updated")
                
                # Merge react-agent result with state updates
                self.logger.debug(f"[MODULE EXIT] Exiting module {module_name}, module_complete={module_complete}")
                return {**result, **state_updates}
            except Exception as e:
                self.logger.error(f"[MODULE ERROR] Error in react-agent for {module_name}: {e}", exc_info=True)
                # Return error state
                error_result = ModuleResult(
                    module_name=module_name,
                    stage=FillingStage(stage='error'),
                    error_message=str(e),
                    thread_id=state.get('thread_id'),
                    user_id=state.get('user_id')
                )
                updated_results = state.get('module_results', {}).copy()
                updated_results[module_name] = error_result
                
                self.logger.error(f"[STATE UPDATE] Set module {module_name} to error state, cleared current_active_module")
                
                return {
                    **state_updates,
                    'module_results': updated_results,
                    'module_stage': FillingStage(stage='error'),
                    'error_message': str(e),
                    'current_active_module': None
                }
        
        return wrapper_node
    


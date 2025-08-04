"""
BaseModuleAgent - Abstract base class for all simulation module agents
Provides common functionality and enforces consistent interface across all modules
"""
import json
import logging
from typing import List, Optional, Any, Type, TypeVar, Generic, Dict
from enum import Enum
from pydantic import BaseModel, Field
from abc import ABC, abstractmethod
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, AIMessage
from vitess_ai.core.llms_providers import create_llm_with_fallback
from langchain.tools import BaseTool
from langgraph.graph import StateGraph, END, START, MessagesState
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from vitess_ai.schema.base import FillingStage

# Type variables for generic parameter types
R = TypeVar('R')  # For initial response types

class BaseModuleState(MessagesState):
    """Base state class that all module agents should use"""
    stage: FillingStage
    config_mode: str
    validation_status: Optional[bool] = None
    error_message: Optional[str] = None
    parameters: Any = None
    cli_parameters: str = None


class BaseModuleAgent(ABC, Generic[R]):
    """
    Abstract base class for all simulation module agents.
    
    This class provides:
    - Common initialization patterns
    - Standardized graph structure
    - Consistent node implementations
    - Template method pattern for customization
    - Type safety with generics
    - Structured logging throughout
    """
    
    def __init__(self, provider:str, model: str, tools: List[BaseTool] = []):
        """Initialize the base module agent"""
        self.provider = provider
        self.model = model
        self.tools = tools
        self.llm = create_llm_with_fallback(provider=self.provider, model=self.model)
        
        
        # Setup logging
        self._setup_logging()
        
        # Log initialization
        self.logger.info(f"Initializing {self.name} with model {model}")
        if tools:
            self.logger.info(f"Loaded {len(tools)} MCP tools")
        
        # Setup agent-specific configurations
        self._setup_prompts()
        self._setup_llm()
        
        # Create the graph
        self.graph = self._create_base_graph()
        
        # Add memory for conversation persistence
        self.memory = MemorySaver()
        self.app = self.graph.compile(checkpointer=self.memory)
        
        self.logger.info(f"{self.name} initialization completed")
    
    def _setup_logging(self):
        """Setup logging for the module agent"""
        # Create logger specific to this agent instance
        logger_name = f"vitess_ai.agents.{self.module_name}"
        self.logger = logging.getLogger(logger_name)
        
        # Only add handler if logger doesn't have one (avoid duplicates)
        if not self.logger.handlers:
            # Create console handler
            handler = logging.StreamHandler()
            handler.setLevel(logging.INFO)
            
            # Create formatter
            formatter = logging.Formatter(
                fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            
            # Add handler to logger
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            
            # Prevent propagation to avoid duplicate logs
            self.logger.propagate = False
    
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
    def system_prompt(self) -> str:
        """System prompt for the module"""
        pass
    
    @abstractmethod
    def get_initial_response_schema(self) -> Type[R]:
        """Return the Pydantic schema for initial user response parsing"""
        pass
    
    
    @abstractmethod
    def get_result_key(self) -> str:
        """Return the key name for storing results (e.g., 'readin_params')"""
        pass
    
    # =================
    # TEMPLATE METHODS (Override as needed)
    # =================
    
    def get_default_setup_message(self) -> str:
        """Message shown when user chooses default setup - override if needed"""
        return f"""
        You have chosen the default setup configuration. We will use optimal default values 
        for most {self.module_name} parameters. You'll only need to specify essential 
        parameters that require manual input.
        """
    
    def get_customize_setup_message(self) -> str:
        """Message shown when user chooses customization - override if needed"""
        return f"""
        You have chosen the customize configuration. I'll help you configure the 
        {self.module_name} parameters step by step. We'll go through each parameter 
        and you can choose which ones to modify from the defaults.
        """
    
    def get_completion_message(self) -> str:
        """Message shown on successful completion - override if needed"""
        return f"\n{self.name} configuration completed successfully!"
    
    def parse_config_mode(self, response: R) -> str:
        """Parse config mode from initial response - override if different attribute name"""
        return response.response  # type: ignore
    
    def validate_config_mode(self, config_mode: str) -> bool:
        """Validate the config mode - override for custom validation"""
        return config_mode in ['Default Setup', 'Customize', 'Custom']
    
    def get_valid_config_modes(self) -> List[str]:
        """Return list of valid configuration modes - override if different"""
        return ['Default Setup', 'Customize', 'Custom']
    
    # =================
    # PRIVATE SETUP METHODS
    # =================
    
    def _setup_prompts(self):
        """Setup prompts based on whether tools are available"""
        if self.tools:
            self.welcome_prompt = AIMessage(content=self.welcome_message)
            self.sys_prompt = SystemMessage(content=self.system_prompt)
        else:
            self.welcome_prompt = SystemMessage(content=self.welcome_message)
            self.sys_prompt = SystemMessage(content=self.system_prompt)
    
    def _setup_llm(self):
        """Setup LLM with tools if available"""
        if self.tools:
            self.llm = self.llm.bind_tools(self.tools, parallel_tool_calls=False)
    
    # =================
    # GRAPH CREATION
    # =================
    
    def _create_base_graph(self) -> StateGraph:
        """Create the standardized graph structure"""
        workflow = StateGraph(BaseModuleState)
        
        # Standard nodes that all modules have
        workflow.add_node("welcome", self._welcome_node)
        workflow.add_node("default_setup", self._default_setup_node)
        workflow.add_node("customize_setup", self._customize_setup_node)
        workflow.add_node("params_config", self._parameters_configuration)
        workflow.add_node("finalize", self._finalize_node)
        
        # Add tools node only if tools are available
        if self.tools:
            workflow.add_node("tools", ToolNode(self.tools))
        
        # Standard edges
        workflow.add_edge(START, 'welcome')
        workflow.add_conditional_edges('welcome', self._route_after_init)
        workflow.add_edge('default_setup', 'params_config')
        workflow.add_edge('customize_setup', 'params_config')
        workflow.add_edge('finalize', END)
        workflow.add_conditional_edges('params_config', self._condition_parameters_config)
        
        # Add tool edges only if tools are available
        if self.tools:
            workflow.add_conditional_edges('tools', self._route_after_tools)
        
        return workflow
    
    # =================
    # STANDARD NODE IMPLEMENTATIONS
    # =================
    
    def _welcome_node(self, state: BaseModuleState) -> BaseModuleState:
        """Standardized welcome node implementation"""
        self.logger.info("Starting welcome interaction")
        
        print(f"{self.welcome_prompt.content}")
        user_init_message = input("\nUser:\n").strip()
        
        self.logger.info(f"User initial input received: {user_init_message[:50]}{'...' if len(user_init_message) > 50 else ''}")
        
        # Create instruction message for parsing
        instruction_message = SystemMessage(content=f"""
        Parse the user's response to determine their configuration choice.
        Valid options: {', '.join(self.get_valid_config_modes())}
        
        ❌ **Not Known**: When the user's input does not clearly indicate a choice 
        between the valid options (e.g., unrelated topics, ambiguous language)
        """)
        
        messages = [self.welcome_prompt, instruction_message, HumanMessage(user_init_message)]
        
        # Use structured output to parse response
        initial_response_schema = self.get_initial_response_schema()
        structured_llm = self.llm.with_structured_output(initial_response_schema)
        
        try:
            response = structured_llm.invoke(messages)
            config_mode = self.parse_config_mode(response)
            self.logger.info(f"Parsed configuration mode: {config_mode}")
        except Exception as e:
            self.logger.error(f"Failed to parse initial response: {e}")
            config_mode = "Unknown"
        
        return {
            'messages': [self.sys_prompt, *messages],
            'stage': FillingStage(stage='processing'),
            'config_mode': config_mode,
            'validation_status': None,
            'error_message': None
        }
    
    def _route_after_init(self, state: BaseModuleState) -> str:
        """Standardized routing after initial welcome"""
        config_mode = state.get('config_mode', '')
        self.logger.info(f"Routing after init with config_mode: {config_mode}")
        
        if not self.validate_config_mode(config_mode):
            self.logger.warning(f"Invalid config mode '{config_mode}', ending conversation")
            print("We don't understand your choice.\nWe will end the conversation.")
            return END
        
        # Map config modes to nodes - customize this mapping in subclasses if needed
        if config_mode in ['Customize', 'Custom']:
            self.logger.info("Routing to customize setup")
            return 'customize_setup'
        elif config_mode == 'Default Setup':
            self.logger.info("Routing to default setup")
            return 'default_setup'
        else:
            self.logger.error(f"Unhandled config mode: {config_mode}")
            print("Invalid configuration mode selected.")
            return END
    
    def _default_setup_node(self, state: BaseModuleState) -> BaseModuleState:
        """Standardized default setup node"""
        self.logger.info("Entering default setup configuration")
        print(f"\n=== HANDLING DEFAULT SETUP CONFIGURATION ===")
        
        sys_default_message = SystemMessage(content=self.get_default_setup_message())
        
        return {
            'messages': [*state['messages'], sys_default_message],
            'stage': state.get('stage', FillingStage(stage='processing')),
            'config_mode': state.get('config_mode', ''),
            'validation_status': state.get('validation_status'),
            'error_message': state.get('error_message')
        }
    
    def _customize_setup_node(self, state: BaseModuleState) -> BaseModuleState:
        """Standardized customize setup node"""
        self.logger.info("Entering customized configuration")
        print(f"\n=== HANDLING CUSTOMIZED CONFIGURATION ===")
        
        sys_customize_message = SystemMessage(content=self.get_customize_setup_message())
        
        return {
            'messages': [*state['messages'], sys_customize_message],
            'stage': state.get('stage', FillingStage(stage='processing')),
            'config_mode': state.get('config_mode', ''),
            'validation_status': state.get('validation_status'),
            'error_message': state.get('error_message')
        }
    
    def _parameters_configuration(self, state: BaseModuleState) -> BaseModuleState:
        """
        Standardized parameter configuration with logging
        Template method - can be overridden for custom behavior
        """
        self.logger.info(f"Entering parameters configuration for {self.name}")
        self.logger.info(f"Current state messages count: {len(state['messages'])}")
        self.logger.info(f"Config mode: {state.get('config_mode', 'not set')}")
        
        print(f"\n=== ENTERING _parameters_configuration for {self.name} ===")
        
        # Use LLM with tools for enhanced functionality
        try:
            response = self.llm.invoke(state['messages'])
            self.logger.info("LLM response received successfully")
        except Exception as e:
            self.logger.error(f"LLM invocation failed: {e}")
            response = None
        
        if not response:
            self.logger.error("No response from LLM, returning error state")
            return {
                'messages': state['messages'],
                'stage': FillingStage(stage='error'),
                'config_mode': state.get('config_mode', ''),
                'validation_status': False,
                'error_message': "Failed to get LLM response"
            }
        
        # Always add the AI response to messages first
        updated_messages = state['messages'] + [response]
        self.logger.info(f"Updated messages count after adding response: {len(updated_messages)}")
        
        print(f"\nAssistant:\n{response.content}")
        
        # Check for tool calls
        # future: check with other providers
        has_tool_calls = hasattr(response, 'tool_calls') and response.tool_calls
        self.logger.info(f"Tool calls detected: {has_tool_calls}")
        
        if has_tool_calls:
            self.logger.info("Routing to tools node")
            return {
                'messages': updated_messages,
                'stage': FillingStage(stage='processing'),
                'config_mode': state.get('config_mode', ''),
                'validation_status': state.get('validation_status'),
                'error_message': state.get('error_message')
            }
        else:
            self.logger.info("No tool calls, getting user input")
            user_input = input("\nUser:\n").strip()
            self.logger.info(f"User input received: {user_input[:50]}{'...' if len(user_input) > 50 else ''}")
            
            final_messages = updated_messages + [HumanMessage(content=user_input)]
            self.logger.info(f"Final messages count after user input: {len(final_messages)}")
            
            return {
                'messages': final_messages,
                'stage': FillingStage(stage='processing'),
                'config_mode': state.get('config_mode', ''),
                'validation_status': state.get('validation_status'),
                'error_message': state.get('error_message')
            }
    
    def _finalize_node(self, state: BaseModuleState) -> BaseModuleState:
        """Standardized finalization node"""
        self.logger.info(f"Entering finalization for {self.name}")
        print(f"\n=== HANDLING FINAL STEP for {self.name} ===")
        print(self.get_completion_message())
        
        last_message = state['messages'][-1].content
        try:
            parsed_result = json.loads(last_message)
            validation_status = parsed_result.get('validation_status', True)

            self.logger.info(f"the cli parameters are {parsed_result['cli_parameters']}")
            
            result_dict = {
                'stage': FillingStage(stage='completed'),
                'config_mode': state.get('config_mode', ''),
                'validation_status': validation_status,
                'error_message': None,
                'parameters': parsed_result['validated_params'],
                'cli_parameters': parsed_result['cli_parameters']
            }
            
            return result_dict
        
        except Exception as e:
            error_msg = f"Failed to parse final result: {str(e)}"
            self.logger.error(error_msg)
            return {
                # 'messages': state['messages'],
                'stage': state.get('stage', FillingStage(stage='error')),
                'config_mode': state.get('config_mode', ''),
                'validation_status': False,
                'error_message': error_msg
            }
    
    def _route_after_tools(self, state: BaseModuleState) -> str:
        """Standardized routing after tool execution"""
        if not self.tools:
            self.logger.warning("No tools available, routing to params_config")
            return 'params_config'
        
        last_message = state['messages'][-1].content
        self.logger.info("Processing tool execution results")
        
        try:
            parsed_message = json.loads(last_message)
            validation_status = parsed_message.get('validation_status', False)
            
            if validation_status:
                self.logger.info("Tool validation successful, routing to finalize")
                return 'finalize'
            else:
                self.logger.info("Tool validation failed or Tool does other except validation, routing back to params_config")
                return 'params_config'
                
        except Exception as e:
            self.logger.error(f"Error parsing tool result: {str(e)}")
            return 'params_config'
    
    def _condition_parameters_config(self, state: BaseModuleState) -> str:
        """Standardized condition for parameter configuration routing"""
        last_message = state['messages'][-1]
        
        # Check for tool calls only if tools are available
        if (self.tools and 
            hasattr(last_message, 'tool_calls') and 
            last_message.tool_calls):
            self.logger.info('Tool calls detected, routing to tools')
            return 'tools'
        else:
            self.logger.info('Continuing parameter configuration')
            return 'params_config'
    
    # =================
    # PUBLIC API
    # =================
    
    async def run(self, user_input: str, thread_id: str = "default") -> str | dict:
        """
        Standardized run method that all modules can use
        Can be overridden for custom behavior
        """
        self.logger.info(f"Starting agent run with thread_id: {thread_id}")
        
        config = {"configurable": {"thread_id": thread_id}}
        current_state = self.app.get_state(config)
        
        # Prepare input message
        user_message = HumanMessage(content=user_input)
        
        if current_state.values:
            # Continue existing conversation
            self.logger.info("Continuing existing conversation")
            current_messages = current_state.values.get("messages", [])
            input_state = {
                "messages": current_messages + [user_message],
                "stage": current_state.values.get("stage", FillingStage(stage='processing')),
                "config_mode": current_state.values.get("config_mode", ""),
                "validation_status": current_state.values.get("validation_status"),
                "error_message": current_state.values.get("error_message")
            }
        else:
            # Start new conversation
            self.logger.info("Starting new conversation")
            input_state = {
                "messages": [user_message],
                "stage": FillingStage(stage='processing'),
                "config_mode": "",
                "validation_status": None,
                "error_message": None
            }
        
        try:
            # Run the graph
            self.logger.info("Invoking agent graph")
            result = await self.app.ainvoke(input_state, config)
             # Return results in standardized format
            if result.get('validation_status'):
                self.logger.info("Agent run completed successfully")
                return {
                    'parameters':result['parameters'],
                    'cli_parameters':result['cli_parameters']
                }
            else:
                self.logger.warning("Agent run completed but no valid results generated")
                return "No response generated"
                
        except Exception as e:
            self.logger.error(f"Agent run failed: {e}")
            return f"Agent execution failed: {str(e)}"
    
    def stream_run(self, user_input: str, thread_id: str = "default"):
        """Standardized streaming method"""
        config = {"configurable": {"thread_id": thread_id}}
        current_state = self.app.get_state(config)
        user_message = HumanMessage(content=user_input)
        
        if current_state.values:
            current_messages = current_state.values.get("messages", [])
            input_state = {
                "messages": current_messages + [user_message],
                "stage": current_state.values.get("stage", FillingStage(stage='processing')),
                "config_mode": current_state.values.get("config_mode", ""),
                "validation_status": current_state.values.get("validation_status"),
                "error_message": current_state.values.get("error_message")
            }
        else:
            input_state = {
                "messages": [user_message],
                "stage": FillingStage(stage='processing'),
                "config_mode": "",
                "validation_status": None,
                "error_message": None
            }
        
        for chunk in self.app.stream(input_state, config):
            yield chunk
    
    def get_conversation_history(self, thread_id: str = "default") -> List[BaseMessage]:
        """Standardized conversation history method"""
        config = {"configurable": {"thread_id": thread_id}}
        state = self.app.get_state(config)
        return state.values.get("messages", []) if state.values else []


# =================
# LOGGING UTILITIES
# =================

def setup_module_logging(log_level: str = "INFO", log_format: Optional[str] = None):
    """Setup logging configuration for all module agents"""
    
    # Set up root logger for vitess_ai.agents
    root_logger = logging.getLogger("vitess_ai.agents")
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper()))
    
    # Create formatter
    if log_format is None:
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    formatter = logging.Formatter(
        fmt=log_format,
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    # Add handler to root logger
    root_logger.addHandler(console_handler)
    root_logger.setLevel(getattr(logging, log_level.upper()))
    root_logger.propagate = False
    
    print(f"✅ Module logging configured at {log_level} level")

def get_all_agent_loggers() -> List[logging.Logger]:
    """Get all active agent loggers"""
    loggers = []
    for name in logging.Logger.manager.loggerDict:
        if name.startswith("vitess_ai.agents."):
            logger = logging.getLogger(name)
            if logger.handlers:  # Only include loggers with handlers (active agents)
                loggers.append(logger)
    return loggers

def set_all_agents_log_level(level: str):
    """Set log level for all active agent loggers"""
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {level}')
    
    count = 0
    for logger in get_all_agent_loggers():
        logger.setLevel(numeric_level)
        for handler in logger.handlers:
            handler.setLevel(numeric_level)
        count += 1
    
    print(f"✅ Updated log level to {level.upper()} for {count} agent loggers")


class ModuleStatus(str, Enum):
    """Status of individual modules"""
    COMPLETED = "completed"
   
class ModuleResult(BaseModel):
    """Result from a completed module agent"""
    module_name: str
    status: ModuleStatus
    parameters: Optional[Dict[str, Any]] = None
    cli_parameters: Optional[str] = None
    error_message: Optional[str] = None
    execution_time: Optional[float] = None
    thread_id: Optional[str] = None

class ModuleMetadata(BaseModel):
    """Definition of a registerable module"""
    name: str = Field(..., description="Module name (e.g., 'readin')")
    display_name: str = Field(..., description="Human-readable name (e.g., 'Read-in Parameters')")
    description: str = Field(..., description="Module description")
    agent_class: Type[BaseModuleAgent] = Field(..., description="Agent class for this module")
    optional: bool = Field(default=False, description="Whether module can be skipped")
    config_path: Optional[str] = Field(None, description="Path to MCP tools configuration")
    order: int = Field(default=100, description="Execution order (1, 2, 3, etc.)")
    
    class Config:
        arbitrary_types_allowed = True


# =================
# MODULE BUILDER - Creates module definitions
# =================

class ModuleBuilder:
    """Simple helper to create module definitions"""
    
    @staticmethod
    def create(
        name: str,
        display_name: str, 
        description: str,
        agent_class: Type[BaseModuleAgent],
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


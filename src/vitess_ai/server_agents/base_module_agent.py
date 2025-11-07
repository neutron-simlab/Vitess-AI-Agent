"""
Base Module Agent - Base class for module agents

This class provides the foundation for agents that use a flat graph
architecture with unified state management. This class is designed
to work as individual nodes within a larger supervisor graph.
"""

import logging
from typing import List, Type, TypeVar, Generic, Optional, Any, Dict
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain.tools import BaseTool
from langgraph.types import interrupt
from vitess_ai.core.llms_providers import create_llm_with_fallback
from vitess_ai.schema.base import FillingStage
from vitess_ai.server_agents.unified_state import UnifiedState, ModuleResult, ModuleStatus

# Type variables for generic parameter types
R = TypeVar('R')  # For initial response types


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


class BaseModuleAgent(ABC, Generic[R]):
    """
    Abstract base class for module agents.
    
    This class provides:
    - Flat graph node implementations (no subgraphs)
    - Unified state management
    - Standardized node patterns
    - Template method pattern for customization
    - Type safety with generics
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
        self._setup_logging()
        
        # Log initialization
        self.logger.info(f"Initializing {self.name} agent with model {model}")
        if tools:
            self.logger.info(f"Loaded {len(tools)} MCP tools")
        
        # Setup agent-specific configurations
        self._setup_prompts()
        self._setup_llm()
        
        self.logger.info(f"{self.name} agent initialization completed")
    
    def _setup_logging(self):
        """Setup logging for the agent"""
        # Create logger specific to this agent instance
        logger_name = f"vitess_ai.server_agents.{self.module_name}"
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
    def default_prompt(self) -> str:
        """Default prompt for the module - used for default setup flow"""
        pass
    
    @property
    @abstractmethod
    def custom_prompt(self) -> str:
        """Custom prompt for the module - used for customize flow"""
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
                    status = getattr(result, 'status', None) if hasattr(result, 'status') else result.get('status') if isinstance(result, dict) else None
                    if status == ModuleStatus.COMPLETED or status == 'completed':
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
        self.welcome_prompt = AIMessage(content=self.welcome_message)
        self.default_sys_prompt = SystemMessage(content=self.default_prompt)
        self.custom_sys_prompt = SystemMessage(content=self.custom_prompt)
        
    
    def _setup_llm(self):
        """Setup LLM with tools if available"""
        if self.tools:
            self.llm = self.llm.bind_tools(self.tools, parallel_tool_calls=False)
    
    # =================
    # FLAT GRAPH NODE IMPLEMENTATIONS
    # =================
    
    def welcome_node(self, state: UnifiedState) -> dict:
        """Welcome node for the module - emits welcome message only"""
        self.logger.info(f"Starting {self.name} welcome interaction")
        
        # Create welcome message without decorative header - Streamlit app handles styling
        welcome_text = f"{self.welcome_message}"
        welcome = AIMessage(content=welcome_text, additional_kwargs={"module_name": self.module_name})
        
        # Return state updates without mutating input state (LangGraph best practice)
        return {
            'current_module': self.module_name,
            'module_stage': FillingStage(stage='processing'),
            'messages': state.get('messages', []) + [welcome],
            'error_message': None
        }

    def welcome_interrupt_node(self, state: UnifiedState) -> dict:
        """Interrupt node to collect initial choice and parse it"""
        self.logger.info(f"Triggering interrupt for {self.name} initial choice")
        
        # Instruction for parsing user response
        instruction_message = SystemMessage(content=f"""
        Parse the user's response to determine their configuration choice.
        Valid options: {', '.join(self.get_valid_config_modes())}
        
        ❌ **Not Known**: When the user's input does not clearly indicate a choice 
        between the valid options (e.g., unrelated topics, ambiguous language)
        """)
        
        # Trigger interrupt and get user input
        user_input = interrupt("Please choose: Default Setup or Customize")
        self.logger.info(f"User input received: {user_input[:50]}{'...' if len(user_input) > 50 else ''}")
        
        # Find welcome message (first AI message with module_name metadata, or last AI message)
        all_messages = state.get('messages', [])
        welcome_msg = None
        for msg in all_messages:
            if hasattr(msg, 'type') and msg.type == 'ai':
                if hasattr(msg, 'additional_kwargs') and msg.additional_kwargs.get('module_name') == self.module_name:
                    welcome_msg = msg
                    break
        
        if not welcome_msg:
            for msg in reversed(all_messages):
                if hasattr(msg, 'type') and msg.type == 'ai':
                    welcome_msg = msg
                    break
        
        # Build minimal message set: welcome (if exists) + instruction + user input
        messages = [instruction_message, HumanMessage(content=user_input)]
        if welcome_msg:
            messages.insert(0, welcome_msg)
        
        # Create structured LLM and parse user input
        initial_response_schema = self.get_initial_response_schema()
        try:
            structured_llm = self.llm.with_structured_output(initial_response_schema)
        except Exception as e:
            self.logger.error(f"Failed to create structured LLM: {e}")
            return {
                'messages': messages,
                'config_mode': "Unknown",
                'validation_status': None,
                'error_message': f"Failed to create structured LLM: {str(e)}"
            }
        
        # Try to parse with full messages, fallback to minimal on error
        try:
            config_mode = self._parse_config_with_llm(structured_llm, messages)
        except Exception as e:
            self.logger.warning(f"Initial parse failed, retrying with minimal messages: {e}")
            try:
                minimal_messages = [instruction_message, HumanMessage(content=user_input)]
                config_mode = self._parse_config_with_llm(structured_llm, minimal_messages)
            except Exception as retry_error:
                self.logger.error(f"Retry also failed: {retry_error}")
                config_mode = "Default Setup"
        
        return {
            'messages': messages,
            'config_mode': config_mode,
            'validation_status': None,
            'error_message': None
        }
    
    def _parse_config_with_llm(self, structured_llm, messages):
        """Parse config mode using structured LLM with timeout protection"""
        import time
        import threading
        import queue
        from vitess_ai.core.config import global_config
        
        timeout_seconds = getattr(self.llm, 'timeout', global_config.TIMEOUT_SECONDS)
        result_queue = queue.Queue()
        exception_queue = queue.Queue()
        
        def invoke_llm():
            try:
                result = structured_llm.invoke(messages)
                result_queue.put(result)
            except Exception as e:
                exception_queue.put(e)
        
        invoke_thread = threading.Thread(target=invoke_llm, daemon=True)
        invoke_thread.start()
        invoke_thread.join(timeout=timeout_seconds + 10)
        
        if invoke_thread.is_alive():
            raise TimeoutError(f"LLM invocation timed out after {timeout_seconds}s")
        
        if not exception_queue.empty():
            raise exception_queue.get()
        
        if result_queue.empty():
            raise RuntimeError("LLM invocation returned no result")
        
        response = result_queue.get()
        config_mode = self.parse_config_mode(response)
        self.logger.info(f"Parsed configuration mode: {config_mode}")
        return config_mode
    
    def default_setup_node(self, state: UnifiedState) -> dict:
        """Default setup node"""
        self.logger.info(f"Entering {self.name} default setup configuration")
        
        setup_message = f"\n=== HANDLING DEFAULT SETUP CONFIGURATION for {self.name} ==="
        sys_default_message = SystemMessage(content=self.get_default_setup_message())
        
        return {
            'messages': state.get('messages', []) + [AIMessage(content=setup_message), sys_default_message, self.default_sys_prompt],
            'module_stage': FillingStage(stage='processing'),
            'error_message': None
        }
    
    def customize_setup_node(self, state: UnifiedState) -> dict:
        """Customize setup node"""
        self.logger.info(f"Entering {self.name} customized configuration")
        
        setup_message = f"\n=== HANDLING CUSTOMIZED CONFIGURATION for {self.name} ==="
        sys_customize_message = SystemMessage(content=self.get_customize_setup_message())
        
        return {
            'messages': state.get('messages', []) + [AIMessage(content=setup_message), sys_customize_message, self.custom_sys_prompt],
            'module_stage': FillingStage(stage='processing'),
            'error_message': None
        }
    
    def _params_config_node(self, state: UnifiedState, config_mode: str) -> dict:
        """Unified parameters configuration node with tool support
        
        Args:
            state: Current state
            config_mode: Configuration mode ('Default Setup' or 'Customize'/'Custom')
        """
        mode_text = "default" if config_mode == 'Default Setup' else "custom"
        self.logger.info(f"Entering {self.name} {mode_text} parameters configuration")
        
        # Get thread_id from state and inject it into the context
        thread_id = state.get('thread_id')
        
        # Prepare messages with thread_id context if available
        messages = state['messages'].copy()
        
        # If thread_id is available, add it as a system message for context
        if thread_id:
            from langchain_core.messages import SystemMessage
            thread_context = SystemMessage(content=f"CONTEXT: Current thread_id is {thread_id}. Always pass this thread_id parameter when calling tools that require file access (such as file_status, get_files, etc.).")
            # Insert thread context before the system prompt
            # Find the last system message and insert after it, or insert at the beginning
            sys_msg_index = -1
            for i, msg in enumerate(messages):
                if isinstance(msg, SystemMessage):
                    sys_msg_index = i
            
            if sys_msg_index >= 0:
                messages.insert(sys_msg_index + 1, thread_context)
            else:
                messages.insert(0, thread_context)
            
            self.logger.info(f"Injected thread_id context into messages: thread_id={thread_id}")
        else:
            self.logger.warning(f"No thread_id found in state - tools may not work correctly")
        
        # Set environment variables for MCP tools if thread_id is available
        if thread_id:
            import os
            os.environ["THREAD_ID"] = thread_id
            os.environ["VITESS_THREAD_ID"] = thread_id
            self.logger.info(f"Set environment variables: THREAD_ID={thread_id}, VITESS_THREAD_ID={thread_id}")
        
        # Use LLM with tools for enhanced functionality
        try:
            response = self.llm.invoke(messages)
            self.logger.info("LLM response received successfully")
        except Exception as e:
            self.logger.error(f"LLM invocation failed: {e}")
            response = None
        
        if not response:
            self.logger.error("No response from LLM, returning error state")
            return {
                'module_stage': FillingStage(stage='error'),
                'validation_status': False,
                'error_message': "Failed to get LLM response"
            }
        
        # Always add the AI response to messages first
        updated_messages = state['messages'] + [response]
        self.logger.info(f"Updated messages count after adding response: {len(updated_messages)}")
        
        # Check for tool calls
        has_tool_calls = hasattr(response, 'tool_calls') and response.tool_calls
        self.logger.info(f"Tool calls detected: {has_tool_calls}")
        
        if has_tool_calls:
            self.logger.info("Routing to tools node")
            return {
                'messages': updated_messages,
                'module_stage': FillingStage(stage='processing'),
                'error_message': None
            }
        else:
            self.logger.info("No tool calls, getting user input")
            user_input = interrupt(f"{response.content}\n")
            self.logger.info("Interrupt triggered for user input in parameters configuration")
            self.logger.info(f"User input received: {user_input[:50]}{'...' if len(user_input) > 50 else ''}")
            
            final_messages = updated_messages + [HumanMessage(content=user_input)]
            self.logger.info(f"Final messages count after user input: {len(final_messages)}")
            
            return {
                'messages': final_messages,
                'module_stage': FillingStage(stage='processing'),
                'error_message': None
            }
    
    def default_params_config_node(self, state: UnifiedState) -> dict:
        """Default parameters configuration node with tool support"""
        return self._params_config_node(state, 'Default Setup')
    
    def custom_params_config_node(self, state: UnifiedState) -> dict:
        """Custom parameters configuration node with tool support"""
        config_mode = state.get('config_mode', 'Customize')
        return self._params_config_node(state, config_mode)
    
    def tools_node(self, state: UnifiedState) -> dict:
        """Tools execution node - handles MCP tool calls"""
        if not self.tools:
            self.logger.warning("No tools available, skipping tools node")
            return state
        
        self.logger.info(f"Executing tools for {self.name}")
        
        # Get the last message which should contain tool calls
        last_message = state['messages'][-1]
        if not (hasattr(last_message, 'tool_calls') and last_message.tool_calls):
            self.logger.warning("No tool calls found in last message")
            return state
        
        # Execute tools (this would be handled by ToolNode in the actual graph)
        # For now, we'll just log and return
        self.logger.info(f"Executing {len(last_message.tool_calls)} tool calls")
        
        return {
            'module_stage': FillingStage(stage='processing'),
            'error_message': None
        }
    
    def finalize_node(self, state: UnifiedState) -> dict:
        """Finalization node - processes final results"""
        self.logger.info(f"Entering {self.name} finalization")
        
        final_message = f"{self.get_completion_message(state)}"
        
        # Process the last message to extract results
        last_message = state['messages'][-1].content
        try:
            import json
            parsed_result = json.loads(last_message)
            validation_status = parsed_result.get('validation_status', True)
            
            self.logger.info(f"CLI parameters: {parsed_result.get('cli_parameters', 'None')}")
            
            # Create module result
            module_result = ModuleResult(
                module_name=self.module_name,
                status=ModuleStatus.COMPLETED,
                parameters=parsed_result.get('validated_params', {}),
                cli_parameters=parsed_result.get('cli_parameters', ''),
                thread_id=state.get('thread_id'),
                user_id=state.get('user_id')
            )
            
            # Update state with module result
            updated_results = state.get('module_results', {}).copy()
            updated_results[self.module_name] = module_result
            
            # Create completion message with module name in metadata for proper display
            completion_ai_message = AIMessage(
                content=final_message, 
                additional_kwargs={"module_name": self.module_name}
            )
            
            return {
                'messages': state.get('messages', []) + [completion_ai_message],
                'current_module': self.module_name,  # Set current_module in state for proper routing
                'module_stage': FillingStage(stage='completed'),
                'validation_status': validation_status,
                'error_message': None,
                'parameters': parsed_result.get('validated_params', {}),
                'cli_parameters': parsed_result.get('cli_parameters', ''),
                'module_results': updated_results
            }
        
        except Exception as e:
            error_msg = f"Failed to parse final result: {str(e)}"
            self.logger.error(error_msg)
            return {
                'module_stage': FillingStage(stage='error'),
                'validation_status': False,
                'error_message': error_msg
            }
    
    # =================
    # GRAPH CREATION METHOD
    # =================
    
    def _create_base_graph(self) -> dict:
        """
        Create the base graph structure for this module.
        
        This method returns a dictionary containing the nodes and edges
        that define the module's workflow.
        
        Returns:
            dict: Dictionary with 'nodes' and 'edges' keys
        """
        from langgraph.prebuilt import ToolNode
        
        # Define all nodes for this module
        nodes = {
            f"{self.module_name}_welcome": self.welcome_node,
            f"{self.module_name}_welcome_interrupt": self.welcome_interrupt_node,
            f"{self.module_name}_default_setup": self.default_setup_node,
            f"{self.module_name}_customize_setup": self.customize_setup_node,
            f"{self.module_name}_default_params_config": self.default_params_config_node,
            f"{self.module_name}_custom_params_config": self.custom_params_config_node,
            f"{self.module_name}_finalize": self.finalize_node,
        }
        
        # Add tools node if tools are available
        if self.tools:
            nodes[f"{self.module_name}_tools"] = ToolNode(self.tools)
        
        # Define edges for this module
        edges = []
        
        # Welcome routing: first go from welcome to interrupt node, then branch
        edges.append({
            'type': 'direct',
            'source': f"{self.module_name}_welcome",
            'target': f"{self.module_name}_welcome_interrupt"
        })
        edges.append({
            'type': 'conditional',
            'source': f"{self.module_name}_welcome_interrupt",
            'condition': self.route_after_welcome
        })
        
        # Setup to params config - separate paths for default and custom
        edges.append({
            'type': 'direct',
            'source': f"{self.module_name}_default_setup",
            'target': f"{self.module_name}_default_params_config"
        })
        edges.append({
            'type': 'direct',
            'source': f"{self.module_name}_customize_setup",
            'target': f"{self.module_name}_custom_params_config"
        })
        
        # Params config routing - separate for default and custom
        edges.append({
            'type': 'conditional',
            'source': f"{self.module_name}_default_params_config",
            'condition': self.route_after_default_params_config
        })
        edges.append({
            'type': 'conditional',
            'source': f"{self.module_name}_custom_params_config",
            'condition': self.route_after_custom_params_config
        })
        
        # Tools routing if available
        if self.tools:
            edges.append({
                'type': 'conditional',
                'source': f"{self.module_name}_tools",
                'condition': self.route_after_tools
            })
        
        return {
            'nodes': nodes,
            'edges': edges
        }
    
    # =================
    # ROUTING FUNCTIONS
    # =================
    
    def route_after_welcome(self, state: UnifiedState) -> str:
        """Route after welcome based on config mode"""
        config_mode = state.get('config_mode', '')
        
        # If config_mode is invalid or unknown, default to Default Setup
        if not self.validate_config_mode(config_mode):
            self.logger.warning(f"Invalid config mode '{config_mode}', defaulting to 'Default Setup'")
            config_mode = 'Default Setup'
        
        # Map config modes to nodes
        if config_mode in ['Customize', 'Custom']:
            self.logger.info("Routing to customize setup")
            return f'{self.module_name}_customize_setup'
        elif config_mode == 'Default Setup':
            self.logger.info("Routing to default setup")
            return f'{self.module_name}_default_setup'
        else:
            # Even if still invalid, default to Default Setup to keep graph running
            self.logger.error(f"Unhandled config mode: {config_mode}, defaulting to Default Setup")
            return f'{self.module_name}_default_setup'
    
    def route_after_tools(self, state: UnifiedState) -> str:
        """Route after tool execution - routes back to correct params config based on config_mode"""
        if not self.tools:
            # Determine which params config node to route to based on config_mode
            config_mode = state.get('config_mode', '')
            if config_mode in ['Customize', 'Custom']:
                self.logger.warning("No tools available, routing to custom_params_config")
                return f'{self.module_name}_custom_params_config'
            else:
                self.logger.warning("No tools available, routing to default_params_config")
                return f'{self.module_name}_default_params_config'
        
        last_message = state['messages'][-1] if state.get('messages') else None
        if not last_message:
            # Determine which params config node to route to based on config_mode
            config_mode = state.get('config_mode', '')
            if config_mode in ['Customize', 'Custom']:
                self.logger.warning("No messages in state, routing to custom_params_config")
                return f'{self.module_name}_custom_params_config'
            else:
                self.logger.warning("No messages in state, routing to default_params_config")
                return f'{self.module_name}_default_params_config'
        
        last_message_content = last_message.content if hasattr(last_message, 'content') else str(last_message)
        
        try:
            import json
            parsed_message = json.loads(last_message_content)
            validation_status = parsed_message.get('validation_status', False)
            
            if validation_status:
                self.logger.info("Tool validation successful, routing to finalize")
                return f'{self.module_name}_finalize'
            else:
                # Route back to the correct params config node based on config_mode
                config_mode = state.get('config_mode', '')
                if config_mode in ['Customize', 'Custom']:
                    self.logger.info("Tool validation failed, routing back to custom_params_config")
                    return f'{self.module_name}_custom_params_config'
                else:
                    self.logger.info("Tool validation failed, routing back to default_params_config")
                    return f'{self.module_name}_default_params_config'
                
        except Exception as e:
            self.logger.error(f"Error parsing tool result: {str(e)}")
            # Route back to the correct params config node based on config_mode
            config_mode = state.get('config_mode', '')
            if config_mode in ['Customize', 'Custom']:
                return f'{self.module_name}_custom_params_config'
            else:
                return f'{self.module_name}_default_params_config'
    
    def _route_after_params_config(self, state: UnifiedState, config_mode: str) -> str:
        """Unified routing after parameters configuration based on tool calls
        
        Args:
            state: Current state
            config_mode: Configuration mode ('Default Setup' or 'Customize'/'Custom')
        """
        last_message = state['messages'][-1] if state.get('messages') else None
        
        # Determine which params config node to route back to based on config_mode
        if config_mode == 'Default Setup':
            params_config_node = f'{self.module_name}_default_params_config'
        else:
            params_config_node = f'{self.module_name}_custom_params_config'
        
        if not last_message:
            self.logger.warning(f"No messages in state, routing to {params_config_node}")
            return params_config_node
        
        # Check for tool calls only if tools are available
        has_tool_calls = (self.tools and 
                         hasattr(last_message, 'tool_calls') and 
                         last_message.tool_calls)
        
        if has_tool_calls:
            self.logger.info("Tool calls detected, routing to tools")
            return f'{self.module_name}_tools'
        else:
            mode_text = "default" if config_mode == 'Default Setup' else "custom"
            self.logger.info(f"Continuing {mode_text} parameter configuration")
            return params_config_node
    
    def route_after_default_params_config(self, state: UnifiedState) -> str:
        """Route after default parameters configuration based on tool calls"""
        return self._route_after_params_config(state, 'Default Setup')
    
    def route_after_custom_params_config(self, state: UnifiedState) -> str:
        """Route after custom parameters configuration based on tool calls"""
        config_mode = state.get('config_mode', 'Customize')
        return self._route_after_params_config(state, config_mode)


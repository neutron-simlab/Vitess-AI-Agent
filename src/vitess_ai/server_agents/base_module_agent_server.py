"""
Base Module Agent Server - Server-optimized base class for module agents

This class provides the foundation for server agents that use a flat graph
architecture with unified state management. Unlike the regular BaseModuleAgent,
this class is designed to work as individual nodes within a larger supervisor graph.
"""

import logging
from typing import List, Type, TypeVar, Generic, Optional
from abc import ABC, abstractmethod
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain.tools import BaseTool
from langgraph.types import interrupt
from vitess_ai.core.llms_providers import create_llm_with_fallback
from vitess_ai.schema.base import FillingStage

# Type variables for generic parameter types
R = TypeVar('R')  # For initial response types


class BaseModuleAgentServer(ABC, Generic[R]):
    """
    Abstract base class for server-optimized module agents.
    
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
        Initialize the base server agent
        
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
        self.logger.info(f"Initializing {self.name} server agent with model {model}")
        if tools:
            self.logger.info(f"Loaded {len(tools)} MCP tools")
        
        # Setup agent-specific configurations
        self._setup_prompts()
        self._setup_llm()
        
        self.logger.info(f"{self.name} server agent initialization completed")
    
    def _setup_logging(self):
        """Setup logging for the server agent"""
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
            from vitess_ai.agents.base_module_agent import ModuleStatus
            
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
        self.sys_prompt = SystemMessage(content=self.system_prompt)
        
    
    def _setup_llm(self):
        """Setup LLM with tools if available"""
        if self.tools:
            self.llm = self.llm.bind_tools(self.tools, parallel_tool_calls=False)
    
    # =================
    # FLAT GRAPH NODE IMPLEMENTATIONS
    # =================
    
    def welcome_node(self, state: dict) -> dict:
        """Welcome node for the module - emits welcome message only"""
        self.logger.info(f"Starting {self.name} welcome interaction")
        
        # Set current module in state
        state["current_module"] = self.module_name
        state["module_stage"] = FillingStage(stage='processing')
        
        # Create welcome message without decorative header - Streamlit app handles styling
        welcome_text = f"{self.welcome_message}"
        welcome = AIMessage(content=welcome_text, additional_kwargs={"module_name": self.module_name})
        
        # Prepend the module system prompt so the LLM has correct context
        return {
            **state,
            'messages': state.get('messages', []) + [self.sys_prompt, welcome],
            'error_message': None
        }

    def welcome_interrupt_node(self, state: dict) -> dict:
        """Interrupt node to collect initial choice and parse it"""
        self.logger.info(f"Triggering interrupt for {self.name} initial choice")
        
        # Instruction for parsing user response
        instruction_message = SystemMessage(content=f"""
        Parse the user's response to determine their configuration choice.
        Valid options: {', '.join(self.get_valid_config_modes())}
        
        ❌ **Not Known**: When the user's input does not clearly indicate a choice 
        between the valid options (e.g., unrelated topics, ambiguous language)
        """)
        
        # Trigger interrupt (welcome already in messages)
        user_input = interrupt("Please choose: Default Setup or Customize")
        self.logger.info(f"User input received: {user_input[:50]}{'...' if len(user_input) > 50 else ''}")
        
        messages = state.get('messages', []) + [instruction_message, HumanMessage(content=user_input)]
        
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
            **state,
            'messages': messages,
            'config_mode': config_mode,
            'validation_status': None,
            'error_message': None
        }
    
    def default_setup_node(self, state: dict) -> dict:
        """Default setup node"""
        self.logger.info(f"Entering {self.name} default setup configuration")
        
        setup_message = f"\n=== HANDLING DEFAULT SETUP CONFIGURATION for {self.name} ==="
        sys_default_message = SystemMessage(content=self.get_default_setup_message())
        
        return {
            **state,
            'messages': state.get('messages', []) + [AIMessage(content=setup_message), sys_default_message],
            'module_stage': FillingStage(stage='processing'),
            'error_message': None
        }
    
    def customize_setup_node(self, state: dict) -> dict:
        """Customize setup node"""
        self.logger.info(f"Entering {self.name} customized configuration")
        
        setup_message = f"\n=== HANDLING CUSTOMIZED CONFIGURATION for {self.name} ==="
        sys_customize_message = SystemMessage(content=self.get_customize_setup_message())
        
        return {
            **state,
            'messages': state.get('messages', []) + [AIMessage(content=setup_message), sys_customize_message],
            'module_stage': FillingStage(stage='processing'),
            'error_message': None
        }
    
    def parameters_config_node(self, state: dict) -> dict:
        """Parameters configuration node with tool support"""
        self.logger.info(f"Entering {self.name} parameters configuration")
        
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
                **state,
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
                **state,
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
                **state,
                'messages': final_messages,
                'module_stage': FillingStage(stage='processing'),
                'error_message': None
            }
    
    def tools_node(self, state: dict) -> dict:
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
            **state,
            'module_stage': FillingStage(stage='processing'),
            'error_message': None
        }
    
    def finalize_node(self, state: dict) -> dict:
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
            from vitess_ai.agents.base_module_agent import ModuleResult, ModuleStatus
            
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
                **state,
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
                **state,
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
        that define the module's workflow. This is similar to the method
        in BaseModuleAgent but adapted for server mode with UnifiedState.
        
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
            f"{self.module_name}_params_config": self.parameters_config_node,
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
        
        # Setup to params config
        edges.append({
            'type': 'direct',
            'source': f"{self.module_name}_default_setup",
            'target': f"{self.module_name}_params_config"
        })
        edges.append({
            'type': 'direct',
            'source': f"{self.module_name}_customize_setup",
            'target': f"{self.module_name}_params_config"
        })
        
        # Params config routing
        edges.append({
            'type': 'conditional',
            'source': f"{self.module_name}_params_config",
            'condition': self.route_after_params_config
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
    
    def route_after_welcome(self, state: dict) -> str:
        """Route after welcome based on config mode"""
        config_mode = state.get('config_mode', '')
        self.logger.info(f"Routing after welcome with config_mode: {config_mode}")
        
        if not self.validate_config_mode(config_mode):
            self.logger.warning(f"Invalid config mode '{config_mode}', ending conversation")
            return "error"
        
        # Map config modes to nodes
        if config_mode in ['Customize', 'Custom']:
            self.logger.info("Routing to customize setup")
            return f'{self.module_name}_customize_setup'
        elif config_mode == 'Default Setup':
            self.logger.info("Routing to default setup")
            return f'{self.module_name}_default_setup'
        else:
            self.logger.error(f"Unhandled config mode: {config_mode}")
            return "error"
    
    def route_after_tools(self, state: dict) -> str:
        """Route after tool execution"""
        if not self.tools:
            self.logger.warning("No tools available, routing to params_config")
            return f'{self.module_name}_params_config'
        
        last_message = state['messages'][-1].content
        self.logger.info("Processing tool execution results")
        
        try:
            import json
            parsed_message = json.loads(last_message)
            validation_status = parsed_message.get('validation_status', False)
            
            if validation_status:
                self.logger.info("Tool validation successful, routing to finalize")
                return f'{self.module_name}_finalize'
            else:
                self.logger.info("Tool validation failed, routing back to params_config")
                return f'{self.module_name}_params_config'
                
        except Exception as e:
            self.logger.error(f"Error parsing tool result: {str(e)}")
            return f'{self.module_name}_params_config'
    
    def route_after_params_config(self, state: dict) -> str:
        """Route after parameters configuration based on tool calls"""
        last_message = state['messages'][-1]
        
        # Check for tool calls only if tools are available
        if (self.tools and 
            hasattr(last_message, 'tool_calls') and 
            last_message.tool_calls):
            self.logger.info('Tool calls detected, routing to tools')
            return f'{self.module_name}_tools'
        else:
            self.logger.info('Continuing parameter configuration')
            return f'{self.module_name}_params_config'

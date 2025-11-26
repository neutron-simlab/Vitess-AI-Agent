"""
Supervisor Agent - Flat graph architecture

This supervisor agent uses a flat graph architecture where all module nodes
are added directly to the supervisor graph, enabling unified state management
and centralized interrupt handling.
"""

import logging
import json
import time
from typing import Dict, List, Any, Optional, Type
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from vitess_ai.core.llms_providers import create_llm_with_fallback
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode

from vitess_ai.schema.supervisor import (
    SupervisorConfig, SupervisorStage, 
    SupervisorStatus, ConfigurationExport
)
from vitess_ai.core.registry import ModuleRegistry
from vitess_ai.server_agents.base_module_agent import (
    BaseModuleAgent,
    ModuleBuilder, 
    ModuleStatus, 
    ModuleMetadata,
)
from vitess_ai.server_agents.unified_state import UnifiedState
from vitess_ai.core.config import global_config
from vitess_ai.prompts.supervisor import get_simulation_execution_prompt, get_post_simulation_response_prompt


class SupervisorAgent:
    """
    Supervisor agent with flat graph architecture.
    
    This agent creates a flat graph where all module nodes are added directly
    to the supervisor graph, enabling unified state management and centralized
    interrupt handling.
    """
    
    def __init__(self, config: SupervisorConfig = None, simulation_tools_path: str = None):
        """Initialize the supervisor agent"""
        self.config = config or self._create_default_config()
        self.llm = create_llm_with_fallback(provider=self.config.provider, model=self.config.model)
        # Create unbound LLM for post-simulation responses (no tools needed)
        self.response_llm = create_llm_with_fallback(provider=self.config.provider, model=self.config.model)
        self.registry = ModuleRegistry()
        
        # Simulation tools configuration
        self.simulation_tools_path = simulation_tools_path or "src/vitess_ai/mcp/supervisor_tools.py"
        self.simulation_tools = []
        
        # Runtime components
        self.agent_instances: Dict[str, BaseModuleAgent] = {}
        self.graph: Optional[StateGraph] = None
        self.app = None
        self.memory = InMemorySaver()
        self.initialized = False
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        self._setup_logging()
        self.logger.info("Supervisor agent initialized with logging enabled")
    
    def _create_default_config(self) -> SupervisorConfig:
        """Create default supervisor configuration"""
        return SupervisorConfig(
            provider=global_config.DEFAULT_PROVIDER,
            model=global_config.DEFAULT_MODEL
        )
    
    def _setup_logging(self):
        """Setup logging for the supervisor agent"""
        logger_name = f"vitess_ai.server_agents.supervisor"
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
    # CLI TOOLS SETUP
    # =================
    
    async def _setup_simulation_tools(self):
        """Setup simulation execution MCP tools"""
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            import os
            
            # Prepare environment variables for MCP subprocess
            env = os.environ.copy()
            
            client = MultiServerMCPClient({
                "simulation_runner": {
                    "command": "python",
                    "args": [self.simulation_tools_path],
                    "transport": "stdio",
                    "env": env  # Pass environment variables to subprocess
                }
            })
            self.simulation_tools = await client.get_tools()
            self.logger.info(f"Loaded {len(self.simulation_tools)} simulation tools")
            self.logger.debug(f"Simulation MCP client created with environment variables: THREAD_ID={env.get('THREAD_ID', 'not set')}, VITESS_THREAD_ID={env.get('VITESS_THREAD_ID', 'not set')}")
            
            # Bind tools to LLM
            if self.simulation_tools:
                self.llm = self.llm.bind_tools(self.simulation_tools, parallel_tool_calls=False)
                
        except Exception as e:
            self.logger.warning(f"Failed to load simulation tools: {e}")
            self.simulation_tools = []
    
    # =================
    # MODULE REGISTRATION API
    # =================
    
    def register_module(self, module_metadata: ModuleMetadata) -> None:
        """Register a new module with the supervisor"""
        self.registry.register_module(module_metadata)
        
        # Invalidate graph if already built
        if self.initialized:
            self.logger.info("New module registered, graph will be rebuilt on next run")
            self.initialized = False
    
    def unregister_module(self, module_name: str) -> bool:
        """Unregister a module"""
        result = self.registry.unregister_module(module_name)
        
        # Clean up agent instance
        if module_name in self.agent_instances:
            del self.agent_instances[module_name]
        
        # Invalidate graph
        if self.initialized:
            self.initialized = False
            
        return result
    
    def list_modules(self) -> List[Dict[str, Any]]:
        """List all registered modules with their info"""
        return self.registry.get_modules_info()
    
    def get_execution_plan(self, requested_modules: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get the execution plan for modules"""
        plan = self.registry.get_execution_plan(requested_modules)
        return plan.model_dump()
    
    # =================
    # BUILT-IN MODULE BUILDERS - Convenience methods
    # =================
    
    def add_readin_module(self, config_path: str = None) -> None:
        """Add the standard readin module"""
        from vitess_ai.server_agents.readin_module_agent import ReadInModuleAgent
        
        module = ModuleBuilder.create(
            name="readin",
            display_name="Read-in Parameters",
            description="Configure neutron input parameters and initial conditions",
            agent_class=ReadInModuleAgent,  # Use agent class
            config_path=config_path or global_config.READIN_MCP_PATH,
            order=1
        )
        self.register_module(module)
    
    def add_guide_module(self, config_path: str = None) -> None:
        """Add the standard guide module"""  
        from vitess_ai.server_agents.guide_module_agent import GuideModuleAgent
        
        module = ModuleBuilder.create(
            name="guide",
            display_name="Guide Parameters", 
            description="Configure neutron guide specifications and geometry",
            agent_class=GuideModuleAgent,  # Use agent class
            config_path=config_path or global_config.GUIDE_MCP_PATH,
            order=2
        )
        self.register_module(module)
    
    def add_writeout_module(self, config_path: str = None) -> None:
        """Add the standard writeout module"""
        from vitess_ai.server_agents.writeout_module_agent import WriteoutModuleAgent
        
        module = ModuleBuilder.create(
            name="writeout",
            display_name="Writeout Parameters",
            description="Configure output settings and data formats", 
            agent_class=WriteoutModuleAgent,  # Use agent class
            config_path=config_path or global_config.WRITEOUT_MCP_PATH,
            order=3
        )
        self.register_module(module)
    
    def add_monitor1d_module(self, config_path: str = None) -> None:
        """Add the Monitor1D module"""
        from vitess_ai.server_agents.monitor1d_module_agent import Monitor1DModuleAgent
        
        module = ModuleBuilder.create(
            name="monitor1d",
            display_name="Monitor1D Parameters",
            description="Configure 1D monitor parameters for neutron detection",
            agent_class=Monitor1DModuleAgent,  # Use agent class
            config_path=config_path or global_config.MONITOR_MCP_PATH,
            order=4
        )
        self.register_module(module)
    
    def add_monitor2d_module(self, config_path: str = None) -> None:
        """Add the Monitor2D module"""
        from vitess_ai.server_agents.monitor2d_module_agent import Monitor2DModuleAgent
        
        module = ModuleBuilder.create(
            name="monitor2d",
            display_name="Monitor2D Parameters",
            description="Configure 2D monitor parameters for neutron detection",
            agent_class=Monitor2DModuleAgent,  # Use agent class
            config_path=config_path or global_config.MONITOR_MCP_PATH,
            order=5
        )
        self.register_module(module)
    
    def add_custom_module(
        self,
        name: str,
        display_name: str,
        description: str,
        agent_class: Type[BaseModuleAgent],  # Use agent class
        order: int,
        config_path: str = None,
        optional: bool = False
    ) -> None:
        """Add a custom module using the built-in builder"""
        module = ModuleBuilder.create(
            name=name,
            display_name=display_name,
            description=description,
            agent_class=agent_class,
            config_path=config_path,
            optional=optional,
            order=order
        )
        self.register_module(module)
    
    def add_default_modules(self) -> None:
        """Add all default modules (readin, guide, writeout)"""
        self.add_readin_module()
        self.add_guide_module()
        # self.add_monitor1d_module()  # Deactivated
        # self.add_monitor2d_module()  # Deactivated
        self.add_writeout_module()
    
    # =================
    # AGENT INITIALIZATION
    # =================
    
    async def _setup_agent_instance(self, module_name: str) -> BaseModuleAgent:
        """Setup an agent instance for a module"""
        if module_name in self.agent_instances:
            return self.agent_instances[module_name]
        
        module_metadata = self.registry.get_module(module_name)
        if not module_metadata:
            raise ValueError(f"Module '{module_name}' not registered")
        
        # Setup MCP tools if config path provided
        tools = []
        if module_metadata.config_path:
            try:
                from langchain_mcp_adapters.client import MultiServerMCPClient
                import os
                
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
                tools = await client.get_tools()
                self.logger.info(f"Loaded {len(tools)} MCP tools for {module_name}")
                self.logger.debug(f"MCP client created with environment variables: THREAD_ID={env.get('THREAD_ID', 'not set')}, VITESS_THREAD_ID={env.get('VITESS_THREAD_ID', 'not set')}")
            except Exception as e:
                self.logger.warning(f"Failed to load MCP tools for {module_name}: {e}")
        
        # Create agent instance
        agent = module_metadata.agent_class(
            provider=self.config.provider, 
            model=self.config.model, 
            tools=tools
        )
        
        self.agent_instances[module_name] = agent
        
        self.logger.info(f"Initialized agent for module: {module_name}")
        return agent
    
    async def initialize(self, requested_modules: Optional[List[str]] = None, force_reinitialize: bool = False):
        """Initialize the supervisor with the requested modules
        
        Args:
            requested_modules: Optional list of module names to include
            force_reinitialize: If True, reinitialize even if already initialized
        """
        if self.initialized and not force_reinitialize:
            self.logger.info("Supervisor already initialized")
            return
        
        # If forcing reinitialize, reset the initialized state and clear old components
        if force_reinitialize:
            self.logger.info("Force reinitializing supervisor...")
            self.initialized = False
            # Clear agent instances to force recreation with new LLM config
            self.agent_instances.clear()
            self.graph = None
            self.app = None
        
        self.logger.info("Initializing Supervisor...")
        
        # Setup simulation tools first
        await self._setup_simulation_tools()
        
        # Basic validation 
        issues = self.registry.validate_modules()
        if issues:
            self.logger.warning(f"Module validation issues: {issues}")
        
        # Get execution order
        try:
            execution_order = self.registry.get_execution_order(requested_modules)
            self.logger.info(f"Execution order: {execution_order}")
        except Exception as e:
            raise ValueError(f"Failed to get execution order: {e}")
        
        # Setup agent instances for all modules in execution order
        for module_name in execution_order:
            await self._setup_agent_instance(module_name)
        
        # Create and compile flat graph
        self.graph = self._create_flat_graph(execution_order)
        # Compile with checkpointer for state persistence (LangGraph 1.x compatible)
        # Note: For enhanced control, consider using static interrupts:
        #   self.app = self.graph.compile(
        #       checkpointer=self.memory,
        #       interrupt_before=["node_name"],  # Interrupt before specific nodes
        #       interrupt_after=["node_name"]     # Interrupt after specific nodes
        #   )
        self.app = self.graph.compile(checkpointer=self.memory)
        
        self.initialized = True
        self.logger.info(f"Supervisor initialized with {len(execution_order)} modules and simulation tools")
    
    async def restart_with_new_config(self, provider: str = None, model: str = None, requested_modules: Optional[List[str]] = None, clear_state: bool = True):
        """Restart the supervisor graph with new provider/model configuration
        
        Args:
            provider: New provider to use (optional, uses current if not provided)
            model: New model to use (optional, uses current if not provided)
            requested_modules: Optional list of module names to include
            clear_state: If True, clear all conversation state/memory (default: True)
        """
        self.logger.info(f"Restarting supervisor with new config: provider={provider}, model={model}, clear_state={clear_state}")
        
        # Update config if provided
        if provider is not None:
            self.config.provider = provider
        if model is not None:
            self.config.model = model
        
        # Update LLM instances with new config
        self.llm = create_llm_with_fallback(provider=self.config.provider, model=self.config.model)
        self.response_llm = create_llm_with_fallback(provider=self.config.provider, model=self.config.model)
        
        self.logger.info(f"Updated LLM instances: provider={self.config.provider}, model={self.config.model}")
        
        # Clear conversation state if requested (create new memory checkpointer)
        if clear_state:
            self.logger.info("Clearing conversation state/memory for fresh start")
            self.memory = InMemorySaver()
        
        # Force reinitialize the graph with new LLM config
        await self.initialize(requested_modules=requested_modules, force_reinitialize=True)
        
        self.logger.info("Supervisor graph restarted successfully with new configuration")
    
    # =================
    # FLAT GRAPH CREATION
    # =================
    
    def _create_flat_graph(self, execution_order: List[str]) -> StateGraph:
        """Create a flat graph with all module nodes added directly"""
        workflow = StateGraph(UnifiedState)
        
        # Add supervisor nodes
        workflow.add_node("supervisor_welcome", self._welcome_node)
        workflow.add_node("supervisor_prepare_simulation", self._prepare_simulation_node)
        workflow.add_node("supervisor_run_simulation", self._run_simulation_node)
        workflow.add_node("supervisor_post_simulation_response", self._post_simulation_response_node)
        workflow.add_node("supervisor_completion", self._completion_node)
        workflow.add_node("supervisor_error_handler", self._error_handler_node)
        
        # Add simulation tools node if available
        if self.simulation_tools:
            workflow.add_node("supervisor_simulation_tools", ToolNode(self.simulation_tools))
        
        # Add module nodes and edges for each module in execution order
        for module_name in execution_order:
            agent = self.agent_instances[module_name]
            
            # Use the _create_base_graph() method to get the graph structure
            module_graph = agent._create_base_graph()
            
            # Add all nodes from the module graph to the main workflow
            for node_name, node_func in module_graph['nodes'].items():
                workflow.add_node(node_name, node_func)
            
            # Add module-specific edges with proper routing
            # Wire welcome -> interrupt, then conditional routing from interrupt
            workflow.add_edge(f"{module_name}_welcome", f"{module_name}_welcome_interrupt")
            workflow.add_conditional_edges(
                f"{module_name}_welcome_interrupt", 
                lambda state, mn=module_name: self._route_module_welcome(state, mn)
            )
            
            # Setup to params config - separate paths for default and custom
            workflow.add_edge(f"{module_name}_default_setup", f"{module_name}_default_params_config")
            workflow.add_edge(f"{module_name}_customize_setup", f"{module_name}_custom_params_config")
            
            # Params config routing - separate for default and custom
            workflow.add_conditional_edges(
                f"{module_name}_default_params_config",
                lambda state, mn=module_name: self._route_module_default_params_config(state, mn)
            )
            workflow.add_conditional_edges(
                f"{module_name}_custom_params_config",
                lambda state, mn=module_name: self._route_module_custom_params_config(state, mn)
            )
            
            # Tools routing if available
            if agent.tools:
                workflow.add_conditional_edges(
                    f"{module_name}_tools",
                    lambda state, mn=module_name: self._route_module_tools(state, mn)
                )
            
            # Finalize routing to next module or simulation
            workflow.add_conditional_edges(
                f"{module_name}_finalize",
                lambda state, mn=module_name: self._route_module_finalize(state, mn)
            )
        
        # Add supervisor edges
        workflow.add_edge(START, "supervisor_welcome")
        workflow.add_conditional_edges("supervisor_welcome", self._route_from_welcome)
        
        # Simulation execution routing
        workflow.add_edge("supervisor_prepare_simulation", "supervisor_run_simulation")
        workflow.add_conditional_edges("supervisor_run_simulation", self._route_from_simulation)
        if self.simulation_tools:
            workflow.add_conditional_edges("supervisor_simulation_tools", self._route_after_simulation_tools)
            workflow.add_conditional_edges("supervisor_post_simulation_response", self._route_after_post_simulation_response)

        workflow.add_edge("supervisor_completion", END)
        workflow.add_edge("supervisor_error_handler", END)
        
        return workflow
    
    # =================
    # SUPERVISOR NODE IMPLEMENTATIONS
    # =================
    
    def _welcome_node(self, state: UnifiedState) -> dict:
        """Welcome node with dynamic module information"""
        self.logger.info("Supervisor welcome node triggered.")
        
        # Get thread_id and user_id from state (set in initial input)
        thread_id = state.get('thread_id')
        user_id = state.get('user_id')
        
        # Set environment variables for MCP tools if thread_id is available
        if thread_id:
            import os
            os.environ["THREAD_ID"] = thread_id
            os.environ["VITESS_THREAD_ID"] = thread_id
            self.logger.info(f"Using thread_id from state: {thread_id} and set environment variables")
            self.logger.debug(f"Environment variables set: THREAD_ID={os.environ.get('THREAD_ID')}, VITESS_THREAD_ID={os.environ.get('VITESS_THREAD_ID')}")
        else:
            self.logger.warning("No thread_id found in state - MCP tools may not work correctly")
        
        # Show available modules
        modules_info = []
        execution_order = self.registry.get_execution_order()
        
        for module_name in execution_order:
            module_metadata = self.registry.get_module(module_name)
            if module_metadata:
                optional_text = " (optional)" if module_metadata.optional else ""
                modules_info.append(f"{module_metadata.order}. **{module_metadata.display_name}**{optional_text}: {module_metadata.description}")
        
        simulation_info = f"\n **Simulation Execution**: Automatic execution of configured simulation" if self.simulation_tools else ""
        
        welcome_text = self.config.welcome_message + "\n\n**Available Modules:**\n" + "\n".join(modules_info) + "\n" + simulation_info 
        
        # Return welcome message in messages for streaming
        # Preserve thread_id and user_id from state
        return {
            'messages': [
                AIMessage(content=welcome_text)
            ],
            'current_stage': SupervisorStage.MODULE_EXECUTION,
            'execution_order': execution_order,
            'pending_modules': execution_order.copy(),
            'module_results': {},
            'thread_id': thread_id or "",
            'user_id': user_id or "",
            'cli_generation_ready': False,
            'error_message': None,
        }
    
    def _prepare_simulation_node(self, state: UnifiedState) -> dict:
        """Prepare simulation node - emits the 'starting simulation' message before execution"""
        self.logger.info("Preparing simulation execution - showing start message")
        
        # Extract module results from state
        module_results = state.get('module_results', {})
        execution_order = state.get('execution_order', [])
        
        # Create user-visible message indicating simulation execution is starting
        completed_modules = [name for name, result in module_results.items() 
                             if result.status == ModuleStatus.COMPLETED]
        simulation_start_message = f"""
{'='*3}
**STARTING SIMULATION EXECUTION**
{'='*3}

All modules have been configured successfully:
"""
        for module_name in completed_modules:
            module_metadata = self.registry.get_module(module_name)
            if module_metadata:
                simulation_start_message += f"   • {module_metadata.display_name}\n"

        simulation_start_message += f"""
**Execution Order**: {' → '.join(execution_order)}

**Executing simulation** with the configured parameters...

"""
        
        # Add the start message to state immediately so it streams before tool execution
        start_ai_message = AIMessage(content=simulation_start_message)
        
        return {
            'messages': state.get('messages', []) + [start_ai_message],
            'current_module': 'supervisor'  # Mark as supervisor message for proper display
        }
    
    def _run_simulation_node(self, state: UnifiedState) -> dict:
        """Simulation execution node - runs simulation directly using module results
        
        This node includes timeout protection to prevent hanging with Blablador:
        - Specifically catches timeout errors
        - Provides informative error messages if timeout occurs
        - Falls back gracefully if LLM invocation fails
        """
        self.logger.info("Entering simulation execution phase")
        
        # Extract module results from state
        module_results = state.get('module_results', {})
        execution_order = state.get('execution_order', [])
        
        # Create system message for simulation execution
        simulation_prompt = get_simulation_execution_prompt(module_results, execution_order)
        simulation_system_prompt = SystemMessage(content=simulation_prompt)

        messages = [simulation_system_prompt]
        timeout = getattr(self.llm, 'timeout', global_config.TIMEOUT_SECONDS)
        msg_count = len(messages)
        response = None
        
        try:
            # Enhanced logging for LLM invocation
            self.logger.info(f"Invoking LLM for simulation execution: {msg_count} messages, timeout={timeout}s, provider={self.config.provider}, model={self.config.model}")
            start_time = time.time()
            
            response = self.llm.invoke(messages)
            
            duration = time.time() - start_time
            self.logger.info(f"LLM invocation completed successfully in {duration:.2f}s")
            
        except TimeoutError as e:
            duration = time.time() - start_time if 'start_time' in locals() else 0
            self.logger.error(f"LLM invocation timed out after {duration:.2f}s (timeout={timeout}s): {e}")
            error_message = AIMessage(content=f"Error during simulation execution: The LLM request timed out after {timeout} seconds. This may indicate network issues or the model is overloaded. Please try again.")
            response = error_message
        except Exception as e:
            duration = time.time() - start_time if 'start_time' in locals() else 0
            error_type = type(e).__name__
            # Check if it's a timeout-related error
            if 'timeout' in str(e).lower() or 'timed out' in str(e).lower():
                self.logger.error(f"LLM invocation timed out after {duration:.2f}s: {e}")
                error_message = AIMessage(content=f"Error during simulation execution: The LLM request timed out after approximately {duration:.0f} seconds. This may indicate network issues or the model is overloaded. Please try again.")
            else:
                self.logger.error(f"LLM invocation failed after {duration:.2f}s ({error_type}): {e}", exc_info=True)
                error_message = AIMessage(content=f"Error during simulation execution: {str(e)}")
            response = error_message

        # Update messages: Add system prompt and LLM response (start message already added in prepare node)
        updated_messages = state.get('messages', []) + messages + [response] if response else state.get('messages', []) + messages

        return {
            'messages': updated_messages,
            'current_module': 'supervisor'  # Mark as supervisor message for proper display
        }
    
    def _completion_node(self, state: UnifiedState) -> dict:
        """Enhanced completion node with CLI information and simulation execution summary"""
        
        # Generate summary
        module_results = state.get('module_results', {})
        completed_modules = [name for name, result in module_results.items() 
                           if result.status == ModuleStatus.COMPLETED]
        
        # Check if simulation was executed by looking for simulation finish status
        simulation_executed = state.get('simulation_finish', False)
        
        completion_message = f"""
{'='*3}
**VITESS SIMULATION CONFIGURATION COMPLETED**
{'='*3}

**CONFIGURATION SUMMARY:**
Completed modules: {len(completed_modules)}
"""
        
        for module_name in completed_modules:
            module_metadata = self.registry.get_module(module_name)
            if module_metadata:
                completion_message += f"   {module_metadata.order}. {module_metadata.display_name}\n"
        
        # Add simulation execution status if applicable
        if simulation_executed:
            completion_message += f"""
{'='*3}
**SIMULATION EXECUTION**
{'='*3}

Simulation has been executed successfully with the configured parameters.

All configuration and execution steps are complete!
"""
        else:
            completion_message += f"""
{'='*3}
**NEXT STEPS**
{'='*3}

Configuration is complete. The simulation parameters are ready for execution.
"""
        
        # Return completion message in messages for streaming
        return {
            'current_stage': SupervisorStage.COMPLETION,
            'error_message': None,
            'current_module': 'supervisor',  # Mark as supervisor message for proper display
            'messages': state.get('messages', []) + [AIMessage(content=completion_message)]
        }
    
    def _error_handler_node(self, state: UnifiedState) -> dict:
        """Error handler node"""
        error_msg = state.get('error_message', 'Unknown error occurred')
        
        # Get current module from execution order if available
        execution_order = state.get('execution_order', [])
        current_module = execution_order[-1] if execution_order else 'unknown'
        
        error_message = f"""
❌ **ERROR in {current_module.upper()} module**
"""
        if error_msg and error_msg != 'None':
            error_message += f"Error: {error_msg}\n"
        else:
            error_message += "Error: Module execution failed with no specific error message\n"
        error_message += "Configuration process terminated."
        
        # Return error message in messages for streaming
        return {
            'current_stage': SupervisorStage.ERROR,
            'messages': state.get('messages', []) + [AIMessage(content=error_message)]
        }
    
    # =================
    # ROUTING FUNCTIONS
    # =================
    
    def _route_from_welcome(self, state: UnifiedState) -> str:
        """Route from welcome to first module or error"""
        if state.get('current_stage') == SupervisorStage.MODULE_EXECUTION:
            execution_order = state.get('execution_order', [])
            if execution_order:
                first_module = execution_order[0]
                return f"{first_module}_welcome"
        
        if state.get('current_stage') == SupervisorStage.ERROR:
            return "supervisor_error_handler"
        
        # If we're still in welcome stage, automatically proceed to module execution
        execution_order = self.registry.get_execution_order()
        if execution_order:
            first_module = execution_order[0]
            return f"{first_module}_welcome"
        
        return "supervisor_error_handler"  # No modules available
    
    def _route_module_welcome(self, state: UnifiedState, module_name: str) -> str:
        """Route from module welcome based on config mode"""
        agent = self.agent_instances[module_name]
        return agent.route_after_welcome(state)
    
    def _route_module_default_params_config(self, state: UnifiedState, module_name: str) -> str:
        """Route from module default params config based on tool calls"""
        agent = self.agent_instances[module_name]
        return agent.route_after_default_params_config(state)
    
    def _route_module_custom_params_config(self, state: UnifiedState, module_name: str) -> str:
        """Route from module custom params config based on tool calls"""
        agent = self.agent_instances[module_name]
        return agent.route_after_custom_params_config(state)
    
    def _route_module_tools(self, state: UnifiedState, module_name: str) -> str:
        """Route from module tools based on validation status"""
        agent = self.agent_instances[module_name]
        return agent.route_after_tools(state)
    
    def _route_module_finalize(self, state: UnifiedState, module_name: str) -> str:
        """Route from module finalize to next module or simulation"""
        execution_order = state.get('execution_order', [])
        module_results = state.get('module_results', {})
        
        try:
            current_index = execution_order.index(module_name)
            
            if current_index == len(execution_order) - 1:
                # Last module completed - go to simulation preparation
                self.logger.info("All modules completed, routing to simulation preparation")
                return "supervisor_prepare_simulation"
            else:
                # Route directly to next module (bypassing summarize)
                completed = [name for name, res in module_results.items() if getattr(res, 'status', None) == ModuleStatus.COMPLETED]
                # Find first module not completed
                next_module = None
                for mn in execution_order:
                    if mn not in completed:
                        next_module = mn
                        break
                if next_module is None:
                    return "supervisor_prepare_simulation"
                self.logger.info(f"Routing directly to next module: {next_module}")
                return f"{next_module}_welcome"
        except ValueError as e:
            self.logger.error(f"Module {module_name} not found in execution order: {execution_order}")
            return "supervisor_error_handler"
    
    def _route_from_simulation(self, state: UnifiedState) -> str:
        """Route from simulation execution based on tools availability"""
        last_message = state['messages'][-1]
        
        # Check for tool calls only if tools are available
        if (self.simulation_tools and 
            hasattr(last_message, 'tool_calls') and 
            last_message.tool_calls
            ):
            self.logger.info('Tool calls detected, routing to simulation tools')
            return "supervisor_simulation_tools"
    
        else: 
            self.logger.info("There is a problem with simulation tool calling, particularly with LLM can't understand the instruction.")
            return END
    
    def _route_after_simulation_tools(self, state: UnifiedState) -> str:
        """Route after simulation tools execution to post-simulation response node"""
        # Routing functions should not mutate state - just return next node
        self.logger.info("Routing to post-simulation response node")
        return 'supervisor_post_simulation_response'
    
    def _post_simulation_response_node(self, state: UnifiedState) -> dict:
        """Post-simulation response node - generates AI response after tool execution
        
        This node includes timeout protection to prevent hanging with Blablador:
        - Specifically catches timeout errors
        - Provides fallback messages if timeout occurs
        - Uses existing tool results to generate appropriate responses
        """
        self.logger.info("Generating AI response after simulation execution")
        
        # Extract tool result from the last message (should be a ToolMessage)
        messages = state.get('messages', [])
        last_message = messages[-1] if messages else None
        
        # Parse tool result from the last message
        tool_result = {}
        if last_message:
            if isinstance(last_message, ToolMessage):
                last_message_content = last_message.content
            elif hasattr(last_message, 'content'):
                last_message_content = last_message.content
            else:
                last_message_content = str(last_message)
            
            try:
                # Try to parse as JSON
                if isinstance(last_message_content, str):
                    tool_result = json.loads(last_message_content)
                elif isinstance(last_message_content, dict):
                    tool_result = last_message_content
                else:
                    tool_result = {}
                
                self.logger.info(f"Parsed tool result: {tool_result.get('simulation_finish', False)}")
            except (json.JSONDecodeError, TypeError) as e:
                self.logger.error(f"Failed to parse tool result: {e}")
                tool_result = {}
        
        # Store parsed result in state for future reference
        simulation_finish = tool_result.get('simulation_finish', False)
        execution_results = tool_result.get('execution_results', {})
        
        # Create system prompt for post-simulation response
        response_prompt = get_post_simulation_response_prompt(tool_result)
        system_message = SystemMessage(content=response_prompt)
        
        # Prepare LLM invocation with timeout protection
        recent_messages = messages[-5:] if len(messages) > 5 else messages
        llm_messages = [system_message] + recent_messages
        timeout = getattr(self.response_llm, 'timeout', global_config.TIMEOUT_SECONDS)
        response = None
        
        try:
            # Invoke unbound LLM (without tools) to generate response
            # Include recent conversation context (last few messages)
            msg_count = len(llm_messages)
            self.logger.info(f"Invoking LLM for post-simulation response: {msg_count} messages, timeout={timeout}s, provider={self.config.provider}, model={self.config.model}")
            start_time = time.time()
            
            response = self.response_llm.invoke(llm_messages)
            
            duration = time.time() - start_time
            self.logger.info(f"Post-simulation response LLM invocation completed successfully in {duration:.2f}s")
            
        except TimeoutError as e:
            duration = time.time() - start_time if 'start_time' in locals() else 0
            self.logger.error(f"Post-simulation response LLM invocation timed out after {duration:.2f}s (timeout={timeout}s): {e}")
            # Fallback message if LLM times out
            if simulation_finish:
                response = AIMessage(content="The simulation has been executed successfully! All configuration steps are complete and the simulation ran without errors. (Note: LLM response generation timed out, but simulation completed successfully.)")
            else:
                response = AIMessage(content="The simulation execution has completed. Please check the tool results above for details. (Note: LLM response generation timed out.)")
        except Exception as e:
            duration = time.time() - start_time if 'start_time' in locals() else 0
            error_type = type(e).__name__
            # Check if it's a timeout-related error
            if 'timeout' in str(e).lower() or 'timed out' in str(e).lower():
                self.logger.error(f"Post-simulation response LLM invocation timed out after {duration:.2f}s: {e}")
                if simulation_finish:
                    response = AIMessage(content="The simulation has been executed successfully! All configuration steps are complete and the simulation ran without errors. (Note: LLM response generation timed out, but simulation completed successfully.)")
                else:
                    response = AIMessage(content="The simulation execution has completed. Please check the tool results above for details. (Note: LLM response generation timed out.)")
            else:
                self.logger.error(f"Post-simulation response LLM invocation failed after {duration:.2f}s ({error_type}): {e}", exc_info=True)
                # Fallback message if LLM fails
                if simulation_finish:
                    response = AIMessage(content="The simulation has been executed successfully! All configuration steps are complete and the simulation ran without errors.")
                else:
                    response = AIMessage(content="The simulation execution has completed. Please check the tool results above for details.")
        
        # Add AI response to messages
        updated_messages = messages + [response]
        
        return {
            'messages': updated_messages,
            'current_module': 'supervisor',  # Mark as supervisor message for proper display
            'simulation_finish': simulation_finish,
            'simulation_tool_result': tool_result,
            'simulation_results': execution_results if execution_results else state.get('simulation_results')
        }
    
    def _route_after_post_simulation_response(self, state: UnifiedState) -> str:
        """Route after post-simulation response to completion"""
        validation_status = state.get('simulation_finish', False)
        
        if validation_status:
            self.logger.info("Simulation executed successfully, routing to completion")
        else:
            self.logger.info("Simulation execution completed with issues, routing to completion")
        
        return 'supervisor_completion'
    
    # =================
    # PUBLIC API
    # =================
    
    async def run(self, user_id: str = "user-default", thread_id: str = "supervisor_default", 
                  requested_modules: Optional[List[str]] = None) -> Dict[str, Any]:
        """Run the complete simulation configuration and execution process"""
        
        # Initialize if needed
        if not self.initialized:
            await self.initialize(requested_modules)
        
        self.logger.info(f"Starting configuration process with thread_id: {thread_id}")
        
        config = {"configurable": {"thread_id": thread_id}}
        
        input_state = UnifiedState(
            messages=[],
            current_stage=SupervisorStage.WELCOME,
            module_results={},
            execution_order=[],
            pending_modules=[],
            current_agent_thread="",
            error_message=None,
            user_preferences={},
            thread_id=thread_id,
            user_id=user_id,
            cli_generation_ready=False,
            cli_command=None,
            current_module=None,
            module_stage=None,
            config_mode="",
            validation_status=None,
            parameters=None,
            cli_parameters="",
            simulation_finish=None,
            context={},
        )
        
        try:
            result = await self.app.ainvoke(input_state, config)
            
            if result['current_stage'] == SupervisorStage.COMPLETION:
                # Extract successful results
                module_results = result.get('module_results', {})
                parameters = {}
                cli_parameters = {}
                
                for name, result_obj in module_results.items():
                    if result_obj.status == ModuleStatus.COMPLETED:
                        parameters[name] = result_obj.parameters
                        cli_parameters[name] = result_obj.cli_parameters
                
                # Extract CLI command if generated
                messages = result.get('messages', [])
                cli_command = None
                execution_results = None
                
                for msg in reversed(messages):
                    if hasattr(msg, 'content'):
                        content = str(msg.content)
                        if 'cli_command' in content or 'simulation' in content.lower():
                            # Try to extract execution info from message content
                            break
                
                return {
                    "status": "success",
                    "simulation_config": parameters,
                    "cli_parameters": cli_parameters,
                    "cli_command": cli_command,
                    "execution_results": execution_results,
                    "completed_modules": list(parameters.keys()),
                    "execution_order": result.get('execution_order', []),
                    "simulation_tools_available": len(self.simulation_tools) > 0
                }
            else:
                return {
                    "status": "error",
                    "error_message": result.get('error_message', 'Configuration incomplete'),
                    "current_stage": result['current_stage'],
                    "completed_modules": [
                        name for name, res in result.get('module_results', {}).items()
                        if res.status == ModuleStatus.COMPLETED
                    ]
                }
                
        except Exception as e:
            self.logger.error(f"Configuration failed: {e}")
            return {
                "status": "error", 
                "error_message": f"Configuration process failed: {str(e)}",
                "current_stage": "unknown"
            }
    
    def get_status(self, thread_id: str = "supervisor_default") -> SupervisorStatus:
        """Get current configuration status"""
        if not self.initialized:
            return SupervisorStatus(
                status="not_initialized",
                current_stage="none",
                available_modules=self.list_modules()
            )
        
        config = {"configurable": {"thread_id": thread_id}}
        state = self.app.get_state(config)
        
        if not state.values:
            return SupervisorStatus(
                status="not_started",
                current_stage="none",
                available_modules=self.list_modules()
            )
        
        module_results = state.values.get('module_results', {})
        completed = [
            name for name, res in module_results.items() 
            if res.status == ModuleStatus.COMPLETED
        ]
        total_modules = len(state.values.get('execution_order', []))
        
        return SupervisorStatus(
            status="completed" if len(completed) == total_modules else "in_progress",
            current_stage=state.values.get('current_stage', SupervisorStage.WELCOME),
            completed_modules=completed,
            execution_order=state.values.get('execution_order', []),
            error_message=state.values.get('error_message')
        )
    
    def export_config(self, thread_id: str = "supervisor_default") -> ConfigurationExport:
        """Export final configuration"""
        status = self.get_status(thread_id)
        
        if status.status != "completed":
            raise ValueError(f"Configuration not complete. Status: {status.status}")
        
        config = {"configurable": {"thread_id": thread_id}}
        state = self.app.get_state(config)
        
        module_results = state.values.get('module_results', {})
        
        return ConfigurationExport(
            simulation_configuration={
                f"{name}_parameters": result.parameters
                for name, result in module_results.items()
                if result.status == ModuleStatus.COMPLETED
            },
            metadata={
                "thread_id": thread_id,
                "supervisor_version": "3.0.0",
                "execution_order": state.values.get('execution_order', []),
                "completed_modules": status.completed_modules,
                "total_modules": len(state.values.get('execution_order', [])),
                "session_info": state.values.get('session_metadata', {}),
                "cli_tools_enabled": len(self.simulation_tools) > 0,
                "cli_generated": state.values.get('cli_command') is not None
            }
        )


# =================
# CONVENIENCE FACTORY FUNCTIONS
# =================

async def create_default_supervisor(
        provider = global_config.DEFAULT_PROVIDER, 
        model: str = global_config.DEFAULT_MODEL,
        cli_tools_path: str = None
        ) -> SupervisorAgent:
    """Create supervisor with default modules and CLI generation"""
    config = SupervisorConfig(
        provider=provider, 
        model=model
    )
    supervisor = SupervisorAgent(config, simulation_tools_path=cli_tools_path)
    supervisor.add_default_modules()
    await supervisor.initialize()
    return supervisor


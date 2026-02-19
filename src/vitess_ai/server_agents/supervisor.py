"""
Supervisor Agent - React-Agent Orchestrator

This supervisor agent orchestrates module react-agents using a supervisor
pattern. Module agents are created using LangChain's create_agent
and integrated as nodes in the supervisor graph, enabling unified state
management and checkpoint-based resumption.
"""
import json
import time
from typing import Dict, List, Any, Optional
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from vitess_ai.core.llms_providers import create_llm_with_fallback
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import InMemorySaver

from vitess_ai.schema.supervisor import (
    SupervisorConfig, SupervisorStage,
    create_routing_decision_model
)
from vitess_ai.core.registry import ModuleRegistry
from vitess_ai.core.log import get_logger
from vitess_ai.server_agents.base_module_agent import (
    BaseModuleAgent,
    ModuleMetadata,
)
from vitess_ai.server_agents.unified_state import UnifiedState
from vitess_ai.server_agents.module_middleware import (
    MessageFilterMiddleware, 
    ThreadIdMiddleware,
    RelevanceGuardrailMiddleware
)
from vitess_ai.core.config import global_config
from vitess_ai.prompts.supervisor import (
    get_simulation_execution_prompt, 
    get_post_simulation_response_prompt,
    get_supervisor_routing_prompt
)
from vitess_ai.server_agents.tool_wrapper import create_thread_id_tool_node


class SupervisorAgent:
    """
    Supervisor agent with react-agent orchestrator architecture.
    
    This agent creates a supervisor graph that orchestrates module react-agents.
    Module agents are created using LangChain's create_agent and integrated
    as nodes, enabling unified state management and checkpoint-based resumption
    with END pattern.
    """
    
    def __init__(self, config: SupervisorConfig = None, simulation_tools_path: str = None):
        """Initialize the supervisor agent"""
        self.config = config or self._create_default_config()
        self.llm = create_llm_with_fallback(provider=self.config.provider, model=self.config.model, streaming=False)
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
        self.logger = get_logger(__name__)
        self.logger.info("Supervisor agent initialized with logging enabled")
        
        # Cache for routing decision model (created dynamically based on registered modules)
        self._routing_decision_model = None
    
    def _create_default_config(self) -> SupervisorConfig:
        """Create default supervisor configuration"""
        return SupervisorConfig(
            provider=global_config.DEFAULT_PROVIDER,
            model=global_config.DEFAULT_MODEL
        )
    
    # =================
    # CLI TOOLS SETUP
    # =================
    
    async def _setup_simulation_tools(self):
        """Setup simulation execution MCP tools"""
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            import os
            
            # Check transport mode
            if global_config.is_mcp_http_mode():
                # Use HTTP transport (streamable-http for FastMCP compatibility)
                supervisor_url = global_config.get_mcp_url("supervisor")
                client = MultiServerMCPClient({
                    "simulation_runner": {
                        "url": supervisor_url,
                        "transport": "streamable_http",
                        "headers": {
                            "Content-Type": "application/json",
                            "Accept": "application/json,text/event-stream",
                            "MCP-Protocol-Version": "2024-11-05"
                        }
                    }
                })
                self.logger.info(f"Connecting to simulation MCP server via HTTP: {supervisor_url}")
            else:
                # Use stdio transport (development mode)
                env = os.environ.copy()
                client = MultiServerMCPClient({
                    "simulation_runner": {
                        "command": "python",
                        "args": [self.simulation_tools_path],
                        "transport": "stdio",
                        "env": env  # Pass environment variables to subprocess
                    }
                })
                self.logger.debug(f"Simulation MCP client created with environment variables: THREAD_ID={env.get('THREAD_ID', 'not set')}, VITESS_THREAD_ID={env.get('VITESS_THREAD_ID', 'not set')}")
            
            self.simulation_tools = await client.get_tools()
            self.logger.info(f"Loaded {len(self.simulation_tools)} simulation tools")
            
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
    
    def list_modules(self) -> List[Dict[str, Any]]:
        """List all registered modules with their info"""
        return self.registry.get_modules_info()
    
    # =================
    # BUILT-IN MODULE BUILDERS - Convenience methods
    # =================

    def add_modules_from_catalog(self) -> None:
        """Register all graph modules from the central module catalog."""
        from vitess_ai.modules import get_graph_module_metadata

        for module_metadata in get_graph_module_metadata():
            self.register_module(module_metadata)

    def add_module_by_name(self, module_name: str) -> None:
        """Register a specific graph module by name from the central catalog."""
        from vitess_ai.modules import get_graph_module_metadata

        for module_metadata in get_graph_module_metadata():
            if module_metadata.name == module_name:
                self.register_module(module_metadata)
                return
        raise ValueError(f"Module '{module_name}' not found in catalog")
    
    def add_readin_module(self) -> None:
        """Add the standard readin module"""
        self.add_module_by_name("readin")
    
    def add_guide_module(self) -> None:
        """Add the standard guide module"""
        self.add_module_by_name("guide")
    
    def add_writeout_module(self) -> None:
        """Add the standard writeout module"""
        self.add_module_by_name("writeout")
    
    def add_monitor1d_module(self) -> None:
        """Add the Monitor1D module"""
        self.add_module_by_name("monitor1d")
    
    def add_monitor2d_module(self) -> None:
        """Add the Monitor2D module"""
        self.add_module_by_name("monitor2d")
    
    def add_default_modules(self) -> None:
        """Add all default graph modules from the module catalog."""
        self.add_modules_from_catalog()
    
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
        
        # Use BaseModuleAgent.setup_agent_instance to create the agent
        agent = await BaseModuleAgent.setup_agent_instance(
            module_metadata=module_metadata,
            provider=self.config.provider,
            model=self.config.model,
            logger=self.logger
        )
        
        self.agent_instances[module_name] = agent
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
        self.app = self.graph.compile(checkpointer=self.memory)
        
        self.initialized = True
        self.logger.info(f"Supervisor initialized with {len(execution_order)} modules and simulation tools")
    
    async def restart_with_new_config(self, provider: str = None, model: str = None, clear_state: bool = True):
        """Restart the supervisor graph with new provider/model configuration
        
        Args:
            provider: New provider to use (optional, uses current if not provided)
            model: New model to use (optional, uses current if not provided)
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
        await self.initialize(force_reinitialize=True)
        
        self.logger.info("Supervisor graph restarted successfully with new configuration")
    
    # =================
    # SUPERVISOR GRAPH CREATION (React-Agent Architecture)
    # =================
    
    def _create_flat_graph(self, execution_order: List[str]) -> StateGraph:
        """
        Create supervisor graph with react-agent module nodes.
        
        Architecture:
        - Supervisor node routes to module react-agents
        - Module react-agents are created using create_agent
        - Module agents END when needing user input (validation not yet complete)
        - When module ENDs needing input, the entire graph ENDs to wait for user
        - When user provides input and invokes again, LangGraph resumes from checkpoint
          and supervisor routes back to the active module
        """
        workflow = StateGraph(UnifiedState)
        
        # Add supervisor nodes
        workflow.add_node("supervisor", self._supervisor_routing_node)
        workflow.add_node("supervisor_prepare_simulation", self._prepare_simulation_node)
        workflow.add_node("supervisor_run_simulation", self._run_simulation_node)
        workflow.add_node("supervisor_post_simulation_response", self._post_simulation_response_node)
        workflow.add_node("supervisor_generate_plots", self._generate_plots_node)
        workflow.add_node("supervisor_completion", self._completion_node)
        workflow.add_node("supervisor_error_handler", self._error_handler_node)
        
        # Add simulation tools node if available
        if self.simulation_tools:
            workflow.add_node("supervisor_simulation_tools", create_thread_id_tool_node(self.simulation_tools))
        
        # Add module react-agents as nodes with wrapper for state management
        for module_name in execution_order:
            agent = self.agent_instances[module_name]
            # Create middleware for this module
            # Relevance guardrail first to catch unrelated questions early
            relevance_guardrail = RelevanceGuardrailMiddleware(
                module_name=module_name,
                provider=self.config.provider,
                model=self.config.model
            )
            message_filter = MessageFilterMiddleware(module_name=module_name)
            thread_id_middleware = ThreadIdMiddleware()
            # Create react-agent with comprehensive prompt (includes both default and custom modes)
            # Pass middleware to filter messages and inject thread_id context
            # Guardrail is first to evaluate relevance before other processing
            react_agent = agent.create_module_react_agent(
                config_mode=None,  # None = handle dynamically
                middleware=[relevance_guardrail, message_filter, thread_id_middleware]
            )
            # Wrap react-agent to handle state updates and welcome messages
            # Pass message_filter so wrapper can use same filtering logic for pre-filtering
            wrapped_agent = agent.create_module_wrapper_node(react_agent, message_filter)
            workflow.add_node(f"{module_name}_agent", wrapped_agent)
            
        # Routing edges
        workflow.add_edge(START, "supervisor")
            
        # Supervisor routing - routes to modules or simulation
        workflow.add_conditional_edges("supervisor", self._route_supervisor)
            
        # Module agents return to supervisor or END
        for module_name in execution_order:
            workflow.add_conditional_edges(
                f"{module_name}_agent",
                lambda state, mn=module_name: self._route_from_module(state, mn),
                {
                    "supervisor": "supervisor",
                    "supervisor_error_handler": "supervisor_error_handler",
                    END: END
                }
            )
        
        # Simulation execution routing
        workflow.add_edge("supervisor_prepare_simulation", "supervisor_run_simulation")
        workflow.add_conditional_edges("supervisor_run_simulation", self._route_from_simulation)
        if self.simulation_tools:
            workflow.add_conditional_edges("supervisor_simulation_tools", self._route_after_simulation_tools)
            workflow.add_conditional_edges("supervisor_post_simulation_response", self._route_after_post_simulation_response)
        # Plot generation always routes to completion
        workflow.add_edge("supervisor_generate_plots", "supervisor_completion")

        workflow.add_edge("supervisor_completion", END)
        workflow.add_edge("supervisor_error_handler", END)
        
        return workflow
    
    # =================
    # SUPERVISOR NODE IMPLEMENTATIONS
    # =================

    def _get_llm_for_invocation(
        self,
        config: Optional[RunnableConfig] = None,
        use_response_llm: bool = False,
    ):
        """
        Return the LLM to use for this invocation.
        If config.configurable has provider and model, create and return that LLM
        so the supervisor can use a different model per invocation without restart.
        Otherwise return self.llm or self.response_llm.
        """
        configurable = {}
        if config is not None:
            configurable = getattr(config, "configurable", None) or {}
        provider = configurable.get("provider")
        model = configurable.get("model")
        if provider and model:
            try:
                return create_llm_with_fallback(
                    provider=str(provider),
                    model=str(model),
                    temperature=0.0,
                )
            except Exception as e:
                self.logger.warning(
                    f"[SUPERVISOR] Failed to create LLM from configurable provider={provider}, model={model}: {e}. Using default."
                )
        return self.response_llm if use_response_llm else self.llm

    def _prepare_simulation_node(self, state: UnifiedState) -> dict:
        """Prepare simulation node - emits the 'starting simulation' message before execution"""
        self.logger.info("Preparing simulation execution - showing start message")
        
        # Extract module results from state
        module_results = state.get('module_results', {})
        execution_order = state.get('execution_order', [])
        
        # Create user-visible message indicating simulation execution is starting
        completed_modules = [name for name, result in module_results.items() 
                             if result.stage.stage == "completed"]
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
    
    def _run_simulation_node(
        self, state: UnifiedState, config: Optional[RunnableConfig] = None
    ) -> dict:
        """Simulation execution node - runs simulation directly using module results
        
        This node includes timeout protection to prevent hanging with Blablador:
        - Specifically catches timeout errors
        - Provides informative error messages if timeout occurs
        - Falls back gracefully if LLM invocation fails
        Uses config.configurable (provider/model) when present for dynamic model selection.
        """
        self.logger.info("Entering simulation execution phase")
        
        # Extract module results from state
        module_results = state.get('module_results', {})
        execution_order = state.get('execution_order', [])
        
        # Create system message for simulation execution
        simulation_prompt = get_simulation_execution_prompt(module_results, execution_order)
        simulation_system_prompt = SystemMessage(content=simulation_prompt)

        messages = [simulation_system_prompt]
        llm = self._get_llm_for_invocation(config, use_response_llm=False)
        # Bind simulation tools so the dynamic LLM can call them (same as self.llm at init)
        if self.simulation_tools:
            llm = llm.bind_tools(self.simulation_tools, parallel_tool_calls=False)
        timeout = getattr(llm, 'timeout', global_config.TIMEOUT_SECONDS)
        msg_count = len(messages)
        response = None
        
        try:
            # Enhanced logging for LLM invocation
            self.logger.info(f"Invoking LLM for simulation execution: {msg_count} messages, timeout={timeout}s")
            start_time = time.time()
            
            response = llm.invoke(messages)
            
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
                           if result.stage.stage == "completed"]
        
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
    
    def _get_completed_modules(self, module_results: dict) -> List[str]:
        """
        Get list of completed module names from module_results.
        
        A module is considered completed only if:
        - It has a ModuleResult in module_results
        - The ModuleResult has stage="completed" (which means the validation tool returned success with valid parameters)
        
        Args:
            module_results: Dictionary of module_name -> ModuleResult
            
        Returns:
            List of completed module names
        """
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
        return completed
    
    def get_routing_decision_model(self):
        """
        Get or create the RoutingDecision Pydantic model based on registered modules.
        
        Returns:
            RoutingDecision model class with Literal types for available modules
        """
        if self._routing_decision_model is None:
            # Get all registered module names
            module_names = self.registry.list_modules()
            # Create the model dynamically
            self._routing_decision_model = create_routing_decision_model(module_names)
            self.logger.info(f"Created routing decision model with modules: {module_names}")
        return self._routing_decision_model
    
    def _are_all_modules_completed(self, execution_order: List[str], module_results: dict) -> bool:
        """
        Verify that ALL modules in execution_order have been validated and completed.
        
        This checks:
        1. execution_order is not empty
        2. Every module in execution_order has a ModuleResult with stage="completed"
        3. The number of completed modules equals the number of modules in execution_order
        
        Args:
            execution_order: List of module names in execution order
            module_results: Dictionary of module_name -> ModuleResult
            
        Returns:
            True if all modules are completed, False otherwise
        """
        if not execution_order:
            self.logger.warning("execution_order is empty, cannot verify completion")
            return False
        
        completed = self._get_completed_modules(module_results)
        
        # Check that all modules in execution_order are completed
        for module in execution_order:
            if module not in completed:
                self.logger.debug(f"Module {module} is not completed (completed modules: {completed})")
                return False
        
        # Verify count matches (defensive check)
        if len(completed) != len(execution_order):
            self.logger.warning(
                f"Completion count mismatch: {len(completed)} completed modules "
                f"but {len(execution_order)} modules in execution_order"
            )
            return False
        
        self.logger.info(f"All {len(execution_order)} modules are completed: {execution_order}")
        return True
    
    def _supervisor_routing_node(
        self, state: UnifiedState, config: Optional[RunnableConfig] = None
    ) -> dict:
        """
        Supervisor routing node - determines which module to route to using LLM.
        
        This node uses LLM-based routing that can:
        - Understand conversation context and user intent
        - Handle complex requests like changing previous modules
        - Provide natural greetings instead of formal welcome messages
        - Route intelligently based on state and messages
        
        Falls back to manual routing if LLM fails.
        Uses config.configurable (provider/model) when present for dynamic model selection.
        """
        self.logger.info("[SUPERVISOR ROUTING] Supervisor routing node triggered (LLM-based)")
        
      
        current_stage = state.get('current_stage')
        execution_order = state.get('execution_order', [])
        messages = state.get('messages', [])
        module_results = state.get('module_results', {})
        current_active = state.get('current_active_module')
        thread_id = state.get('thread_id')
        user_id = state.get('user_id')
        
        # Set environment variables for MCP subprocesses
        if thread_id:
            import os
            os.environ["THREAD_ID"] = thread_id
            os.environ["VITESS_THREAD_ID"] = thread_id
        
        # Get execution_order from registry if not set
        if not execution_order:
            execution_order = self.registry.get_execution_order()
            if execution_order:
                self.logger.info(f"Retrieved execution_order from registry: {execution_order}")
        
        completed_modules = self._get_completed_modules(module_results)
        
        # Check the actual stage of current_active_module if it exists (for logging)
        current_active_stage = None
        if current_active and current_active in module_results:
            result = module_results[current_active]
            if hasattr(result, 'stage'):
                if hasattr(result.stage, 'stage'):
                    current_active_stage = result.stage.stage
                elif isinstance(result.stage, dict):
                    current_active_stage = result.stage.get('stage')
                else:
                    current_active_stage = result.stage
        
        self.logger.debug(f"[SUPERVISOR ROUTING] State: current_stage={current_stage}, execution_order={execution_order}, current_active_module={current_active}, current_active_stage={current_active_stage}, completed_modules={completed_modules}")
        
        state_updates = {}
        
        # CRITICAL: Check if there's an active module that hasn't been validated yet
        # If so, we MUST route back to it - don't allow routing to next module
        # A module is considered unvalidated if it's not in completed_modules
        # (i.e., ModuleResult.stage != "completed" - could be "processing" or "error")
        if current_active and current_active not in completed_modules:
            self.logger.info(f"[SUPERVISOR ROUTING] Active module {current_active} is not validated yet - forcing route back to it")
            state_updates['current_active_module'] = current_active
            state_updates['current_module'] = current_active
            if thread_id:
                state_updates['thread_id'] = thread_id
            if user_id:
                state_updates['user_id'] = user_id
            if 'current_stage' not in state_updates:
                state_updates['current_stage'] = SupervisorStage.MODULE_EXECUTION
            return state_updates
        
        # Try LLM-based routing first
        try:
            # Get routing decision model
            RoutingDecisionModel = self.get_routing_decision_model()
            
            # Prepare module information
            modules_info = self.registry.get_modules_info()
            
            # Get recent messages (last 8 for context)
            recent_messages = messages[-8:] if len(messages) > 8 else messages
            
            # Create routing prompt
            routing_prompt = get_supervisor_routing_prompt(
                execution_order=execution_order,
                completed_modules=completed_modules,
                module_results=module_results,
                current_active_module=current_active,
                recent_messages=recent_messages,
                modules_info=modules_info,
                simulation_tools_available=bool(self.simulation_tools)
            )
            
            # Create LLM with structured output (use configurable provider/model when present)
            llm = self._get_llm_for_invocation(config, use_response_llm=False)
            routing_llm = llm.with_structured_output(RoutingDecisionModel)
            
            # Detect first interaction: check if there's already a supervisor greeting message
            # First interaction = no previous supervisor AIMessage (greeting) exists
            has_supervisor_greeting = any(
                isinstance(msg, AIMessage) and 
                hasattr(msg, 'additional_kwargs') and 
                msg.additional_kwargs.get('module_name') == 'supervisor'
                for msg in messages
            )
            is_first_interaction = not has_supervisor_greeting
            
            # Invoke LLM for routing decision
            self.logger.info(f"[SUPERVISOR ROUTING] Invoking LLM for routing decision (first_interaction={is_first_interaction})")
            routing_decision = routing_llm.invoke([SystemMessage(content=routing_prompt)])
            
            self.logger.info(f"[SUPERVISOR ROUTING] LLM routing decision: action={routing_decision.action}, target_module={routing_decision.target_module}, has_greeting={bool(routing_decision.greeting_message)}, reasoning={routing_decision.reasoning[:100]}...")
            
            # Handle greeting message (first interaction)
            # If LLM didn't provide greeting but this is first interaction, generate one programmatically
            if is_first_interaction:
                if routing_decision.greeting_message:
                    greeting_content = routing_decision.greeting_message
                    self.logger.info("[SUPERVISOR ROUTING] Using LLM-provided greeting message")
                else:
                    # Generate fallback greeting if LLM didn't provide one
                    self.logger.warning("[SUPERVISOR ROUTING] LLM didn't provide greeting_message for first interaction, generating fallback")
                    modules_list = ", ".join([m.get('display_name', m.get('name', '')) for m in modules_info])
                    greeting_content = f"Hello! I'm your Simulation Supervisor. I'll help you configure your neutron simulation step by step. We'll work through the following modules: {modules_list}. Let's start!"
                
                greeting_message = AIMessage(
                    content=greeting_content,
                    additional_kwargs={"module_name": "supervisor"}
                )
                state_updates['messages'] = state.get('messages', []) + [greeting_message]
                state_updates['current_module'] = 'supervisor'
                self.logger.info(f"[SUPERVISOR ROUTING] Added supervisor greeting message: {greeting_content[:100]}...")
            
            # Initialize execution_order if not set
            if not execution_order:
                execution_order = self.registry.get_execution_order()
                state_updates['execution_order'] = execution_order
                state_updates['pending_modules'] = execution_order.copy()
            
            # Handle routing based on LLM decision
            if routing_decision.action == "route_to_simulation":
                # Route to simulation - don't set current_active_module
                # But first verify no active unvalidated module exists
                if current_active and current_active not in completed_modules:
                    self.logger.warning(f"[SUPERVISOR ROUTING] LLM tried to route to simulation but active module {current_active} is not validated - overriding to route back to active module")
                    state_updates['current_active_module'] = current_active
                    state_updates['current_module'] = current_active
                else:
                    self.logger.info("[SUPERVISOR ROUTING] LLM decided to route to simulation")
                    # _route_supervisor will handle this
            elif routing_decision.action == "route_to_module":
                target_module = routing_decision.target_module
                
                if target_module and target_module != "simulation":
                    # CRITICAL: Validate that we're not routing away from an unvalidated active module
                    if current_active and current_active not in completed_modules and target_module != current_active:
                        self.logger.warning(f"[SUPERVISOR ROUTING] LLM tried to route to {target_module} but active module {current_active} is not validated - overriding to route back to active module")
                        state_updates['current_active_module'] = current_active
                        state_updates['current_module'] = current_active
                    # Validate target_module exists
                    elif target_module in execution_order or target_module in self.registry.list_modules():
                        self.logger.info(f"[SUPERVISOR ROUTING] LLM decided to route to module: {target_module}")
                        state_updates['current_active_module'] = target_module
                        state_updates['current_module'] = target_module
                        
                        # If routing to completed module, keep state (will re-validate)
                        if target_module in completed_modules:
                            self.logger.info(f"[SUPERVISOR ROUTING] Routing to completed module {target_module} for modification")
                    else:
                        self.logger.warning(f"[SUPERVISOR ROUTING] LLM returned invalid module name: {target_module}, falling back to manual routing")
                        raise ValueError(f"Invalid module name: {target_module}")
                else:
                    # target_module is None or "simulation" but action is route_to_module
                    # This might be a mistake, but handle gracefully
                    self.logger.warning(f"[SUPERVISOR ROUTING] LLM action is route_to_module but target_module is {target_module}, falling back")
                    raise ValueError(f"Inconsistent routing decision: action={routing_decision.action}, target_module={target_module}")
            
            # Update state stage
            if 'current_stage' not in state_updates:
                state_updates['current_stage'] = SupervisorStage.MODULE_EXECUTION
            
            # Ensure thread_id and user_id are set
            if thread_id:
                state_updates['thread_id'] = thread_id
            if user_id:
                state_updates['user_id'] = user_id
            
            return state_updates
            
        except Exception as e:
            # Fallback to manual routing
            self.logger.warning(f"[SUPERVISOR ROUTING] LLM routing failed: {e}, falling back to manual routing", exc_info=True)
            return self._supervisor_routing_node_manual(state)
    
    def _supervisor_routing_node_manual(self, state: UnifiedState) -> dict:
        """
        Manual fallback routing logic (original implementation).
        Used when LLM routing fails.
        """
        self.logger.info("[SUPERVISOR ROUTING] Using manual routing fallback")
        
        current_stage = state.get('current_stage')
        execution_order = state.get('execution_order', [])
        messages = state.get('messages', [])
        module_results = state.get('module_results', {})
        current_active = state.get('current_active_module')
        thread_id = state.get('thread_id')
        user_id = state.get('user_id')
        
        # Get execution_order from registry if not set
        if not execution_order:
            execution_order = self.registry.get_execution_order()
        
        state_updates = {}
        
        # CRITICAL: Check if there's an active module that hasn't been validated yet
        # If so, we MUST route back to it - don't allow routing to next module
        completed_modules = self._get_completed_modules(module_results)
        
        # Check the actual stage of current_active_module if it exists (for logging)
        current_active_stage = None
        if current_active and current_active in module_results:
            result = module_results[current_active]
            if hasattr(result, 'stage'):
                if hasattr(result.stage, 'stage'):
                    current_active_stage = result.stage.stage
                elif isinstance(result.stage, dict):
                    current_active_stage = result.stage.get('stage')
                else:
                    current_active_stage = result.stage
        
        if current_active and current_active not in completed_modules:
            self.logger.info(f"[SUPERVISOR ROUTING] Manual routing: Active module {current_active} is not validated yet (stage={current_active_stage}) - forcing route back to it")
            state_updates['current_active_module'] = current_active
            state_updates['current_module'] = current_active
            if thread_id:
                state_updates['thread_id'] = thread_id
            if user_id:
                state_updates['user_id'] = user_id
            if 'current_stage' not in state_updates:
                state_updates['current_stage'] = SupervisorStage.MODULE_EXECUTION
            return state_updates
        
        # Check if this is a new conversation
        is_new_conversation = not execution_order
        
        # Initialize execution_order if needed
        if is_new_conversation:
            execution_order = self.registry.get_execution_order()
            state_updates['execution_order'] = execution_order
            state_updates['pending_modules'] = execution_order.copy()
            state_updates['current_stage'] = SupervisorStage.MODULE_EXECUTION
            if thread_id:
                state_updates['thread_id'] = thread_id
            if user_id:
                state_updates['user_id'] = user_id
        
        # Update current_active_module if routing to a new module
        execution_order = state_updates.get('execution_order') or execution_order
        if not current_active and execution_order:
            # Check if all modules completed
            if self._are_all_modules_completed(execution_order, module_results):
                self.logger.info("[SUPERVISOR ROUTING] All modules completed, ready for simulation")
                # Don't set current_active_module - let _route_supervisor handle routing to simulation
            else:
                # Find next pending module
                completed = self._get_completed_modules(module_results)
                next_module = None
                for module in execution_order:
                    if module not in completed:
                        next_module = module
                        break
                
                if next_module:
                    self.logger.info(f"[SUPERVISOR ROUTING] Manual routing to next module: {next_module}")
                    state_updates['current_active_module'] = next_module
                    state_updates['current_module'] = next_module
        else:
            # Active module exists - keep it
            self.logger.info(f"[SUPERVISOR ROUTING] Resuming active module: {current_active}")
            state_updates['current_module'] = current_active
        
        return state_updates
    
    def _route_supervisor(self, state: UnifiedState) -> str:
        """
        Route from supervisor to appropriate module agent or simulation.
        
        Priority:
        1. Resume active module if user input provided
        2. Find next pending module
        3. All modules complete - go to simulation
        
        Note: state is passed as a dict by LangGraph, not as UnifiedState instance
        """
        # Priority 1: Resume active module if user input provided
        current_active = state.get('current_active_module')
        if current_active:
            # User provided input, route to active module
            # Module will resume from checkpoint automatically
            self.logger.info(f"[ROUTE SUPERVISOR] Routing to active module: {current_active}")
            return f"{current_active}_agent"
        
        # Priority 2: Find next pending module
        # Note: state is passed as a dict, so we need to implement get_next_module logic inline
        execution_order = state.get('execution_order', [])
        module_results = state.get('module_results', {})
        
        self.logger.debug(f"[ROUTE SUPERVISOR] execution_order={execution_order}, module_results keys={list(module_results.keys())}")
        
        # If execution_order is empty, we can't determine routing
        # This should only happen on first invocation before welcome stage sets it
        if not execution_order:
            self.logger.warning("[ROUTE SUPERVISOR] execution_order is empty in route_supervisor - trying registry as fallback")
            # Try to get it from registry as fallback
            execution_order = self.registry.get_execution_order()
            if not execution_order:
                self.logger.error("[ROUTE SUPERVISOR] Cannot determine execution_order - no modules registered")
                # Fallback: return to supervisor to try again (shouldn't happen in normal flow)
                return "supervisor"
        
        # Verify all modules are completed before routing to simulation
        # Only check if execution_order is not empty
        if execution_order and self._are_all_modules_completed(execution_order, module_results):
            # Priority 3: All modules validated and completed - route to simulation
            self.logger.info("[ROUTE SUPERVISOR] All modules validated and completed, routing to simulation")
            return "supervisor_prepare_simulation"
        
        # Get completed modules to find next pending module
        completed = self._get_completed_modules(module_results)
        pending = [m for m in execution_order if m not in completed]
        
        self.logger.debug(f"[ROUTE SUPERVISOR] Completed: {completed}, Pending: {pending}")
        
        # Find first module in execution order that isn't completed
        next_module = None
        for module in execution_order:
            if module not in completed:
                next_module = module
                break
        
        if next_module:
            # Mark as active and route
            self.logger.info(f"[ROUTE SUPERVISOR] Routing to next module: {next_module} (completed: {completed}, pending: {pending})")
            return f"{next_module}_agent"
        
        # Edge case: no next module found but not all modules are completed
        # This should not happen if _are_all_modules_completed works correctly
        self.logger.error(
            f"[ROUTE SUPERVISOR] Could not find next module but not all modules are completed. "
            f"Execution order: {execution_order}, Completed: {completed}, "
            f"Module results: {list(module_results.keys())}"
        )
        # Fallback: route to simulation (should not reach here in normal flow)
        return "supervisor_prepare_simulation"
    
    def _route_from_module(self, state: UnifiedState, module_name: str) -> str:
        """
        Route from module agent back to supervisor or END.
        
        This handles:
        - Module completion: clear active module, return to supervisor
        - Module END (needs input): keep active module, END graph to wait for user input
        - Module error: route to error handler
        
        When a module ENDs waiting for user input, the entire graph ENDs.
        When user provides input and invokes again, LangGraph resumes from checkpoint
        and supervisor will route back to the active module.
        """
        # Note: state is passed as a dict by LangGraph, not as UnifiedState instance
        # So we need to access it as a dict
        module_results = state.get('module_results', {})
        module_result = module_results.get(module_name)
        
        self.logger.debug(f"[ROUTING] Routing from module {module_name}, module_result exists: {module_result is not None}")
        
        if module_result:
            # Handle both ModuleResult object and dict
            if hasattr(module_result, 'stage'):
                stage = module_result.stage
            elif isinstance(module_result, dict):
                stage = module_result.get('stage')
            else:
                stage = None
            
            # Extract stage value
            if hasattr(stage, 'stage'):
                stage_value = stage.stage
            elif isinstance(stage, dict):
                stage_value = stage.get('stage')
            else:
                stage_value = stage
            
            self.logger.debug(f"[ROUTING] Module {module_name} stage_value: {stage_value}")
            
            if stage_value == "completed":
                # Module complete - clear active module, return to supervisor
                self.logger.info(f"[ROUTING] Module {module_name} completed, routing to supervisor")
                return "supervisor"
            elif stage_value == "error":
                # Module error - route to error handler
                self.logger.error(f"[ROUTING] Module {module_name} encountered error, routing to error handler")
                return "supervisor_error_handler"
        
        # Module ENDed but not complete (needs user input)
        # Keep current_active_module set, END graph to wait for user input
        # When user provides input and invokes again, LangGraph resumes from checkpoint
        # and supervisor will route back to this active module
        self.logger.info(f"[ROUTING] Module {module_name} ENDed waiting for input, ending graph to wait for user")
        return END
    
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
    
    def _post_simulation_response_node(
        self, state: UnifiedState, config: Optional[RunnableConfig] = None
    ) -> dict:
        """Post-simulation response node - generates AI response after tool execution
        
        This node includes timeout protection to prevent hanging with Blablador:
        - Specifically catches timeout errors
        - Provides fallback messages if timeout occurs
        - Uses existing tool results to generate appropriate responses
        Uses config.configurable (provider/model) when present for dynamic model selection.
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
        
        # Prepare LLM invocation with timeout protection (use configurable provider/model when present)
        response_llm = self._get_llm_for_invocation(config, use_response_llm=True)
        recent_messages = messages[-5:] if len(messages) > 5 else messages
        llm_messages = [system_message] + recent_messages
        timeout = getattr(response_llm, 'timeout', global_config.TIMEOUT_SECONDS)
        response = None
        
        try:
            # Invoke unbound LLM (without tools) to generate response
            # Include recent conversation context (last few messages)
            msg_count = len(llm_messages)
            self.logger.info(f"Invoking LLM for post-simulation response: {msg_count} messages, timeout={timeout}s")
            start_time = time.time()
            
            response = response_llm.invoke(llm_messages)
            
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
        """Route after post-simulation response to plot generation"""
        validation_status = state.get('simulation_finish', False)
        
        if validation_status:
            self.logger.info("Simulation executed successfully, routing to plot generation")
        else:
            self.logger.info("Simulation execution completed with issues, routing to plot generation")
        
        return 'supervisor_generate_plots'
    
    def _generate_plots_node(self, state: UnifiedState) -> dict:
        """Generate plots from monitor files after simulation execution"""
        self.logger.info("Entering plot generation phase")
        
        # Get thread_id from state
        thread_id = state.get('thread_id')
        if not thread_id:
            self.logger.warning("No thread_id in state, skipping plot generation")
            return {
                'messages': state.get('messages', []),
                'plot_data': {},
            }
        
        # Check for monitor files and generate plots
        plot_data = {}
        plot_messages = []
        
        try:
            from pathlib import Path
            from vitess_ai.core.config import global_config
            
            # Extract file paths from module results in state
            module_results = state.get('module_results', {})
            outputs_dir = Path(global_config.VITESS_PROJECT_PATH) / thread_id / "outputs"
            
            def extract_file_path(module_name: str, default_filename: str) -> str:
                """Extract file path from module results or use default."""
                file_path = None
                if module_name in module_results:
                    module_result = module_results[module_name]
                    if hasattr(module_result, 'parameters') and module_result.parameters:
                        file_path = module_result.parameters.get('fMonitorFilename')
                    elif isinstance(module_result, dict):
                        params = module_result.get('parameters', {})
                        if isinstance(params, dict):
                            file_path = params.get('fMonitorFilename')
                
                # Fallback to default path if not found in state
                if not file_path:
                    return str(outputs_dir / default_filename)
                
                # Ensure it's a string and resolve relative paths
                file_path = str(file_path)
                if not Path(file_path).is_absolute():
                    # If relative, assume it's relative to outputs directory
                    return str(outputs_dir / file_path)
                return file_path
            
            # Get Monitor1D file path from module results
            monitor1d_file_path = extract_file_path('monitor1d', 'monitor1D.dat')
            
            monitor1d_file = Path(monitor1d_file_path)
            if monitor1d_file.exists():
                self.logger.info(f"Found Monitor1D file: {monitor1d_file}")
                try:
                    from vitess_ai.plots.vitess_plot import read_mfile_plotly
                    result = read_mfile_plotly(str(monitor1d_file))
                    if result.get("success"):
                        plot_data["monitor1d"] = {
                            "plot_json": result["plot_json"],
                            "title": result.get("title", "Monitor1D Results"),
                            "xaxis": result.get("xaxis", "x"),
                            "yaxis": result.get("yaxis", "Intensity [n/s]"),
                            "plot_type": "monitor1d",
                        }
                        plot_messages.append(f"✅ Generated interactive plot for Monitor1D data")
                    else:
                        self.logger.warning(f"Failed to generate Monitor1D plot: {result.get('error')}")
                except Exception as e:
                    self.logger.error(f"Error generating Monitor1D plot: {e}", exc_info=True)
            else:
                self.logger.info(f"Monitor1D file not found: {monitor1d_file}")
            
            # Get Monitor2D file path from module results
            monitor2d_file_path = extract_file_path('monitor2d', 'monitor2D.dat')
            
            monitor2d_file = Path(monitor2d_file_path)
            if monitor2d_file.exists():
                self.logger.info(f"Found Monitor2D file: {monitor2d_file}")
                try:
                    from vitess_ai.plots.vitess_plot import read_mfile_plotly
                    result = read_mfile_plotly(str(monitor2d_file))
                    if result.get("success"):
                        plot_data["monitor2d"] = {
                            "plot_json": result["plot_json"],
                            "title": result.get("title", "Monitor2D Results"),
                            "xaxis": result.get("xaxis", "x"),
                            "yaxis": result.get("yaxis", "y"),
                            "plot_type": "monitor2d",
                        }
                        plot_messages.append(f"✅ Generated interactive plot for Monitor2D data")
                    else:
                        self.logger.warning(f"Failed to generate Monitor2D plot: {result.get('error')}")
                except Exception as e:
                    self.logger.error(f"Error generating Monitor2D plot: {e}", exc_info=True)
            else:
                self.logger.info(f"Monitor2D file not found: {monitor2d_file}")
                self.logger.info(f"Monitor2D file path checked: {monitor2d_file_path}")
                # Check if monitor2d module was even configured
                if 'monitor2d' not in module_results:
                    self.logger.info("Monitor2D module was not configured, so no plot expected")
                else:
                    self.logger.warning(f"Monitor2D module was configured but file not found at expected path: {monitor2d_file_path}")
            
        except Exception as e:
            self.logger.error(f"Error in plot generation node: {e}", exc_info=True)
            # Log plot_data for debugging
            self.logger.info(f"Plot data generated so far: {list(plot_data.keys())}")
        
        # Create message with plot information
        messages = state.get('messages', [])
        
        # Check if any monitor modules were configured
        execution_order = state.get('execution_order', [])
        has_monitor_modules = 'monitor1d' in execution_order or 'monitor2d' in execution_order
        
        if plot_data:
            # Plots were successfully generated
            plot_summary = "📊 **Visualization Results**\n\n" + "\n".join(plot_messages)
            from langchain_core.messages import AIMessage
            # Create message with plot_data in custom_data for UI rendering
            plot_message = AIMessage(content=plot_summary)
            # Store plot_data in message's additional_kwargs for custom_data extraction
            # The streaming handler will convert this to ChatMessage with custom_data
            plot_message.additional_kwargs = {"plot_data": plot_data}
            messages.append(plot_message)
            # Log what plots were generated for debugging
            self.logger.info(f"Plot generation complete. Generated plots: {list(plot_data.keys())}")
            self.logger.debug(f"Plot data structure: monitor1d={'monitor1d' in plot_data}, monitor2d={'monitor2d' in plot_data}")
        elif has_monitor_modules:
            # Monitor modules were configured but no plots were generated
            # This could mean files weren't created or there was an error
            self.logger.info("Monitor modules were configured but no plots were generated")
            # Optionally add a message to inform the user (commented out to avoid noise)
            # from langchain_core.messages import AIMessage
            # no_plots_message = AIMessage(content="ℹ️ No visualization data available. Monitor files may not have been generated during simulation.")
            # messages.append(no_plots_message)
        else:
            # No monitor modules were configured - this is expected, no action needed
            self.logger.info("No monitor modules in execution order, skipping plot generation message")
        
        return {
            'messages': messages,
            'plot_data': plot_data,
            'current_module': 'supervisor',
        }
    
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

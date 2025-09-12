"""
supervisor_agent.py - Enhanced Supervisor Agent with CLI Generation
Combined Builder and Supervisor Agent with MCP CLI generation tools
"""
import logging
import json
from typing import Dict, List, Any, Optional, Callable, Type
from langchain_core.messages import SystemMessage, HumanMessage
from vitess_ai.core.llms_providers import create_llm_with_fallback
from langgraph.graph import StateGraph, MessagesState, END, START
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode
from pydantic import Field

from vitess_ai.schema.supervisor_modules import (
    SupervisorConfig, SupervisorStage, 
      SupervisorStatus, ConfigurationExport
)
from vitess_ai.core.registry import ModuleRegistry
from vitess_ai.core.interrupt import InterruptManager

from vitess_ai.agents.base_module_agent import (
    BaseModuleAgent, ModuleBuilder, 
    ModuleStatus, ModuleMetadata, 
    ModuleResult
)

from vitess_ai.core.config import global_config

# =================
# CONFIG BUILDER - Creates supervisor configurations
# =================

class SupervisorConfigBuilder:
    """Simple helper to create supervisor configurations"""
    
    @staticmethod
    def create(
        provider: str = global_config.DEFAULT_PROVIDER,
        model: str = global_config.DEFAULT_MODEL,
        welcome_message: str = None,
        cli_tools_path: str = None
    ) -> SupervisorConfig:
        """
        Create a supervisor config 
        
        Args:
            provider: Provider of LLM
            model: LLM model to use
            welcome_message: Custom welcome text (uses default if None)
            cli_tools_path: Path to CLI generation MCP tools
        """
        config = SupervisorConfig(
            provider=provider,
            model=model
        )
        
        if welcome_message:
            config.welcome_message = welcome_message
            
        return config

# =================
# SUPERVISOR STATE
# =================

class SupervisorState(MessagesState):
    """Enhanced state for the supervisor"""
    current_stage: SupervisorStage = SupervisorStage.WELCOME
    module_results: Dict[str, ModuleResult] = Field(default={}) # State storing Vitess modules parameters
    current_module: Optional[str] = None
    execution_order: List[str] = Field(default=[])
    pending_modules: List[str] = Field(default=[])
    current_agent_thread: str = ""
    error_message: Optional[str] = None
    user_preferences: Dict[str, Any] = Field(default={})
    session_metadata: Dict[str, Any] = Field(default={})
    cli_generation_ready: bool = False
    cli_command: Optional[str] = None
    simulation_finish: Optional[bool] = None

# =================
# MAIN SUPERVISOR AGENT
# =================

class SupervisorAgent:
    """Supervisor agent with module registration system and CLI generation capabilities"""
    
    def __init__(self, config: SupervisorConfig = None, simulation_tools_path: str = None):
        """Initialize the supervisor agent"""
        self.config = config or SupervisorConfigBuilder.create()
        self.llm = create_llm_with_fallback(provider=self.config.provider, model=self.config.model)
        self.registry = ModuleRegistry()
        
        # Simulation tools configuration
        self.simulation_tools_path = simulation_tools_path or "vitess_ai/mcp_tools/supervisor_mcp_tools.py"
        self.simulation_tools = []
        
        # Runtime components
        self._agent_instances: Dict[str, BaseModuleAgent] = {}
        self._graph: Optional[StateGraph] = None
        self._app = None
        self.memory = MemorySaver()
        self._initialized = False
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
    
    # =================
    # CLI TOOLS SETUP
    # =================
    
    async def _setup_simulation_tools(self):
        """Setup simulation execution MCP tools"""
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            client = MultiServerMCPClient({
                "simulation_runner": {
                    "command": "python",
                    "args": [self.simulation_tools_path],
                    "transport": "stdio"
                }
            })
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
        if self._initialized:
            self.logger.info("New module registered, graph will be rebuilt on next run")
            self._initialized = False
    
    def unregister_module(self, module_name: str) -> bool:
        """Unregister a module"""
        result = self.registry.unregister_module(module_name)
        
        # Clean up agent instance
        if module_name in self._agent_instances:
            del self._agent_instances[module_name]
        
        # Invalidate graph
        if self._initialized:
            self._initialized = False
            
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
        from vitess_ai.agents.readin_module_agent import ReadInAgent
        
        module = ModuleBuilder.create(
            name="readin",
            display_name="Read-in Parameters",
            description="Configure neutron input parameters and initial conditions",
            agent_class=ReadInAgent,
            config_path=config_path or global_config.READIN_MCP_PATH,
            order=1
        )
        self.register_module(module)
    
    def add_guide_module(self, config_path: str = None) -> None:
        """Add the standard guide module"""  
        from vitess_ai.agents.guide_module_agent import GuideAgent
        
        module = ModuleBuilder.create(
            name="guide",
            display_name="Guide Parameters", 
            description="Configure neutron guide specifications and geometry",
            agent_class=GuideAgent,
            config_path=config_path or global_config.GUIDE_MCP_PATH,
            order=2
        )
        self.register_module(module)
    
    def add_writeout_module(self, config_path: str = None) -> None:
        """Add the standard writeout module"""
        from vitess_ai.agents.writeout_module_agent import WriteoutAgent
        
        module = ModuleBuilder.create(
            name="writeout",
            display_name="Writeout Parameters",
            description="Configure output settings and data formats", 
            agent_class=WriteoutAgent,
            config_path=config_path or global_config.WRITEOUT_MCP_PATH,
            order=3
        )
        self.register_module(module)
    
    def add_custom_module(
        self,
        name: str,
        display_name: str,
        description: str,
        agent_class: Type[BaseModuleAgent],
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
        self.add_writeout_module()
    
    # =================
    # AGENT INITIALIZATION
    # =================
    
    async def _setup_agent_instance(self, module_name: str) -> BaseModuleAgent:
        """Setup an agent instance for a module"""
        if module_name in self._agent_instances:
            return self._agent_instances[module_name]
        
        module_metadata = self.registry.get_module(module_name)
        if not module_metadata:
            raise ValueError(f"Module '{module_name}' not registered")
        
        # Setup MCP tools if config path provided
        tools = []
        if module_metadata.config_path:
            try:
                from langchain_mcp_adapters.client import MultiServerMCPClient
                client = MultiServerMCPClient({
                    "validation": {
                        "command": "python",
                        "args": [module_metadata.config_path],
                        "transport": "stdio"
                    }
                })
                tools = await client.get_tools()
                self.logger.info(f"Loaded {len(tools)} MCP tools for {module_name}")
            except Exception as e:
                self.logger.warning(f"Failed to load MCP tools for {module_name}: {e}")
        
        # Create agent instance
        agent = module_metadata.agent_class(provider=self.config.provider, model=self.config.model, tools=tools)
        self._agent_instances[module_name] = agent
        
        self.logger.info(f"Initialized agent for module: {module_name}")
        return agent
    
    async def initialize(self, requested_modules: Optional[List[str]] = None):
        """Initialize the supervisor with the requested modules"""
        if self._initialized:
            self.logger.info("Supervisor already initialized")
            return
        
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
        
        # Create and compile graph
        self._graph = self._create_dynamic_graph(execution_order)
        self._app = self._graph.compile(checkpointer=self.memory)
        
        self._initialized = True
        self.logger.info(f"Supervisor initialized with {len(execution_order)} modules and simulation tools")
    
    # =================
    # DYNAMIC GRAPH CREATION
    # =================
    
    def _create_dynamic_graph(self, execution_order: List[str]) -> StateGraph:
        """Create a dynamic graph based on registered modules"""
        workflow = StateGraph(SupervisorState)
        
        # Add standard nodes
        workflow.add_node("welcome", self._welcome_node)
        workflow.add_node("run_simulation", self._run_simulation_node)
        workflow.add_node("completion", self._completion_node)
        workflow.add_node("error_handler", self._error_handler_node)
        
        # Add simulation tools node if available
        if self.simulation_tools:
            workflow.add_node("simulation_tools", ToolNode(self.simulation_tools))
        
        # Add module nodes dynamically
        for module_name in execution_order:
            node_name = f"module_{module_name}"
            workflow.add_node(node_name, self._create_module_node(module_name))
        
        # Add edges
        workflow.add_edge(START, "welcome")
        workflow.add_conditional_edges("welcome", self._route_from_welcome)
        
        # Chain module nodes based on execution order
        for i, module_name in enumerate(execution_order):
            current_node = f"module_{module_name}"
            
            if i == len(execution_order) - 1:
                # Last module - routes to simulation execution
                workflow.add_conditional_edges(current_node, 
                    lambda state, mn=module_name: self._route_from_module(state, mn, is_last=True))
            else:
                # Intermediate module - routes to next module
                next_module = execution_order[i + 1]
                workflow.add_conditional_edges(current_node,
                    lambda state, mn=module_name, nm=next_module: self._route_from_module(state, mn, next_module=nm))
        
        # Simulation execution routing
        workflow.add_conditional_edges("run_simulation", self._route_from_simulation)
        if self.simulation_tools:
            workflow.add_conditional_edges("simulation_tools", self._route_after_simulation_tools)
        
        workflow.add_edge("completion", END)
        workflow.add_edge("error_handler", END)
        
        return workflow
    
    def _create_module_node(self, module_name: str) -> Callable:
        """Create a node function for a specific module"""
        
        # Subgraph for module execution taking the SupervisorState as input and returning the SupervisorState
        async def module_node(state: SupervisorState) -> SupervisorState:
            """Dynamic module node implementation"""
            module_metadata = self.registry.get_module(module_name)
            if not module_metadata:
                return self._create_error_state(state, f"Module '{module_name}' not found")
            
            self.logger.info(f"Executing module: {module_name}")
            print(f"\n{'='*60}")
            print(f"📋 MODULE: {module_metadata.display_name.upper()}")
            print(f"{'='*60}")
            print(f"Description: {module_metadata.description}")
            
            try:
                # Get agent instance
                if module_name not in self._agent_instances:
                    await self._setup_agent_instance(module_name)
                
                agent = self._agent_instances[module_name]
                
                # Execute the module
                thread_id = f"{module_name}_{hash(str(state.get('session_metadata', {})))}"
                # Use InterruptManager:
                interrupt_manager = InterruptManager(self.logger)
                result = await interrupt_manager.execute_module_agent(agent, thread_id, "")
                
                # Create module result
                if isinstance(result, dict):
                    module_result = ModuleResult(
                        module_name=module_name,
                        status=ModuleStatus.COMPLETED,
                        parameters=result['parameters'],
                        cli_parameters=result['cli_parameters'],
                        thread_id=thread_id
                    )
                    
                    # Update state
                    updated_results = state.get('module_results', {}).copy()
                    updated_results[module_name] = module_result
                    
                    return {
                        **state,
                        'current_stage': SupervisorStage.MODULE_EXECUTION,
                        'current_module': module_name,
                        'module_results': updated_results,
                        'error_message': None
                    }
                else:
                    return self._create_error_state(state, f"Module '{module_name}' returned invalid result")
                    
            except Exception as e:
                self.logger.error(f"Module {module_name} failed: {e}")
                return self._create_error_state(state, f"Module '{module_name}' failed: {str(e)}")
        
        return module_node
    
    # =================
    # Vitess Simulation Node
    # =================
    
    def _run_simulation_node(self, state: SupervisorState) -> SupervisorState:
        """Simulation execution node - runs simulation directly using module results"""
        self.logger.info("Entering simulation execution phase")
        print(f"\n{'='*60}")
        print("🚀 RUNNING SIMULATION")
        print(f"{'='*60}")
        
        # Extract module results from state
        module_results = state.get('module_results', {})
        execution_order = state.get('execution_order', [])
        
        print(f"Executing simulation with {len(module_results)} configured modules:")
        for module in execution_order:
            if module in module_results:
                result = module_results[module]
                cli_params = result.cli_parameters if hasattr(result, 'cli_parameters') else result.get('cli_parameters', '')
                param_count = len(cli_params.split()) if cli_params else 0
                print(f"   ✅ {module}: {param_count} parameters")
            else:
                print(f"   ❌ {module}: Missing parameters")
        
        print("\nStarting simulation execution...")
        
        # Create system message for simulation execution
        simulation_system_prompt = SystemMessage(content=f"""
You are a neutron simulation executor. All modules have been configured and you need to run the simulation.

IMPORTANT: You must call the run_simulation tool with these EXACT parameters:

Tool Call Required:
```
run_simulation(
    module_results={module_results},
    execution_order={execution_order},
    execute=true
)
```

Module Summary:
- Configured modules: {list(module_results.keys())}
- Execution order: {execution_order}
- Total modules: {len(module_results)}

Each module has generated CLI parameters that will be combined into a simulation pipeline.

Execute the simulation immediately using the run_simulation tool with the exact parameters shown above.
Do not modify or interpret the module_results data - pass it exactly as provided.
""")

        try:
            messages = [simulation_system_prompt]
            response = self.llm.invoke(messages)
            self.logger.info("LLM response received successfully")
        except Exception as e:
            self.logger.error(f"LLM invocation failed: {e}")
            response = None

        # Update messages
        updated_messages = state.get('messages', []) + messages + [response]

        self.logger.info(f"Updated message after run simulation llm invocation: {updated_messages}")

        return {
            'messages': updated_messages
        }
        
    
    def _route_from_simulation(self, state: SupervisorState) -> str:
        """Route from simulation execution based on tools availability"""
        last_message = state['messages'][-1]
        self.logger.info(f"Last message after run simulation node {last_message}")
        
        # Check for tool calls only if tools are available
        if (self.simulation_tools and 
            hasattr(last_message, 'tool_calls') and 
            last_message.tool_calls
            ):
            self.logger.info('Tool calls detected, routing to simulation tools')
            return "simulation_tools"
    
        else: 
            self.logger.info("There is a problem with simulation tool calling, particularly with LLM can't understand the instruction.")
            return END
        
        
    def _route_after_simulation_tools(self, state: SupervisorState) -> str:
        """Route after simulation tools execution"""

        
        last_message = state['messages'][-1].content
        self.logger.info("Processing simulation execution results")
        
        
        try:
            parsed_message = json.loads(last_message)
            validation_status = parsed_message.get('simulation_finish', False)
        except (json.JSONDecodeError, TypeError) as e:
            self.logger.error(f"Failed to parse simulation result: {e}")
            return END
        
        if validation_status:
            self.logger.info("Simulation is executed succesfully, routing to finalize")
            return 'completion'
        else:
            self.logger.info("Simulation is exectued but not run sucessfully.")
            return END
                
    
    # =================
    # STANDARD NODE IMPLEMENTATIONS
    # =================
    
    def _welcome_node(self, state: SupervisorState) -> SupervisorState:
        """Welcome node with dynamic module information - automatically proceeds to configuration"""
        
        # Show available modules
        modules_info = []
        execution_order = self.registry.get_execution_order()
        
        for module_name in execution_order:
            module_metadata = self.registry.get_module(module_name)
            if module_metadata:
                optional_text = " (optional)" if module_metadata.optional else ""
                modules_info.append(f"{module_metadata.order}. **{module_metadata.display_name}**{optional_text}: {module_metadata.description}")
        
        simulation_info = f"\n🚀 **Simulation Execution**: Automatic execution of configured simulation" if self.simulation_tools else ""
        
        welcome_text = self.config.welcome_message + "\n\n**Available Modules:**\n" + "\n".join(modules_info) + simulation_info
        
        # Add explanation about Vitess AI Agent
        vitess_explanation = """

🤖 **About Vitess AI Agent:**
The Vitess AI Agent is an intelligent simulation configuration system designed to help you set up neutron scattering simulations using the Vitess simulation framework. This system uses specialized AI agents for each simulation module to guide you through the configuration process.

**How it works:**
- Each module has a dedicated AI agent that understands the specific parameters and requirements
- The agents will ask you questions about your simulation needs and provide intelligent recommendations
- All modules will be configured automatically, and then the simulation will be executed
- The system handles parameter validation and generates the appropriate CLI commands

**Process:**
1. Configuration: Each module agent will guide you through setting up parameters
2. Validation: Parameters are validated using specialized tools
3. Execution: The complete simulation is automatically executed
4. Results: You'll receive the simulation results and configuration summary

🚀 **Starting simulation configuration process automatically...**
        """
        
        full_welcome = welcome_text + vitess_explanation
        print(full_welcome)
        
        # Automatically proceed to module execution
        execution_order = self.registry.get_execution_order()
        
        return {
            'messages': [HumanMessage(content="Automatic start")],
            'current_stage': SupervisorStage.MODULE_EXECUTION,
            'execution_order': execution_order,
            'pending_modules': execution_order.copy(),
            'current_module': execution_order[0] if execution_order else None,
            'module_results': {},
            'session_metadata': {'start_intent': 'automatic_start'},
            'cli_generation_ready': False,
            'error_message': None
        }
    
    def _completion_node(self, state: SupervisorState) -> SupervisorState:
        """Enhanced completion node with CLI information"""
        print(f"\n{'='*60}")
        print("🎉 VITESS SIMULATION CONFIGURATION COMPLETED and EXECUTED")
        print(f"{'='*60}")
        
        # Generate summary
        module_results = state.get('module_results', {})
        completed_modules = [name for name, result in module_results.items() 
                           if (hasattr(result, 'status') and result.status == ModuleStatus.COMPLETED) or
                              (isinstance(result, dict) and result.get('status') == 'completed')]
        
        print(f"\n📋 **CONFIGURATION SUMMARY:**")
        print(f"✅ Completed modules: {len(completed_modules)}")
        
        for module_name in completed_modules:
            module_metadata = self.registry.get_module(module_name)
            if module_metadata:
                print(f"   {module_metadata.order}. {module_metadata.display_name}")

        
        return {
            **state,
            'current_stage': SupervisorStage.COMPLETION,
            'error_message': None
        }
    
    def _error_handler_node(self, state: SupervisorState) -> SupervisorState:
        """Error handler node"""
        error_msg = state.get('error_message', 'Unknown error occurred')
        current_module = state.get('current_module', 'unknown')
        
        print(f"\n❌ **ERROR in {current_module.upper()} module**")
        print(f"Error: {error_msg}")
        print("Configuration process terminated.")
        
        return {
            **state,
            'current_stage': SupervisorStage.ERROR
        }
    
    # =================
    # ROUTING FUNCTIONS
    # =================
    
    def _route_from_welcome(self, state: SupervisorState) -> str:
        """Route from welcome to first module or error"""
        if state.get('current_stage') == SupervisorStage.MODULE_EXECUTION:
            execution_order = state.get('execution_order', [])
            if execution_order:
                first_module = execution_order[0]
                return f"module_{first_module}"
        
        if state.get('current_stage') == SupervisorStage.ERROR:
            return "error_handler"
        
        # If we're still in welcome stage, automatically proceed to module execution
        execution_order = self.registry.get_execution_order()
        if execution_order:
            first_module = execution_order[0]
            return f"module_{first_module}"
        
        return "error_handler"  # No modules available
    
    def _route_from_module(self, state: SupervisorState, module_name: str, 
                          next_module: str = None, is_last: bool = False) -> str:
        """Route from a module to next module, CLI generation, or error"""
        
        module_results = state.get('module_results', {})
        current_result = module_results.get(module_name)
        
        # Check if module completed successfully
        if current_result:
            status = current_result.status if hasattr(current_result, 'status') else current_result.get('status')
            if status == ModuleStatus.COMPLETED or status == 'completed':
                if is_last:
                    # Last module completed - go to simulation execution
                    self.logger.info("All modules completed, routing to simulation execution")
                    return "run_simulation"
                elif next_module:
                    return f"module_{next_module}"
        
        # Module failed
        return "error_handler"
    
    # =================
    # HELPER METHODS
    # =================
    
    def _create_error_state(self, state: SupervisorState, error_message: str) -> SupervisorState:
        """Create an error state"""
        return {
            **state,
            'current_stage': SupervisorStage.ERROR,
            'error_message': error_message
        }
    
    # =================
    # PUBLIC API
    # =================
    
    async def run(self, thread_id: str = "supervisor_default", 
                  requested_modules: Optional[List[str]] = None) -> Dict[str, Any]:
        """Run the complete simulation configuration and execution process"""
        
        # Initialize if needed
        if not self._initialized:
            await self.initialize(requested_modules)
        
        self.logger.info(f"Starting configuration process with thread_id: {thread_id}")
        
        config = {"configurable": {"thread_id": thread_id}}
        
        input_state = {
            "messages": [],
            "current_stage": SupervisorStage.WELCOME,
            "module_results": {},
            "current_module": None,
            "execution_order": [],
            "pending_modules": [],
            "current_agent_thread": "",
            "error_message": None,
            "user_preferences": {},
            "session_metadata": {"thread_id": thread_id},
            "cli_generation_ready": False,
            "cli_command": None
        }
        
        try:
            result = await self._app.ainvoke(input_state, config)
            
            if result['current_stage'] == SupervisorStage.COMPLETION:
                # Extract successful results
                module_results = result.get('module_results', {})
                parameters = {}
                cli_parameters = {}
                
                for name, result_obj in module_results.items():
                    if ((hasattr(result_obj, 'status') and result_obj.status == ModuleStatus.COMPLETED) or
                        (isinstance(result_obj, dict) and result_obj.get('status') == 'completed')):
                        
                        if hasattr(result_obj, 'parameters'):
                            parameters[name] = result_obj.parameters
                        elif isinstance(result_obj, dict):
                            parameters[name] = result_obj.get('parameters', {})
                        
                        if hasattr(result_obj, 'cli_parameters'):
                            cli_parameters[name] = result_obj.cli_parameters
                        elif isinstance(result_obj, dict):
                            cli_parameters[name] = result_obj.get('cli_parameters', '')
                
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
                        if ((hasattr(res, 'status') and res.status == ModuleStatus.COMPLETED) or
                            (isinstance(res, dict) and res.get('status') == 'completed'))
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
        if not self._initialized:
            return SupervisorStatus(
                status="not_initialized",
                current_stage="none",
                available_modules=self.list_modules()
            )
        
        config = {"configurable": {"thread_id": thread_id}}
        state = self._app.get_state(config)
        
        if not state.values:
            return SupervisorStatus(
                status="not_started",
                current_stage="none",
                available_modules=self.list_modules()
            )
        
        module_results = state.values.get('module_results', {})
        completed = [
            name for name, res in module_results.items() 
            if ((hasattr(res, 'status') and res.status == ModuleStatus.COMPLETED) or
                (isinstance(res, dict) and res.get('status') == 'completed'))
        ]
        total_modules = len(state.values.get('execution_order', []))
        
        return SupervisorStatus(
            status="completed" if len(completed) == total_modules else "in_progress",
            current_stage=state.values.get('current_stage', SupervisorStage.WELCOME),
            current_module=state.values.get('current_module'),
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
        state = self._app.get_state(config)
        
        module_results = state.values.get('module_results', {})
        
        return ConfigurationExport(
            simulation_configuration={
                f"{name}_parameters": (result.parameters if hasattr(result, 'parameters') 
                                     else result.get('parameters', {}))
                for name, result in module_results.items()
                if ((hasattr(result, 'status') and result.status == ModuleStatus.COMPLETED) or
                    (isinstance(result, dict) and result.get('status') == 'completed'))
            },
            metadata={
                "thread_id": thread_id,
                "supervisor_version": "2.0.0",
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
    config = SupervisorConfigBuilder.create(provider=provider, model=model)
    supervisor = SupervisorAgent(config, simulation_tools_path=global_config.SUPERVISOR_MCP_PATH)
    supervisor.add_default_modules()
    await supervisor.initialize()
    return supervisor


# =================
# USAGE EXAMPLES
# =================

def show_execution_order(supervisor: SupervisorAgent):
    """Show what order modules will execute in"""
    modules = supervisor.list_modules()
    sorted_modules = sorted(modules, key=lambda m: m['order'])
    
    print("📋 Execution Order:")
    for module in sorted_modules:
        optional_text = " (optional)" if module['optional'] else ""
        print(f"   {module['order']}. {module['display_name']}{optional_text}")


async def main():
    """Supervisor running Vitess simulation"""
    
    print("🚀 Initializing Vitess Simulation Supervisor...")
    print("=" * 50)
    
    # Example 1: Default supervisor with CLI generation
    supervisor = await create_default_supervisor(
        cli_tools_path="vitess_ai/mcp_tools/supervisor_mcp_tools.py"
    )
    show_execution_order(supervisor)

    result = await supervisor.run("simulation_001")
    print("\n" + "="*60)
    print("🏁 FINAL RESULT:")
    print("="*60)
    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
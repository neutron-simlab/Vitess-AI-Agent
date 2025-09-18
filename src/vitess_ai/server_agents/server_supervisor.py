"""
Server Supervisor Agent - Flat graph architecture for server mode

This supervisor agent uses a flat graph architecture where all module nodes
are added directly to the supervisor graph, enabling unified state management
and centralized interrupt handling.
"""

import logging
import json
from typing import Dict, List, Any, Optional, Type
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from vitess_ai.core.llms_providers import create_llm_with_fallback
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode
from pydantic import Field

from vitess_ai.schema.supervisor import (
    SupervisorConfig, SupervisorStage, 
    SupervisorStatus, ConfigurationExport
)
from vitess_ai.core.registry import ModuleRegistry
from vitess_ai.agents.base_module_agent import (
    ModuleBuilder, 
    ModuleStatus, ModuleMetadata, 
    ModuleResult
)
from vitess_ai.server_agents.base_module_agent_server import BaseModuleAgentServer
from vitess_ai.server_agents.unified_state import UnifiedState
from vitess_ai.schema.base import FillingStage
# Remove the import of BaseServerAgent since we'll use BaseModuleAgent
from vitess_ai.core.config import global_config


class ServerSupervisorAgent:
    """
    Server supervisor agent with flat graph architecture.
    
    This agent creates a flat graph where all module nodes are added directly
    to the supervisor graph, enabling unified state management and centralized
    interrupt handling for server mode.
    """
    
    def __init__(self, config: SupervisorConfig = None, simulation_tools_path: str = None):
        """Initialize the server supervisor agent"""
        self.config = config or self._create_default_config()
        self.llm = create_llm_with_fallback(provider=self.config.provider, model=self.config.model)
        self.registry = ModuleRegistry()
        
        # Simulation tools configuration
        self.simulation_tools_path = simulation_tools_path or "src/vitess_ai/mcp/supervisor_tools.py"
        self.simulation_tools = []
        
        # Runtime components
        self.agent_instances: Dict[str, BaseModuleAgentServer] = {}
        self.graph: Optional[StateGraph] = None
        self.app = None
        self.memory = InMemorySaver()
        self.initialized = False
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        self._setup_logging()
        self.logger.info("Server supervisor agent initialized with logging enabled")
    
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
        from vitess_ai.server_agents.readin_module_agent_server import ReadInModuleAgentServer
        
        module = ModuleBuilder.create(
            name="readin",
            display_name="Read-in Parameters",
            description="Configure neutron input parameters and initial conditions",
            agent_class=ReadInModuleAgentServer,  # Use server agent class
            config_path=config_path or global_config.READIN_MCP_PATH,
            order=1
        )
        self.register_module(module)
    
    def add_guide_module(self, config_path: str = None) -> None:
        """Add the standard guide module"""  
        from vitess_ai.server_agents.guide_module_agent_server import GuideModuleAgentServer
        
        module = ModuleBuilder.create(
            name="guide",
            display_name="Guide Parameters", 
            description="Configure neutron guide specifications and geometry",
            agent_class=GuideModuleAgentServer,  # Use server agent class
            config_path=config_path or global_config.GUIDE_MCP_PATH,
            order=2
        )
        self.register_module(module)
    
    def add_writeout_module(self, config_path: str = None) -> None:
        """Add the standard writeout module"""
        from vitess_ai.server_agents.writeout_module_agent_server import WriteoutModuleAgentServer
        
        module = ModuleBuilder.create(
            name="writeout",
            display_name="Writeout Parameters",
            description="Configure output settings and data formats", 
            agent_class=WriteoutModuleAgentServer,  # Use server agent class
            config_path=config_path or global_config.WRITEOUT_MCP_PATH,
            order=3
        )
        self.register_module(module)
    
    def add_custom_module(
        self,
        name: str,
        display_name: str,
        description: str,
        agent_class: Type[BaseModuleAgentServer],  # Use server agent class
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
    
    async def _setup_agent_instance(self, module_name: str) -> BaseModuleAgentServer:
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
        agent = module_metadata.agent_class(
            provider=self.config.provider, 
            model=self.config.model, 
            tools=tools
        )
        
        self.agent_instances[module_name] = agent
        
        self.logger.info(f"Initialized agent for module: {module_name}")
        return agent
    
    async def initialize(self, requested_modules: Optional[List[str]] = None):
        """Initialize the supervisor with the requested modules"""
        if self.initialized:
            self.logger.info("Server supervisor already initialized")
            return
        
        self.logger.info("Initializing Server Supervisor...")
        
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
        self.app = self.graph.compile(checkpointer=self.memory)
        
        self.initialized = True
        self.logger.info(f"Server supervisor initialized with {len(execution_order)} modules and simulation tools")
    
    # =================
    # FLAT GRAPH CREATION
    # =================
    
    def _create_flat_graph(self, execution_order: List[str]) -> StateGraph:
        """Create a flat graph with all module nodes added directly"""
        workflow = StateGraph(UnifiedState)
        
        # Add supervisor nodes
        workflow.add_node("supervisor_welcome", self._welcome_node)
        workflow.add_node("supervisor_run_simulation", self._run_simulation_node)
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
            # Welcome routing
            workflow.add_conditional_edges(
                f"{module_name}_welcome", 
                lambda state, mn=module_name: self._route_module_welcome(state, mn)
            )
            
            # Setup to params config
            workflow.add_edge(f"{module_name}_default_setup", f"{module_name}_params_config")
            workflow.add_edge(f"{module_name}_customize_setup", f"{module_name}_params_config")
            
            # Params config routing
            workflow.add_conditional_edges(
                f"{module_name}_params_config",
                lambda state, mn=module_name: self._route_module_params_config(state, mn)
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
        workflow.add_conditional_edges("supervisor_run_simulation", self._route_from_simulation)
        if self.simulation_tools:
            workflow.add_conditional_edges("supervisor_simulation_tools", self._route_after_simulation_tools)
        
        workflow.add_edge("supervisor_completion", END)
        workflow.add_edge("supervisor_error_handler", END)
        
        return workflow
    
    # =================
    # SUPERVISOR NODE IMPLEMENTATIONS
    # =================
    
    def _welcome_node(self, state: dict) -> dict:
        """Welcome node with dynamic module information"""
        self.logger.info("Server supervisor welcome node triggered.")
        
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
        
        # Return welcome message in messages for streaming
        user_message = state.get('messages', [])[0] if state.get('messages') else HumanMessage(content="Start")
        return {
            'messages': [
                user_message,
                AIMessage(content=full_welcome)
            ],
            'current_stage': SupervisorStage.MODULE_EXECUTION,
            'execution_order': execution_order,
            'pending_modules': execution_order.copy(),
            'module_results': {},
            'thread_id': state.get('thread_id', ""),
            'user_id': state.get('user_id', ""),
            'cli_generation_ready': False,
            'error_message': None,
        }
    
    def _run_simulation_node(self, state: dict) -> dict:
        """Simulation execution node - runs simulation directly using module results"""
        self.logger.info("Entering simulation execution phase")
        
        # Extract module results from state
        module_results = state.get('module_results', {})
        execution_order = state.get('execution_order', [])
        
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

CRITICAL: You must call the run_simulation tool with execute=true to actually run the simulation.
The tool expects:
- module_results: Dictionary with module results (already provided)
- execution_order: List of module names in execution order (already provided)  
- execute: Boolean set to true to actually run the simulation

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

        return {
            'messages': updated_messages
        }
    
    def _completion_node(self, state: dict) -> dict:
        """Enhanced completion node with CLI information"""
        
        # Generate summary
        module_results = state.get('module_results', {})
        completed_modules = [name for name, result in module_results.items() 
                           if result.status == ModuleStatus.COMPLETED]
        
        completion_message = f"""
{'='*60}
🎉 VITESS SIMULATION CONFIGURATION COMPLETED and EXECUTED
{'='*60}

📋 **CONFIGURATION SUMMARY:**
✅ Completed modules: {len(completed_modules)}
"""
        
        for module_name in completed_modules:
            module_metadata = self.registry.get_module(module_name)
            if module_metadata:
                completion_message += f"   {module_metadata.order}. {module_metadata.display_name}\n"
        
        # Return completion message in messages for streaming
        return {
            **state,
            'current_stage': SupervisorStage.COMPLETION,
            'error_message': None,
            'messages': state.get('messages', []) + [AIMessage(content=completion_message)]
        }
    
    def _error_handler_node(self, state: dict) -> dict:
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
            **state,
            'current_stage': SupervisorStage.ERROR,
            'messages': state.get('messages', []) + [AIMessage(content=error_message)]
        }
    
    # =================
    # ROUTING FUNCTIONS
    # =================
    
    def _route_from_welcome(self, state: dict) -> str:
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
    
    def _route_module_params_config(self, state: UnifiedState, module_name: str) -> str:
        """Route from module params config based on tool calls"""
        agent = self.agent_instances[module_name]
        return agent.route_after_params_config(state)
    
    def _route_module_tools(self, state: UnifiedState, module_name: str) -> str:
        """Route from module tools based on validation status"""
        agent = self.agent_instances[module_name]
        return agent.route_after_tools(state)
    
    def _route_module_finalize(self, state: UnifiedState, module_name: str) -> str:
        """Route from module finalize to next module or simulation"""
        execution_order = state.get('execution_order', [])
        current_index = execution_order.index(module_name)
        
        if current_index == len(execution_order) - 1:
            # Last module completed - go to simulation execution
            self.logger.info("All modules completed, routing to simulation execution")
            return "supervisor_run_simulation"
        else:
            # Go to next module
            next_module = execution_order[current_index + 1]
            return f"{next_module}_welcome"
    
    def _route_from_simulation(self, state: dict) -> str:
        """Route from simulation execution based on tools availability"""
        last_message = state['messages'][-1]
        self.logger.info(f"Last message after run simulation node {last_message}")
        
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
    
    def _route_after_simulation_tools(self, state: dict) -> str:
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
            self.logger.info("Simulation is executed successfully, routing to finalize")
            return 'supervisor_completion'
        else:
            self.logger.info("Simulation is executed but not run successfully.")
            return END
    
    # =================
    # PUBLIC API
    # =================
    
    async def run(self, user_id: str = "user-default", thread_id: str = "supervisor_default", 
                  requested_modules: Optional[List[str]] = None) -> Dict[str, Any]:
        """Run the complete simulation configuration and execution process"""
        
        # Initialize if needed
        if not self.initialized:
            await self.initialize(requested_modules)
        
        self.logger.info(f"Starting server configuration process with thread_id: {thread_id}")
        
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
                "supervisor_version": "3.0.0-server",
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

async def create_default_server_supervisor(
        provider = global_config.DEFAULT_PROVIDER, 
        model: str = global_config.DEFAULT_MODEL,
        cli_tools_path: str = None
        ) -> ServerSupervisorAgent:
    """Create server supervisor with default modules and CLI generation"""
    config = SupervisorConfig(
        provider=provider, 
        model=model
    )
    supervisor = ServerSupervisorAgent(config, simulation_tools_path=cli_tools_path)
    supervisor.add_default_modules()
    await supervisor.initialize()
    return supervisor

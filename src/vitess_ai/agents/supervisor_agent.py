"""
supervisor_agent.py - Combined Builder and Supervisor Agent
Everything you need for the scalable supervisor system in one file
"""
import logging
import json
from typing import Dict, List, Any, Optional, Callable, Type
from langchain_core.messages import SystemMessage, HumanMessage
from vitess_ai.core.llms_providers import create_llm_with_fallback
from langgraph.graph import StateGraph, MessagesState, END, START
from langgraph.checkpoint.memory import MemorySaver
from pydantic import Field

from vitess_ai.schema.supervisor_modules import (
    SupervisorConfig, SupervisorStage, 
      SupervisorStatus, ConfigurationExport
)
from vitess_ai.core.registry import ModuleRegistry

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
        welcome_message: str = None
    ) -> SupervisorConfig:
        """
        Create a supervisor config 
        
        Args:
            provider: Provider of LLM
            model: LLM model to use
            max_retries: How many times to retry failed modules
            allow_skipping: Can users skip optional modules?
            welcome_message: Custom welcome text (uses default if None)
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


# =================
# MAIN SUPERVISOR AGENT
# =================

class SupervisorAgent:
    """Supervisor agent with module registration system and built-in builders"""
    
    def __init__(self, config: SupervisorConfig = None):
        """Initialize the supervisor agent"""
        self.config = SupervisorConfigBuilder.create()
        self.llm = create_llm_with_fallback(provider=self.config.provider, model=self.config.model)
        self.registry = ModuleRegistry()
        
        # Runtime components
        self._agent_instances: Dict[str, BaseModuleAgent] = {}
        self._graph: Optional[StateGraph] = None
        self._app = None
        self.memory = MemorySaver()
        self._initialized = False
        
        # Setup logging
        self._logger = logging.getLogger(__name__)
    
    # =================
    # MODULE REGISTRATION API
    # =================
    
    def register_module(self, module_metadata: ModuleMetadata) -> None:
        """Register a new module with the supervisor"""
        self.registry.register_module(module_metadata)
        
        # Invalidate graph if already built
        if self._initialized:
            self._logger.info("New module registered, graph will be rebuilt on next run")
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
            config_path=global_config.READIN_MCP_PATH,
            order=1
        )
        self.register_module(module)

    # def add_filter_module(self, config_path: str = None) -> None:
    #     """Add the standard guide module"""  
    #     from vitess_ai.agents.filter_module_agent import FilterAgent
        
    #     module = ModuleBuilder.create(
    #         name="filter",
    #         display_name="Filter Parameters", 
    #         description="Configure filter on simulation input",
    #         agent_class=FilterAgent,
    #         config_path=global_config.FILTER_MCP_PATH,
    #         order=2
    #     )
    #     self.register_module(module)
    
    def add_guide_module(self, config_path: str = None) -> None:
        """Add the standard guide module"""  
        from vitess_ai.agents.guide_module_agent import GuideAgent
        
        module = ModuleBuilder.create(
            name="guide",
            display_name="Guide Parameters", 
            description="Configure neutron guide specifications and geometry",
            agent_class=GuideAgent,
            config_path=global_config.GUIDE_MCP_PATH,
            order=3
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
            config_path=global_config.WRITEOUT_MCP_PATH,
            order=4
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
        # self.add_filter_module()
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
                self._logger.info(f"Loaded {len(tools)} MCP tools for {module_name}")
            except Exception as e:
                self._logger.warning(f"Failed to load MCP tools for {module_name}: {e}")
        
        # Create agent instance
        agent = module_metadata.agent_class(provider=self.config.provider, model=self.config.model, tools=tools)
        self._agent_instances[module_name] = agent
        
        self._logger.info(f"Initialized agent for module: {module_name}")
        return agent
    
    async def initialize(self, requested_modules: Optional[List[str]] = None):
        """Initialize the supervisor with the requested modules"""
        if self._initialized:
            self._logger.info("Supervisor already initialized")
            return
        
        self._logger.info("Initializing Supervisor...")
        
        # Basic validation 
        issues = self.registry.validate_modules()
        if issues:
            self._logger.warning(f"Module validation issues: {issues}")
        
        # Get execution order
        try:
            execution_order = self.registry.get_execution_order(requested_modules)
            self._logger.info(f"Execution order: {execution_order}")
        except Exception as e:
            raise ValueError(f"Failed to get execution order: {e}")
        
        # Setup agent instances for all modules in execution order
        for module_name in execution_order:
            await self._setup_agent_instance(module_name)
        
        # Create and compile graph
        self._graph = self._create_dynamic_graph(execution_order)
        self._app = self._graph.compile(checkpointer=self.memory)
        
        self._initialized = True
        self._logger.info(f"Supervisor initialized with {len(execution_order)} modules")
    
    # =================
    # DYNAMIC GRAPH CREATION
    # =================
    
    def _create_dynamic_graph(self, execution_order: List[str]) -> StateGraph:
        """Create a dynamic graph based on registered modules"""
        workflow = StateGraph(SupervisorState)
        
        # Add standard nodes
        workflow.add_node("welcome", self._welcome_node)
        workflow.add_node("completion", self._completion_node)
        workflow.add_node("error_handler", self._error_handler_node)
        
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
                # Last module - routes to completion
                workflow.add_conditional_edges(current_node, 
                    lambda state, mn=module_name: self._route_from_module(state, mn, is_last=True))
            else:
                # Intermediate module - routes to next module
                next_module = execution_order[i + 1]
                workflow.add_conditional_edges(current_node,
                    lambda state, mn=module_name, nm=next_module: self._route_from_module(state, mn, next_module=nm))
        
        workflow.add_edge("completion", END)
        workflow.add_edge("error_handler", END)
        
        return workflow
    
    def _create_module_node(self, module_name: str) -> Callable:
        """Create a node function for a specific module"""
        
        async def module_node(state: SupervisorState) -> SupervisorState:
            """Dynamic module node implementation"""
            module_metadata = self.registry.get_module(module_name)
            if not module_metadata:
                return self._create_error_state(state, f"Module '{module_name}' not found")
            
            self._logger.info(f"Executing module: {module_name}")
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
                result = await agent.run("", thread_id)
                
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
                self._logger.error(f"Module {module_name} failed: {e}")
                return self._create_error_state(state, f"Module '{module_name}' failed: {str(e)}")
        
        return module_node
    
    # =================
    # NODE IMPLEMENTATIONS
    # =================
    
    def _welcome_node(self, state: SupervisorState) -> SupervisorState:
        """Welcome node with dynamic module information"""
        
        # Show available modules
        modules_info = []
        execution_order = self.registry.get_execution_order()
        
        for module_name in execution_order:
            module_metadata = self.registry.get_module(module_name)
            if module_metadata:
                optional_text = " (optional)" if module_metadata.optional else ""
                modules_info.append(f"{module_metadata.order}. **{module_metadata.display_name}**{optional_text}: {module_metadata.description}")
        
        welcome_text = self.config.welcome_message + "\n\n**Available Modules:**\n" + "\n".join(modules_info)
        print(welcome_text)
        
        user_input = input("\nSupervisor: ").strip()
        
        # Use LLM to interpret user intent
        system_prompt = SystemMessage(content="""
You are analyzing user input to determine their intent in a simulation configuration system.

Classify the user's response into one of these categories:
- "START": User wants to begin the configuration process (e.g., "start", "begin", "let's go", "yes", "ready")
- "HELP": User wants more information or help (e.g., "help", "what is this", "explain", "info") 
- "UNCLEAR": User input is unclear or unrelated

Respond with only one word: START, HELP, or UNCLEAR
        """)
        
        messages = [system_prompt, HumanMessage(content=user_input)]
        response = self.llm.invoke(messages)
        intent = response.content.strip().upper()
        
        if intent == "START":
            print("🚀 Starting simulation configuration process...")
            execution_order = self.registry.get_execution_order()
            
            return {
                'messages': [HumanMessage(content=user_input)],
                'current_stage': SupervisorStage.MODULE_EXECUTION,
                'execution_order': execution_order,
                'pending_modules': execution_order.copy(),
                'current_module': execution_order[0] if execution_order else None,
                'module_results': {},
                'session_metadata': {'start_intent': user_input},
                'error_message': None
            }
        elif intent == "HELP":
            self._show_help()
            return state  # Stay in welcome
        else:
            print("I'm not sure what you mean. Please type something like 'start' to begin or 'help' for more information.")
            return state  # Stay in welcome for retry
    
    def _completion_node(self, state: SupervisorState) -> SupervisorState:
        """Completion node with dynamic results"""
        print(f"\n{'='*60}")
        print("🎉 SIMULATION CONFIGURATION COMPLETED!")
        print(f"{'='*60}")
        
        # Generate summary
        module_results = state.get('module_results', {})
        completed_modules = [name for name, result in module_results.items() 
                           if result.status == ModuleStatus.COMPLETED]
        
        print(f"\n📋 **CONFIGURATION SUMMARY:**")
        print(f"✅ Completed modules: {len(completed_modules)}")
        
        for module_name in completed_modules:
            module_metadata = self.registry.get_module(module_name)
            if module_metadata:
                print(f"   {module_metadata.order}. {module_metadata.display_name}")
        
        print(f"\n📄 Configuration ready for export")
        
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
        
        return "welcome"  # Stay in welcome
    
    def _route_from_module(self, state: SupervisorState, module_name: str, 
                          next_module: str = None, is_last: bool = False) -> str:
        """Route from a module to next module, completion, or error"""
        
        module_results = state.get('module_results', {})
        current_result = module_results.get(module_name)
        
        # Check if module completed successfully
        if current_result and current_result.status == ModuleStatus.COMPLETED:
            if is_last:
                return "completion"
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
    
    def _show_help(self):
        """Show help information"""
        execution_order = self.registry.get_execution_order()
        
        help_text = f"""
📖 **HELP - Independent Module Configuration**

This system will guide you through {len(execution_order)} independent modules:
"""
        
        for module_name in execution_order:
            module_metadata = self.registry.get_module(module_name)
            if module_metadata:
                optional_text = " (optional)" if module_metadata.optional else " (required)"
                help_text += f"\n{module_metadata.order}. **{module_metadata.display_name}**{optional_text}\n   {module_metadata.description}"
        
        help_text += """

Each module is independent and has a specialized AI agent that will:
- Ask you questions about your simulation needs
- Provide default recommendations  
- Validate your parameter choices
- Generate the final configuration

Modules run in order, but each one is self-contained.
Type 'start' when you're ready to begin!
        """
        print(help_text)
    
    # =================
    # PUBLIC API
    # =================
    
    async def run(self, thread_id: str = "supervisor_default", 
                  requested_modules: Optional[List[str]] = None) -> Dict[str, Any]:
        """Run the complete simulation configuration process"""
        
        # Initialize if needed
        if not self._initialized:
            await self.initialize(requested_modules)
        
        self._logger.info(f"Starting configuration process with thread_id: {thread_id}")
        
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
            "session_metadata": {"thread_id": thread_id}
        }
        
        try:
            result = await self._app.ainvoke(input_state, config)
            
            if result['current_stage'] == SupervisorStage.COMPLETION:
                # Extract successful results
                parameters = {
                    name: result_obj.parameters 
                    for name, result_obj in result.get('module_results', {}).items()
                    if result_obj.status == ModuleStatus.COMPLETED
                }
                cli_parameters = {
                    name: result_obj.cli_parameters
                    for name, result_obj in result.get('module_results', {}).items()
                    if result_obj.status == ModuleStatus.COMPLETED
                }
                
                return {
                    "status": "success",
                    "simulation_config": parameters,
                    "cli_parameters": cli_parameters,
                    "completed_modules": list(parameters.keys()),
                    "execution_order": result.get('execution_order', [])
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
            self._logger.error(f"Configuration failed: {e}")
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
        completed = [name for name, res in module_results.items() if res.status == ModuleStatus.COMPLETED]
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
                f"{name}_parameters": result.parameters
                for name, result in module_results.items()
                if result.status == ModuleStatus.COMPLETED
            },
            metadata={
                "thread_id": thread_id,
                "supervisor_version": "2.0.0",
                "execution_order": state.values.get('execution_order', []),
                "completed_modules": status.completed_modules,
                "total_modules": len(state.values.get('execution_order', [])),
                "session_info": state.values.get('session_metadata', {})
            }
        )


# =================
# CONVENIENCE FACTORY FUNCTIONS
# =================

async def create_default_supervisor(
        provider = global_config.DEFAULT_PROVIDER, 
        model: str = global_config.DEFAULT_MODEL
        ) -> SupervisorAgent:
    """Create supervisor with default modules (readin, guide, writeout)"""
    config = SupervisorConfigBuilder.create(provider=provider, model=model)
    supervisor = SupervisorAgent(config)
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
    """Example: Different ways to use the combined supervisor"""
    
    print("🚀 Initializing Neutron Simulation Supervisor...")
    print("=" * 50)
    
    # Example 1: Default supervisor
    print("\n1️⃣ Default supervisor (readin → guide → writeout):")
    supervisor = await create_default_supervisor()
    show_execution_order(supervisor)

    result = await supervisor.run("simulation_001")
    print("\n" + "="*60)
    print("🏁 FINAL RESULT:")
    print("="*60)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
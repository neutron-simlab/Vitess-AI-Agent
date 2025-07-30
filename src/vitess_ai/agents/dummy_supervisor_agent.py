"""
Unified SupervisorAgent - Single class that handles everything
Orchestrates ReadInAgent, GuideAgent, and WriteoutAgent in sequence
"""
import json
from typing import Optional, Dict, Any
from enum import Enum
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END, START, MessagesState
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from vitess_ai.schema.readin_module import ReadInParameters
from vitess_ai.schema.guide_module import GuideParameters
from vitess_ai.schema.writeout_module import WriteoutParameters

# Import your existing agents (adjust paths as needed)
from vitess_ai.agents.readin_module_agent import ReadInAgent
from vitess_ai.agents.guide_module_agent import GuideAgent
from vitess_ai.agents.writeout_module_agent import WriteoutAgent


class SimulationStage(Enum):
    """Enumeration of simulation configuration stages"""
    WELCOME = "welcome"
    READIN = "readin"
    GUIDE = "guide"
    WRITEOUT = "writeout"
    COMPLETED = "completed"
    ERROR = "error"


class SupervisorState(MessagesState):
    """State for the supervisor agent"""
    current_stage: SimulationStage
    readin_params: Optional[ReadInParameters] = None
    guide_params: Optional[GuideParameters] = None
    writeout_params: Optional[WriteoutParameters] = None
    readin_completed: bool = False
    guide_completed: bool = False
    writeout_completed: bool = False
    current_agent_thread: str = ""
    error_message: Optional[str] = None


class SupervisorAgent:
    def __init__(self, model_name: str = 'gpt-4o-mini-2024-07-18'):
        """Initialize the SupervisorAgent"""
        self.llm = ChatOpenAI(model=model_name, temperature=0)
        self.name = "Neutron Simulation Supervisor"
        self.model_name = model_name
        
        # Sub-agents
        self.readin_agent: Optional[ReadInAgent] = None
        self.guide_agent: Optional[GuideAgent] = None
        self.writeout_agent: Optional[WriteoutAgent] = None
        
        # Agent configuration paths 
        self.agent_configs = {
            "readin": "/Users/az-ihsan/Documents/kerjaan-ihsan/post-doc/JueNA_knowledge_base/vitess-ai-agent/src/vitess_ai/mcp/readin_module_tools.py",
            "guide": "/Users/az-ihsan/Documents/kerjaan-ihsan/post-doc/JueNA_knowledge_base/vitess-ai-agent/src/vitess_ai/mcp/guide_module_tools.py", 
            "writeout": "/Users/az-ihsan/Documents/kerjaan-ihsan/post-doc/JueNA_knowledge_base/vitess-ai-agent/src/vitess_ai/mcp/writeout_module_tools.py"
        }
        
        # Welcome message
        self.welcome_message = """
🤖 **Neutron Simulation Configuration System**

Welcome! I'm your Simulation Supervisor. I'll guide you through configuring 
your neutron simulation in three sequential stages:

1️⃣ **Read-in Parameters**: Configure input parameters and initial conditions
2️⃣ **Guide Parameters**: Set up neutron guide specifications  
3️⃣ **Writeout Parameters**: Configure output settings and data formats

Each stage must be completed before proceeding to the next. I'll coordinate 
with specialized agents for each module and ensure all parameters are properly validated.

Ready to begin? Type 'start' to begin the configuration process.
        """
        
        # Create the graph and app (will be set after setup)
        self.graph = None
        self.app = None
        self.memory = MemorySaver()
        self._initialized = False

    async def setup_agents(self):
        """Setup all sub-agents with their respective MCP tools"""
        print("🔧 Setting up sub-agents...")
        
        try:
            # Setup ReadIn Agent
            readin_client = MultiServerMCPClient({
                "validation": {
                    "command": "python",
                    "args": [self.agent_configs["readin"]],
                    "transport": "stdio"
                }
            })
            readin_tools = await readin_client.get_tools()
            self.readin_agent = ReadInAgent(model_name=self.model_name, tools=readin_tools)
            print("✅ ReadIn Agent initialized")
            
            # Setup Guide Agent
            guide_client = MultiServerMCPClient({
                "validation": {
                    "command": "python",
                    "args": [self.agent_configs["guide"]],
                    "transport": "stdio"
                }
            })
            guide_tools = await guide_client.get_tools()
            self.guide_agent = GuideAgent(model_name=self.model_name, tools=guide_tools)
            print("✅ Guide Agent initialized")
            
            # Setup Writeout Agent
            writeout_client = MultiServerMCPClient({
                "validation": {
                    "command": "python",
                    "args": [self.agent_configs["writeout"]],
                    "transport": "stdio"
                }
            })
            writeout_tools = await writeout_client.get_tools()
            self.writeout_agent = WriteoutAgent(model_name=self.model_name, tools=writeout_tools)
            print("✅ Writeout Agent initialized")
            
            print("🎉 All agents ready!")
            
        except Exception as e:
            print(f"❌ Agent setup failed: {str(e)}")
            raise

    def _create_graph(self) -> StateGraph:
        """Create the supervisor workflow graph"""
        workflow = StateGraph(SupervisorState)
        
        # Add nodes
        workflow.add_node("welcome", self._welcome_node)
        workflow.add_node("readin_stage", self._readin_stage_node)
        workflow.add_node("guide_stage", self._guide_stage_node)
        workflow.add_node("writeout_stage", self._writeout_stage_node)
        workflow.add_node("completion", self._completion_node)
        workflow.add_node("error_handler", self._error_handler_node)
        
        # Add edges
        workflow.add_edge(START, "welcome")
        workflow.add_conditional_edges("welcome", self._route_from_welcome)
        workflow.add_conditional_edges("readin_stage", self._route_from_readin)
        workflow.add_conditional_edges("guide_stage", self._route_from_guide)
        workflow.add_conditional_edges("writeout_stage", self._route_from_writeout)
        workflow.add_edge("completion", END)
        workflow.add_edge("error_handler", END)
        
        return workflow

    async def initialize(self):
        """Initialize the supervisor - must be called before use"""
        if self._initialized:
            print("🔄 Supervisor already initialized")
            return
            
        print("🚀 Initializing Neutron Simulation Supervisor...")
        
        # Setup agents
        await self.setup_agents()
        
        # Create graph
        self.graph = self._create_graph()
        self.app = self.graph.compile(checkpointer=self.memory)
        
        self._initialized = True
        print("✅ Supervisor initialization complete!")

    # =================
    # NODE HANDLERS
    # =================

    def _welcome_node(self, state: SupervisorState) -> SupervisorState:
        """Welcome node - introduce the system and get user ready"""
        print(self.welcome_message)
        
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
            return {
                'messages': [HumanMessage(content=user_input)],
                'current_stage': SimulationStage.READIN,
                'current_agent_thread': f"readin_{hash(user_input)}",
                'readin_completed': False,
                'guide_completed': False,
                'writeout_completed': False,
                'error_message': None
            }
        elif intent == "HELP":
            self._show_help()
            return state  # Stay in welcome
        else:
            print("I'm not sure what you mean. Please type something like 'start' to begin or 'help' for more information.")
            return state  # Stay in welcome for retry

    async def _readin_stage_node(self, state: SupervisorState) -> SupervisorState:
        """ReadIn stage node - handle read-in parameters configuration"""
        print("\n" + "="*60)
        print("📥 STAGE 1: READ-IN PARAMETERS CONFIGURATION")
        print("="*60)
        print("Now configuring input parameters with the ReadIn Module Agent...")
        
        try:
            if not self.readin_agent:
                raise Exception("ReadIn agent not initialized")
            
            # Run the ReadIn agent
            thread_id = state.get('current_agent_thread', 'readin_default')
            result = await self.readin_agent.run("", thread_id)
            
            if isinstance(result, dict):
               
                return {
                    'messages': state['messages'],
                    'current_stage': SimulationStage.GUIDE,
                    'current_agent_thread': f"guide_{hash(str(result))}",
                    'readin_params': result,
                    'readin_completed': True,
                    'guide_completed': state.get('guide_completed', False),
                    'writeout_completed': state.get('writeout_completed', False),
                    'error_message': None
                }
            else:
                raise Exception("ReadIn agent did not return valid parameters")
                
        except Exception as e:
            return {
                'messages': state['messages'],
                'current_stage': SimulationStage.ERROR,
                'error_message': f"ReadIn stage failed: {str(e)}"
            }

    async def _guide_stage_node(self, state: SupervisorState) -> SupervisorState:
        """Guide stage node - handle guide parameters configuration"""
        print("\n" + "="*60)
        print("🔀 STAGE 2: GUIDE PARAMETERS CONFIGURATION")
        print("="*60)
        print("Now configuring neutron guide specifications...")
        
        try:
            if not self.guide_agent:
                raise Exception("Guide agent not initialized")
            
            # Run the Guide agent
            thread_id = state.get('current_agent_thread', 'guide_default')
            result = await self.guide_agent.run("", thread_id)
            
            if isinstance(result, dict):
                
                return {
                    'messages': state['messages'],
                    'current_stage': SimulationStage.WRITEOUT,
                    'current_agent_thread': f"writeout_{hash(str(result))}",
                    'readin_params': state.get('readin_params'),
                    'guide_params': result,
                    'readin_completed': state.get('readin_completed', False),
                    'guide_completed': True,
                    'writeout_completed': state.get('writeout_completed', False),
                    'error_message': None
                }
            else:
                raise Exception("Guide agent did not return valid parameters")
                
        except Exception as e:
            return {
                'messages': state['messages'],
                'current_stage': SimulationStage.ERROR,
                'error_message': f"Guide stage failed: {str(e)}"
            }

    async def _writeout_stage_node(self, state: SupervisorState) -> SupervisorState:
        """Writeout stage node - handle writeout parameters configuration"""
        print("\n" + "="*60)
        print("📤 STAGE 3: WRITEOUT PARAMETERS CONFIGURATION")
        print("="*60)
        print("Now configuring output settings and data formats...")
        
        try:
            if not self.writeout_agent:
                raise Exception("Writeout agent not initialized")
            
            # Run the Writeout agent
            thread_id = state.get('current_agent_thread', 'writeout_default')
            result = await self.writeout_agent.run("", thread_id)
            
            if isinstance(result, dict):
                
                return {
                    'messages': state['messages'],
                    'current_stage': SimulationStage.COMPLETED,
                    'readin_params': state.get('readin_params'),
                    'guide_params': state.get('guide_params'),
                    'writeout_params': result,
                    'readin_completed': state.get('readin_completed', False),
                    'guide_completed': state.get('guide_completed', False),
                    'writeout_completed': True,
                    'error_message': None
                }
            else:
                raise Exception("Writeout agent did not return valid parameters")
                
        except Exception as e:
            return {
                'messages': state['messages'],
                'current_stage': SimulationStage.ERROR,
                'error_message': f"Writeout stage failed: {str(e)}"
            }

    def _completion_node(self, state: SupervisorState) -> SupervisorState:
        """Completion node - handle successful completion of all stages"""
        print("\n" + "="*60)
        print("🎉 SIMULATION CONFIGURATION COMPLETED!")
        print("="*60)
        
        # Generate final configuration summary
        summary = {
            "simulation_config": {
                "readin_parameters": state.get('readin_params'),
                "guide_parameters": state.get('guide_params'),
                "writeout_parameters": state.get('writeout_params')
            },
            "status": "completed",
            "all_stages_completed": True
        }
        
        print("\n📋 **FINAL CONFIGURATION SUMMARY:**")
        print(json.dumps(summary, indent=2))
        
        return {
            'messages': state['messages'],
            'current_stage': SimulationStage.COMPLETED,
            'readin_params': state.get('readin_params'),
            'guide_params': state.get('guide_params'),
            'writeout_params': state.get('writeout_params'),
            'readin_completed': True,
            'guide_completed': True,
            'writeout_completed': True,
            'error_message': None
        }

    def _error_handler_node(self, state: SupervisorState) -> SupervisorState:
        """Error handler node - handle errors and provide recovery options"""
        error_msg = state.get('error_message', 'Unknown error occurred')
        current_stage = state.get('current_stage', SimulationStage.ERROR)
        
        print(f"\n❌ **ERROR in {current_stage.value.upper()} stage**")
        print(f"Error: {error_msg}")
        print("Please restart the configuration process.")
        
        return {
            'messages': state['messages'],
            'current_stage': SimulationStage.ERROR,
            'error_message': error_msg
        }

    # =================
    # ROUTING FUNCTIONS
    # =================

    def _route_from_welcome(self, state: SupervisorState) -> str:
        """Route from welcome based on user input"""
        if state['current_stage'] == SimulationStage.READIN:
            return "readin_stage"
        elif state['current_stage'] == SimulationStage.ERROR:
            return "error_handler"
        else:
            return "welcome"  # Stay in welcome

    def _route_from_readin(self, state: SupervisorState) -> str:
        """Route from readin stage"""
        if state['current_stage'] == SimulationStage.GUIDE:
            return "guide_stage"
        else:
            return "error_handler"

    def _route_from_guide(self, state: SupervisorState) -> str:
        """Route from guide stage"""
        if state['current_stage'] == SimulationStage.WRITEOUT:
            return "writeout_stage"
        else:
            return "error_handler"

    def _route_from_writeout(self, state: SupervisorState) -> str:
        """Route from writeout stage"""
        if state['current_stage'] == SimulationStage.COMPLETED:
            return "completion"
        else:
            return "error_handler"

    # =================
    # HELPER METHODS
    # =================

    def _show_help(self):
        """Show help information"""
        help_text = """
📖 **HELP - Simulation Configuration Process**

This system will guide you through 3 stages:
1. **ReadIn**: Configure neutron input parameters (beam settings, initial conditions)
2. **Guide**: Set up neutron guide geometry (dimensions, reflectivity)  
3. **Writeout**: Configure output format and data collection settings

Each stage has a specialized AI agent that will:
- Ask you questions about your simulation needs
- Provide default recommendations
- Validate your parameter choices
- Generate the final configuration

Type 'start' when you're ready to begin!
        """
        print(help_text)

    # =================
    # PUBLIC API
    # =================

    async def run(self, thread_id: str = "supervisor_default") -> Dict[str, Any]:
        """Run the complete simulation configuration process"""
        if not self._initialized:
            await self.initialize()
        
        print("🎯 Starting complete simulation configuration...")
        
        # Configuration for the run
        config = {"configurable": {"thread_id": thread_id}}
        
        # Initialize state
        input_state = {
            "messages": [],
            "current_stage": SimulationStage.WELCOME,
            "readin_completed": False,
            "guide_completed": False,
            "writeout_completed": False,
            "current_agent_thread": "",
            "readin_params": None,
            "guide_params": None,
            "writeout_params": None,
            "error_message": None
        }
        
        try:
            # Run the complete workflow
            result = await self.app.ainvoke(input_state, config)
            
            # Return final configuration
            if result['current_stage'] == SimulationStage.COMPLETED:
                return {
                    "status": "success",
                    "simulation_config": {
                        "readin_parameters": result.get('readin_params'),
                        "guide_parameters": result.get('guide_params'),
                        "writeout_parameters": result.get('writeout_params')
                    }
                }
            else:
                return {
                    "status": "error",
                    "error_message": result.get('error_message', 'Configuration incomplete'),
                    "current_stage": result['current_stage'].value
                }
                
        except Exception as e:
            return {
                "status": "error",
                "error_message": f"Configuration process failed: {str(e)}",
                "current_stage": "unknown"
            }

    def get_status(self, thread_id: str = "supervisor_default") -> Dict[str, Any]:
        """Get current configuration status"""
        if not self._initialized:
            return {"status": "not_initialized"}
        
        config = {"configurable": {"thread_id": thread_id}}
        state = self.app.get_state(config)
        
        if not state.values:
            return {
                "status": "not_started",
                "current_stage": "none",
                "progress": "0/3"
            }
        
        # Calculate progress
        completed_stages = []
        if state.values.get('readin_completed'):
            completed_stages.append("readin")
        if state.values.get('guide_completed'):
            completed_stages.append("guide")
        if state.values.get('writeout_completed'):
            completed_stages.append("writeout")
        
        return {
            "status": "in_progress" if len(completed_stages) < 3 else "completed",
            "current_stage": state.values.get('current_stage', SimulationStage.WELCOME).value,
            "progress": f"{len(completed_stages)}/3",
            "completed_stages": completed_stages,
            "error_message": state.values.get('error_message')
        }

    def export_config(self, thread_id: str = "supervisor_default") -> str:
        """Export the final configuration as JSON"""
        status = self.get_status(thread_id)
        
        if status["status"] != "completed":
            raise ValueError(f"Configuration not complete. Current status: {status['status']}")
        
        config = {"configurable": {"thread_id": thread_id}}
        state = self.app.get_state(config)
        
        configuration = {
            "simulation_configuration": {
                "readin_parameters": state.values.get('readin_params'),
                "guide_parameters": state.values.get('guide_params'),
                "writeout_parameters": state.values.get('writeout_params')
            },
            "metadata": {
                "thread_id": thread_id,
                "supervisor_version": "1.0.0",
                "export_timestamp": "2025-01-01T00:00:00Z"
            }
        }
        
        return json.dumps(configuration, indent=2)


# =================
# USAGE EXAMPLE
# =================

async def main():
    """Example usage of the SupervisorAgent"""
    print("🚀 Initializing Neutron Simulation Supervisor...")
    
    # Create supervisor
    supervisor = SupervisorAgent()
    
    # Run the complete configuration process
    result = await supervisor.run("simulation_001")
    
    print("\n" + "="*60)
    print("🏁 FINAL RESULT:")
    print("="*60)
    print(json.dumps(result, indent=2))
    
    # Export configuration if successful
    if result["status"] == "success":
        config_json = supervisor.export_config("simulation_001")
        print("\n📄 Exported Configuration:")
        print(config_json)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
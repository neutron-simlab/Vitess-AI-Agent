"""
ReadInAgent - LangGraph Agent for Neutron Simulation Parameters Configuration
Based on the FilterAgent template, adapted for ReadInParameters
"""
import json
from typing import List, Optional
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, AIMessage
from langchain_openai import ChatOpenAI
from langchain.tools import BaseTool
from langgraph.graph import StateGraph, END, START, MessagesState
from langgraph.prebuilt import ToolNode
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from vitess_ai.schema.base import FillingStage
from vitess_ai.schema.readin_module import ReadInParameters, InitialResponseReadIn
from vitess_ai.prompts.readin_module import READIN_AGENT_PROMPT, READIN_AGENT_WELCOME


# Define the agent state
class ReadInAgentState(MessagesState):
    stage: FillingStage
    config_mode: str  # Track configuration mode (all_defaults/customize_specific/define_all)
    readin_params: Optional[ReadInParameters] = None # type: ignore
    validation_status: Optional[bool] = None # type: ignore
    params: Optional[List[str]] = None # type: ignore  

class ReadInAgent:
    def __init__(self, model_name: str, tools: List[BaseTool]=[]):
        """Initialize the ReadInAgent"""

        self.llm = ChatOpenAI(model=model_name, temperature=0)
        self.name = "ReadIn Agent"
        
        # Get MCP validation tools
        if tools:
            self.welcome_prompt = AIMessage(content=READIN_AGENT_WELCOME)
            self.mcp_tools = tools
            self.llm = self.llm.bind_tools(self.mcp_tools, parallel_tool_calls=False)
            self.sys_prompt = SystemMessage(content=READIN_AGENT_PROMPT)
        else: 
            # System prompts
            self.welcome_prompt = SystemMessage(content=READIN_AGENT_WELCOME)
            self.sys_prompt = SystemMessage(content=READIN_AGENT_PROMPT)
        
        # Create the graph
        self.graph = self._create_graph()
        
        # Add memory for conversation persistence
        self.memory = MemorySaver()
        self.app = self.graph.compile(checkpointer=self.memory)

    def _create_graph(self) -> StateGraph:
        """Create the agent graph"""
        workflow = StateGraph(ReadInAgentState)
        
        # Define nodes
        workflow.add_node("welcome", self._welcome_node)
        workflow.add_node("default_setup", self._default_setup_node)
        workflow.add_node("fully_customize", self._fully_customize_node)
        workflow.add_node("params_config", self._parameters_configuration)
        workflow.add_node("tools", ToolNode(self.mcp_tools))
        workflow.add_node("finalize", self._finalize_node)
       
        
        # Define edges 
        workflow.add_edge(START, 'welcome')
        workflow.add_conditional_edges('welcome', self._route_after_init)
        workflow.add_edge('default_setup', 'params_config')
        workflow.add_edge('fully_customize', 'params_config')
        workflow.add_conditional_edges('params_config', self._condition_parameters_config)
        workflow.add_conditional_edges('tools', self._route_after_tools)

        
        return workflow
    
    def _welcome_node(self, state: ReadInAgentState) -> ReadInAgentState:
        """Send welcome message to user"""  
        print(f"{self.welcome_prompt.content}")
        user_init_message = input("\nUser:\n").strip()
        sys_welcome_message = SystemMessage(content="❌ **Not Known**: When the user's input does not clearly indicate a choice between Default or Customize (e.g., unrelated topics like hobbies, opinions, or ambiguous language)")
        messages = [self.welcome_prompt, sys_welcome_message, HumanMessage(user_init_message)]
        structured_llm = self.llm.with_structured_output(InitialResponseReadIn) # type: ignore
        response = structured_llm.invoke(messages)
        # Store the user's choice
        config_mode = response.response #type:ignore
        
        return {
            'messages': [self.sys_prompt, *messages,],
            'stage': FillingStage(stage='processing'),
            'config_mode': config_mode
        } # type: ignore
    
    def _route_after_init(self, state: ReadInAgentState) -> str:
        """Route based on user's initial choice"""
        config_mode = state.get('config_mode', '')
        
        if config_mode == 'Custom':
            return 'fully_customize'
        elif config_mode == 'Default Setup':
            return 'default_setup'
        else:
            print("We don't know what you are going after.\n We will end the conversation.")
            return END
    
    def _parameters_configuration(self, state: ReadInAgentState) -> ReadInAgentState | str :
        """
        Guide user through parameter configuration with tool support
        """
        print("\n=== ENTERING _parameters_configuration ===")
        print(f"Current state messages count: {len(state['messages'])}")
        print(f"Config mode: {state.get('config_mode', 'not set')}")
        
        # Use LLM with tools for enhanced functionality
        response = self.llm.invoke(state['messages'])
        print(f"\nRAW RESPONSE:\n{response}")
        
        # Debug: Print what we're checking
        print(f"DEBUG: hasattr(response, 'tool_calls'): {hasattr(response, 'tool_calls')}")
        print(f"DEBUG: response.tool_calls: {getattr(response, 'tool_calls', None)}")
        
        # Always add the AI response to messages first
        updated_messages = state['messages'] + [response]
        print(f"DEBUG: Updated messages count after adding response: {len(updated_messages)}")
        
        print(f"\nAssistant:\n{response.content}") 
        if hasattr(response, 'tool_calls') and response.tool_calls: # type: ignore
            print("DEBUG: Tool calls detected, routing to tools")
            print(f"DEBUG: Returning state with {len(updated_messages)} messages")
            # try: 
            #     last_message = json.loads(last_message)
            #     print(last_message['valid'] )
            #     if last_message['valid']: 
            #         END
            #     else: 
            #         'params_config'
            # except Exception as e:
            #     print(str(e))
            return {
                'messages': updated_messages, # type: ignore
                'stage': FillingStage(stage='processing'),
                'config_mode': state.get('config_mode', ''),
            }
        else:
            print("DEBUG: No tool calls, getting user input")
            user_input = input("\nUser:\n").strip()
            final_messages = updated_messages + [HumanMessage(content=user_input)]
            print(f"DEBUG: Final messages count after user input: {len(final_messages)}")
            return {
                'messages': final_messages, # type: ignore
                'stage': FillingStage(stage='processing'),
                'config_mode': state.get('config_mode', ''),
            }
    # the workflow still need to be defined
    def _default_setup_node(self, state: ReadInAgentState) -> ReadInAgentState | str | None:
        """Handle the case where user wants the default setup. """
        print("\n=== HANDLING DEFAULT SETUP PARAMS CONFIGURATION ===")
        
        sys_default_setup_prompt = SystemMessage(content="""
        You have chosen the default setup configuration, we will handle all the setup apart from several parameters that need to fill manually.
                                               """)
        
        return {
            'messages': [*state['messages'], sys_default_setup_prompt]
        } # type: ignore

        
    # the workflow still need to be defined
    def _fully_customize_node(self, state: ReadInAgentState) -> ReadInAgentState | str | None:
        """Handle the case where user wants all default values"""
        print("\n=== HANDLING FULLY CUSTOMIZED CONFIGURATION ===")
        
        sys_fully_customize_prompt = SystemMessage(content="""
        You have choosen the fully customize cofiguration, let me guide you to fill all parameters.
        """)

        return {
            'messages': [*state['messages'], sys_fully_customize_prompt]
        } # type: ignore

        
    def _finalize_node(self, state:ReadInAgentState) -> str:
        """Handle the final step after tool calling on JSON validation"""
        print("\n=== HANDLING FINAL STEP ===")
        print("\n Not yet implemented")

        return END
    
    def _route_after_customize(self, state: ReadInAgentState) -> str:
        """Route after parameter customization selection"""
        if state.get('selected_params'):
            return 'params_config'
        else:
            return 'handle_customize'
    
    
    def _route_after_tools(self, state: ReadInAgentState) -> str:
        """Route after tool execution"""
        # Continue with parameter configuration after tool use
        last_message = state['messages'][-1].content
        print(f"\n the last message from tools calling is:\n {last_message}\n")
        try: 
            last_message = json.loads(last_message) # type: ignore
            if last_message['valid']: 
                print("Parameters filling is complete, see you!")
                return END
            else: 
                return 'params_config'
        except Exception as e:
            print(str(e))
            return 'params_config'
        # return 'params_config'
        

    def _condition_parameters_config(self, state: ReadInAgentState) -> str:
        """
        Determine if parameter configuration is complete or if tools should be called
        """
        last_message = state['messages'][-1]

        print(f"\n the last message from params_config is:\n {last_message}\n")
        
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:  #type:ignore
            print('\n we have a tools call.\n')
            return 'tools'
        else:
            # try: 
            #     last_message = json.loads(last_message)
            #     if last_message['valid']: 
            #         print("parameters filling is complete, see you!")
            #         return END
            #     else: 
            #         return 'params_config'
            # except Exception as e:
            #     print(str(e))
            return 'params_config'
    
    async def run(self, user_input: str, thread_id: str = "default") -> str:
        """Run the agent with user input"""
        # Configuration for the run
        config = {"configurable": {"thread_id": thread_id}}
        
        # Get current state
        current_state = self.app.get_state(config)  #type:ignore
        
        # Prepare input message
        user_message = HumanMessage(content=user_input)
        
        if current_state.values:
            # Continue existing conversation
            current_messages = current_state.values.get("messages", [])
            input_state = {
                "messages": current_messages + [user_message],
                "stage": current_state.values.get("stage", FillingStage(stage='processing')),
                "user_choice": current_state.values.get("user_choice", ""),
                "config_mode": current_state.values.get("config_mode", ""),
                "selected_params": current_state.values.get("selected_params", None)
            }
        else:
            # Start new conversation
            input_state = {
                "messages": [user_message],
                "stage": FillingStage(stage='processing'),
                "user_choice": "",
                "config_mode": "",
                "selected_params": None
            }
        
        # Run the graph
        result = await self.app.ainvoke(input_state, config)  #type:ignore
        
        # Extract the final response
        final_messages = result["messages"]
        if final_messages:
            # Return the last AI message
            for msg in reversed(final_messages):
                if isinstance(msg, AIMessage):
                    return msg.content  #type:ignore
        
        return "No response generated"
    
    def stream_run(self, user_input: str, thread_id: str = "default"):
        """Stream the agent execution for real-time updates"""
        config = {"configurable": {"thread_id": thread_id}}
        
        # Get current state and prepare input
        current_state = self.app.get_state(config)  #type:ignore
        user_message = HumanMessage(content=user_input)
        
        if current_state.values:
            current_messages = current_state.values.get("messages", [])
            input_state = {
                "messages": current_messages + [user_message],
                "stage": current_state.values.get("stage", FillingStage(stage='processing')),
                "user_choice": current_state.values.get("user_choice", ""),
                "config_mode": current_state.values.get("config_mode", ""),
                "selected_params": current_state.values.get("selected_params", None)
            }
        else:
            input_state = {
                "messages": [user_message],
                "stage": FillingStage(stage='processing'),
                "user_choice": "",
                "config_mode": "",
                "selected_params": None
            }
        
        # Stream the execution
        for chunk in self.app.stream(input_state, config):  #type:ignore
            yield chunk
    
    def get_conversation_history(self, thread_id: str = "default") -> List[BaseMessage]:
        """Get the conversation history for a thread"""
        config = {"configurable": {"thread_id": thread_id}}
        state = self.app.get_state(config)  #type:ignore
        return state.values.get("messages", []) if state.values else []


async def main(): 
    client = MultiServerMCPClient({
        "validation": {
            "command": "python",
            "args": ["/Users/az-ihsan/Documents/kerjaan-ihsan/post-doc/JueNA_knowledge_base/vitess-ai-agent/src/vitess_ai/mcp/readin_module_tools.py"],
            "transport": "stdio"
        }
    })  # type: ignore
    tools = await client.get_tools()
    agent = ReadInAgent(model_name='gpt-4o-mini-2024-07-18', tools=tools)

    # Example conversation flow with validation
    thread_id = "200"
    print("=== Neutron Simulation Parameters Configuration Demo ===\n")

    # Start conversation
    print("🤖 Starting conversation...")
    await agent.run("", thread_id)

# Example usage
if __name__ == "__main__":
    import asyncio
    
    asyncio.run(main())
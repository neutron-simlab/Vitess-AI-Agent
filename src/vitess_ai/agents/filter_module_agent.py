"""
Improved LangGraph Agent Template for Neutron Filter Configuration
Fixed issues with state management, I/O handling, and workflow logic
"""
from typing import List, Optional
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, AIMessage
from langchain_openai import ChatOpenAI
from langchain.tools import BaseTool
from langgraph.graph import StateGraph, END, START, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from vitess_ai.schema.filter_module import InitialResponse, FillingStage, FilterBlock
from vitess_ai.prompts.filter_module import (
    INIT_AGENT_INIT_PROMPT, 
    FILTER_AGENT_PROMPT, 
    FILTER_AGENT_WELCOME,
)

# Define the agent state
class FilterAgentState(MessagesState):
    stage: FillingStage
    user_choice: str  # Track user's initial choice (Custom/Default/Not Known)
    filter_params: Optional[FilterBlock] = None # type: ignore
    validation_status: Optional[bool] = None # type: ignore

class FilterAgent:
    def __init__(self, model_name: str, tools: List[BaseTool]=[]):
        """Initialize the LangGraph agent"""

        self.llm = ChatOpenAI(model=model_name, temperature=0)
        
        # Get MCP validation tools
        if tools:
            self.init_prompt = SystemMessage(content=INIT_AGENT_INIT_PROMPT)
            self.welcome_prompt = SystemMessage(content=FILTER_AGENT_WELCOME)
            self.mcp_tools = tools
            self.llm = self.llm.bind_tools(self.mcp_tools, parallel_tool_calls=False)
            self.sys_prompt = SystemMessage(content=FILTER_AGENT_PROMPT)
        else: 
            # System prompts
            self.init_prompt = SystemMessage(content=INIT_AGENT_INIT_PROMPT)
            self.welcome_prompt = SystemMessage(content=FILTER_AGENT_WELCOME)
            self.sys_prompt = SystemMessage(content=FILTER_AGENT_PROMPT)
        
        # Create the graph
        self.graph = self._create_graph()
        
        # Add memory for conversation persistence
        self.memory = MemorySaver()
        self.app = self.graph.compile(checkpointer=self.memory)

    def _create_graph(self) -> StateGraph:
        """Create the agent graph"""
        workflow = StateGraph(FilterAgentState)
        
        # Define nodes
        workflow.add_node("initialize", self._initialize_node)
        workflow.add_node("params_filling", self._parameters_filling)
        workflow.add_node("welcome", self._welcome_node)
        workflow.add_node("tools", ToolNode(self.mcp_tools))
        
        # Define edges 
        workflow.add_edge(START, 'welcome')
        workflow.add_edge('welcome', 'initialize')
        workflow.add_conditional_edges('initialize', self._route_after_init)
        workflow.add_conditional_edges('params_filling', self._condition_parameters_filling)
        workflow.add_conditional_edges('tools', self._route_after_tools)
        
        return workflow
    
    def _welcome_node(self, state: FilterAgentState) -> FilterAgentState:
        """Send welcome message to user"""
        print(f"{self.welcome_prompt.content}")
        
        return {
            'messages': [],
            'stage': FillingStage(stage='processing')
        } #type:ignore
    
    def _initialize_node(self, state: FilterAgentState) -> FilterAgentState:
        """
        Node to initialize the conversation and determine user's preference
        """
        user_init_message = input("\nUser:\n").strip()
        messages = [self.init_prompt, self.welcome_prompt, HumanMessage(user_init_message)]
        
        # Use structured output to classify user intent
        structured_llm = self.llm.with_structured_output(InitialResponse)
        response = structured_llm.invoke(messages)
        
        # Store the user's choice
        user_choice = response.response #type:ignore
        
        return {
            'messages': [*messages, self.sys_prompt],
            'stage': FillingStage(stage='processing'),
            'user_choice': user_choice
        } # type: ignore
    
    def _route_after_init(self, state: FilterAgentState) -> str:
        """Route based on user's initial choice"""
        user_choice = state.get('user_choice', '')
        
        if user_choice == 'Custom':
            return 'params_filling'
        elif user_choice == 'Default':
            # Handle default parameters (could add a default_params node)
            return END
        else:
            # Not Known - ask for clarification or end
            return END
    
    def _parameters_filling(self, state: FilterAgentState) -> FilterAgentState:
        """
        Guide user through parameter configuration with tool support
        """
        print(f"\n=== ENTERING _parameters_filling ===")
        print(f"Current state messages count: {len(state['messages'])}")
        
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
        if hasattr(response, 'tool_calls') and response.tool_calls:
            print("DEBUG: Tool calls detected, routing to tools")
            print(f"DEBUG: Returning state with {len(updated_messages)} messages")
            return {
                'messages': updated_messages,
                'stage': FillingStage(stage='processing')
            }
        else:
            print("DEBUG: No tool calls, getting user input")
            user_input = input("\nUser:\n").strip()
            final_messages = updated_messages + [HumanMessage(content=user_input)]
            print(f"DEBUG: Final messages count after user input: {len(final_messages)}")
            return {
                'messages': final_messages,
                'stage': FillingStage(stage='processing')
            }
    
    def _route_after_tools(self, state: FilterAgentState) -> str:
        """Route after tool execution"""
        # Continue with parameter filling after tool use
        last_message = state['messages'][-1]
        print(f"\n the last message from tools calling is:\n {last_message}\n")
        return END
    
    def _condition_parameters_filling(self, state: FilterAgentState) -> str:
        """
        Determine if parameter filling is complete or if tools should be called
        """
        last_message = state['messages'][-1]

        print(f"\n the last message from params_filling is:\n {last_message}\n")
        
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:  #type:ignore
            print('\n we have a tools call.\n')
            return 'tools'
        else:
            return 'params_filling'
    
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
                "user_choice": current_state.values.get("user_choice", "")
            }
        else:
            # Start new conversation
            input_state = {
                "messages": [user_message],
                "stage": FillingStage(stage='processing'),
                "user_choice": ""
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
                "user_choice": current_state.values.get("user_choice", "")
            }
        else:
            input_state = {
                "messages": [user_message],
                "stage": FillingStage(stage='processing'),
                "user_choice": ""
            }
        
        # Stream the execution
        for chunk in self.app.stream(input_state, config):  #type:ignore
            yield chunk
    
    def get_conversation_history(self, thread_id: str = "default") -> List[BaseMessage]:
        """Get the conversation history for a thread"""
        config = {"configurable": {"thread_id": thread_id}}
        state = self.app.get_state(config)  #type:ignore
        return state.values.get("messages", []) if state.values else []
    
    def reset_conversation(self, thread_id: str = "default") -> None:
        """Reset conversation for a thread"""
        config = {"configurable": {"thread_id": thread_id}}
        # Clear the checkpointer state for this thread
        # Note: This depends on your MemorySaver implementation
        pass


async def main(): 
    client =  MultiServerMCPClient({
            "validation": {
                "command": "python",
                "args": ["/Users/az-ihsan/Documents/kerjaan-ihsan/post-doc/JueNA_knowledge_base/vitess-ai-agent/src/vitess_ai/mcp/validation_server.py"],
                "transport": "stdio"
            }
        })  # type: ignore
    tools = await client.get_tools()
    agent = FilterAgent(model_name='alias-large', tools=tools)

   # Example conversation flow with validation
    thread_id = "100"
    print("=== Filter Configuration Chatbot Demo ===\n")

    # Start conversation
    print("🤖 Starting conversation...")
    response1 = await agent.run("", thread_id)

# Example usage
if __name__ == "__main__":
    import asyncio
    
    asyncio.run(main())
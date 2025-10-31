import json
import logging
import warnings
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core._api import LangChainBetaWarning
from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph

from vitess_ai.server_agents.server_supervisor import create_default_server_supervisor
from vitess_ai.schema.server import (
    AgentInfo,
    ChatMessage,
    StreamInput,
    UserInput,
    HealthStatus
)
from vitess_ai.server.utils import langchain_to_chat_message
from vitess_ai.server.errors import (
    AgentNotFoundError,
    StreamingError,
    InterruptError,
    StateError,
    VitessServerError
)
from vitess_ai.server.interrupt_handler import InterruptHandler
from vitess_ai.server.streaming import StreamEventProcessor

warnings.filterwarnings("ignore", category=LangChainBetaWarning)
logger = logging.getLogger(__name__)

def _setup_service_logging():
    """Setup logging for the service"""
    # Only add handler if logger doesn't have one (avoid duplicates)
    if not logger.handlers:
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
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        # Prevent propagation to avoid duplicate logs
        logger.propagate = False

# Setup logging when module is imported
_setup_service_logging()
logger.info("Service logging initialized")

# Simple in-memory agent registry
DEFAULT_AGENT = "supervisor"
_agent_registry: dict[str, CompiledStateGraph] = {}


def get_all_agent_info() -> list[AgentInfo]:
    """Get information about all available agents."""
    return [
        AgentInfo(
            key="supervisor",
            description="Neutron Simulation Supervisor - coordinates all simulation modules",
            capabilities=[
                "module_coordination",
                "interrupt_handling", 
                "cli_generation",
                "simulation_management",
                "user_interaction"
            ]
        )
    ]

async def get_agent(agent_id: str) -> CompiledStateGraph:
    """Get an agent by ID, creating it if it doesn't exist."""
    logger.info(f"Getting agent: {agent_id}")
    if agent_id not in _agent_registry:
        if agent_id == "supervisor":
            try:
                logger.info("Creating new server supervisor agent")
                # Create server supervisor agent asynchronously
                supervisor = await create_default_server_supervisor()
                _agent_registry[agent_id] = supervisor.app
                logger.info("Server supervisor agent created and registered")
            except Exception as e:
                logger.error(f"Failed to create supervisor agent: {e}")
                raise AgentNotFoundError(
                    agent_id,
                    details={"error": str(e), "agent_type": "supervisor"}
                )
        else:
            logger.error(f"Unknown agent requested: {agent_id}")
            raise AgentNotFoundError(
                agent_id,
                details={"available_agents": list(_agent_registry.keys())}
            )
    else:
        logger.info(f"Using existing agent: {agent_id}")
    
    return _agent_registry[agent_id]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Simple lifespan for in-memory only operation.
    """
    # No database/store initialization needed for in-memory operation
    yield


app = FastAPI(lifespan=lifespan)
router = APIRouter()



@router.post("/{agent_id}/invoke")
@router.post("/invoke")
async def invoke(user_input: UserInput, agent_id: str = DEFAULT_AGENT) -> ChatMessage:
    """
    Invoke an agent with user input to retrieve a final response.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to messages for recording feedback.
    Use user_id to persist and continue a conversation across multiple threads.
    """
    # NOTE: Currently this only returns the last message or interrupt.
    # In the case of an agent outputting multiple AIMessages (such as the background step
    # in interrupt-agent, or a tool step in research-assistant), it's omitted. Arguably,
    # you'd want to include it. You could update the API to return a list of ChatMessages
    # in that case.
    try:
        agent: CompiledStateGraph = await get_agent(agent_id)
    except AgentNotFoundError as e:
        logger.error(f"Agent not found: {e}")
        raise HTTPException(status_code=404, detail=e.message)
    
    try:
        kwargs, run_id = await InterruptHandler.prepare_input(
            user_input.message,
            agent,
            thread_id=user_input.thread_id,
            user_id=user_input.user_id
        )
        logger.info(f"Invoke prepared, run_id: {run_id}")
    except (InterruptError, StateError) as e:
        logger.error(f"Failed to prepare input: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to prepare input: {e.message}")
    except Exception as e:
        logger.error(f"Unexpected error preparing input: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error preparing input")

    try:
        response_events: list[tuple[str, Any]] = await agent.ainvoke(**kwargs, stream_mode=["updates", "values"])  # type: ignore # fmt: skip
        response_type, response = response_events[-1]
        
        if response_type == "values":
            # Normal response, the agent completed successfully
            output = langchain_to_chat_message(response["messages"][-1])
        elif response_type == "updates" and "__interrupt__" in response:
            # The last thing to occur was an interrupt
            # Return the value of the first interrupt as an AIMessage
            interrupt_value = response["__interrupt__"][0].value
            output = langchain_to_chat_message(
                AIMessage(content=interrupt_value if isinstance(interrupt_value, str) else str(interrupt_value))
            )
        else:
            logger.error(f"Unexpected response type: {response_type}")
            raise HTTPException(
                status_code=500,
                detail=f"Unexpected response type: {response_type}"
            )

        output.run_id = str(run_id)
        return output
    except HTTPException:
        raise
    except VitessServerError as e:
        logger.error(f"Server error during invocation: {e}")
        raise HTTPException(status_code=500, detail=e.message)
    except Exception as e:
        logger.error(f"Unexpected error during invocation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Unexpected error during agent invocation")

async def message_generator(
    user_input: StreamInput, agent_id: str = DEFAULT_AGENT
) -> AsyncGenerator[str, None]:
    """
    Generate a stream of messages from the agent.

    This is the workhorse method for the /stream endpoint.
    """
    try:
        agent: CompiledStateGraph = await get_agent(agent_id)
    except AgentNotFoundError as e:
        logger.error(f"Agent not found: {e}")
        yield f"data: {json.dumps({'type': 'error', 'content': f'Agent not found: {e.message}'})}\n\n"
        yield "data: [DONE]\n\n"
        return
    
    try:
        kwargs, run_id = await InterruptHandler.prepare_input(
            user_input.message,
            agent,
            thread_id=user_input.thread_id,
            user_id=user_input.user_id
        )
    except (InterruptError, StateError) as e:
        logger.error(f"Failed to prepare input: {e}")
        yield f"data: {json.dumps({'type': 'error', 'content': f'Failed to prepare input: {e.message}'})}\n\n"
        yield "data: [DONE]\n\n"
        return
    except Exception as e:
        logger.error(f"Unexpected error preparing input: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'content': 'Unexpected error preparing input'})}\n\n"
        yield "data: [DONE]\n\n"
        return
    
    try:
        # Create stream event processor
        processor = StreamEventProcessor(
            agent,
            kwargs["config"],
            str(run_id),
            user_input.message
        )
        
        # Process streamed events from the graph and yield messages over the SSE stream
        async for stream_event in agent.astream(
            **kwargs, stream_mode=["updates", "messages", "custom"], subgraphs=True
        ):
            async for sse_string in processor.process_event(stream_event):
                yield sse_string
        
    except StreamingError as e:
        logger.error(f"Streaming error: {e}")
        yield f"data: {json.dumps({'type': 'error', 'content': f'Streaming error: {e.message}'})}\n\n"
    except Exception as e:
        logger.error(f"Unexpected error in message generator: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'content': 'Internal server error'})}\n\n"
    finally:
        yield "data: [DONE]\n\n"


def _sse_response_example() -> dict[int | str, Any]:
    return {
        status.HTTP_200_OK: {
            "description": "Server Sent Event Response",
            "content": {
                "text/event-stream": {
                    "example": "data: {'type': 'token', 'content': 'Hello'}\n\ndata: {'type': 'token', 'content': ' World'}\n\ndata: [DONE]\n\n",
                    "schema": {"type": "string"},
                }
            },
        }
    }


@router.post(
    "/{agent_id}/stream",
    response_class=StreamingResponse,
    responses=_sse_response_example(),
)
@router.post("/stream", response_class=StreamingResponse, responses=_sse_response_example())
async def stream(user_input: StreamInput, agent_id: str = DEFAULT_AGENT) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. 
    run_id kwarg is also attached to all messages for recording feedback.
    Use user_id to persist and continue a conversation across multiple threads.
    """
    return StreamingResponse(
        message_generator(user_input, agent_id),
        media_type="text/event-stream",
    )

@app.get("/health")
async def health_check() -> HealthStatus:
    """Health check endpoint."""
    return HealthStatus(
        status="ok",
        version="0.1.0",
        details={"service": "vitess-ai-agent", "uptime": "running"}
    )

app.include_router(router)

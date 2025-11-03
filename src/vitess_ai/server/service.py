import json
import logging
import warnings
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from langchain_core._api import LangChainBetaWarning
from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph

from vitess_ai.server_agents.supervisor import create_default_supervisor, SupervisorAgent
from vitess_ai.schema.server import (
    AgentInfo,
    ChatMessage,
    StreamInput,
    UserInput,
    HealthStatus
)
from vitess_ai.core.config import global_config
from vitess_ai.schema.llm_models import Provider, get_default_model_for_provider
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
# Key format: (agent_id, provider, model) -> tuple(SupervisorAgent, CompiledStateGraph)
# Storing both supervisor instance and app allows us to restart the graph with new config
DEFAULT_AGENT = "supervisor"
_agent_registry: dict[tuple[str, str, str], tuple[SupervisorAgent, CompiledStateGraph]] = {}


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

async def get_agent(
    agent_id: str, 
    provider: str | None = None, 
    model: str | None = None
) -> CompiledStateGraph:
    """
    Get an agent by ID, creating it if it doesn't exist.
    
    Args:
        agent_id: Agent identifier (e.g., "supervisor")
        provider: LLM provider (openai or blablador). Defaults to global_config.DEFAULT_PROVIDER
        model: LLM model name. Defaults to provider's default model
    
    Returns:
        CompiledStateGraph for the agent
    """
    # Determine provider (default to config default)
    if provider is None:
        provider = global_config.DEFAULT_PROVIDER
    
    # Determine model (default to provider's default)
    if model is None:
        try:
            provider_enum = Provider(provider)
            model = get_default_model_for_provider(provider_enum)
        except ValueError:
            # Invalid provider, fall back to config default
            provider = global_config.DEFAULT_PROVIDER
            model = global_config.DEFAULT_MODEL
    
    # Create composite key for registry
    # Note: Different provider/model combinations create separate agents
    # This allows the graph to regenerate with the new LLM automatically
    registry_key = (agent_id, provider, model)
    
    logger.info(f"Getting agent: {agent_id} with provider={provider}, model={model}")
    
    if registry_key not in _agent_registry:
        if agent_id == "supervisor":
            try:
                logger.info(f"Creating new supervisor agent with provider={provider}, model={model}")
                # Create supervisor agent asynchronously with specified provider/model
                supervisor = await create_default_supervisor(
                    provider=provider,
                    model=model
                )
                _agent_registry[registry_key] = (supervisor, supervisor.app)
                logger.info("Supervisor agent created and registered")
            except Exception as e:
                logger.error(f"Failed to create supervisor agent: {e}")
                raise AgentNotFoundError(
                    agent_id,
                    details={"error": str(e), "agent_type": "supervisor", "provider": provider, "model": model}
                )
        else:
            logger.error(f"Unknown agent requested: {agent_id}")
            raise AgentNotFoundError(
                agent_id,
                details={"available_agents": ["supervisor"]}
            )
    else:
        logger.info(f"Using existing agent: {agent_id} with provider={provider}, model={model}")
    
    # Return the CompiledStateGraph (app) from the registry
    return _agent_registry[registry_key][1]


async def restart_agent(
    agent_id: str,
    provider: str | None = None,
    model: str | None = None
) -> CompiledStateGraph:
    """
    Restart an agent with new provider/model configuration.
    
    This function forces reinitialization of the agent graph with new LLM configuration,
    similar to refreshing the web page but keeping the new provider/model.
    
    Args:
        agent_id: Agent identifier (e.g., "supervisor")
        provider: New LLM provider (optional, uses current if not provided)
        model: New LLM model name (optional, uses current if not provided)
    
    Returns:
        CompiledStateGraph for the restarted agent
    """
    # Determine provider (default to config default)
    if provider is None:
        provider = global_config.DEFAULT_PROVIDER
    
    # Determine model (default to provider's default)
    if model is None:
        try:
            provider_enum = Provider(provider)
            model = get_default_model_for_provider(provider_enum)
        except ValueError:
            # Invalid provider, fall back to config default
            provider = global_config.DEFAULT_PROVIDER
            model = global_config.DEFAULT_MODEL
    
    registry_key = (agent_id, provider, model)
    
    logger.info(f"Restarting agent: {agent_id} with provider={provider}, model={model}")
    
    if agent_id == "supervisor":
        # If agent exists, restart it with new config
        if registry_key in _agent_registry:
            supervisor, _ = _agent_registry[registry_key]
            logger.info(f"Restarting existing supervisor with new config: provider={provider}, model={model}")
            # Clear state to start fresh (clear_state=True by default)
            await supervisor.restart_with_new_config(provider=provider, model=model, clear_state=True)
            # Update the registry with the new app
            _agent_registry[registry_key] = (supervisor, supervisor.app)
            logger.info("Supervisor restarted successfully with cleared state")
        else:
            # Agent doesn't exist, create it
            logger.info(f"Agent not found, creating new supervisor with provider={provider}, model={model}")
            return await get_agent(agent_id, provider=provider, model=model)
        
        return _agent_registry[registry_key][1]
    else:
        logger.error(f"Unknown agent requested: {agent_id}")
        raise AgentNotFoundError(
            agent_id,
            details={"available_agents": ["supervisor"]}
        )


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
    Provider and model can be specified in the request to use different LLMs.
    """
    # NOTE: Currently this only returns the last message or interrupt.
    # In the case of an agent outputting multiple AIMessages (such as the background step
    # in interrupt-agent, or a tool step in research-assistant), it's omitted. Arguably,
    # you'd want to include it. You could update the API to return a list of ChatMessages
    # in that case.
    
    # Extract provider and model from request
    provider = user_input.provider.value if user_input.provider else None
    model = user_input.model
    
    try:
        agent: CompiledStateGraph = await get_agent(agent_id, provider=provider, model=model)
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
    # Extract provider and model from request
    provider = user_input.provider.value if user_input.provider else None
    model = user_input.model
    
    try:
        agent: CompiledStateGraph = await get_agent(agent_id, provider=provider, model=model)
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
        logger.error(f"Unexpected error preparing input: {e}")
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

@router.post("/{agent_id}/restart")
@router.post("/restart")
async def restart(
    agent_id: str = DEFAULT_AGENT,
    provider: str | None = Query(None, description="New LLM provider (openai or blablador)"),
    model: str | None = Query(None, description="New LLM model name"),
) -> dict[str, Any]:
    """
    Restart an agent with new provider/model configuration.
    
    This endpoint forces reinitialization of the agent graph with new LLM configuration,
    similar to refreshing the web page but keeping the new provider/model.
    
    Args:
        agent_id: Agent identifier (e.g., "supervisor")
        provider: New LLM provider (optional, uses current if not provided)
        model: New LLM model name (optional, uses current if not provided)
    
    Returns:
        Dictionary with restart status and agent info
    """
    try:
        agent = await restart_agent(agent_id, provider=provider, model=model)
        
        # Determine the actual provider/model used
        actual_provider = provider or global_config.DEFAULT_PROVIDER
        if model is None:
            try:
                provider_enum = Provider(actual_provider)
                actual_model = get_default_model_for_provider(provider_enum)
            except ValueError:
                actual_model = global_config.DEFAULT_MODEL
        else:
            actual_model = model
        
        return {
            "status": "success",
            "message": f"Agent {agent_id} restarted successfully",
            "provider": actual_provider,
            "model": actual_model,
            "agent_id": agent_id
        }
    except AgentNotFoundError as e:
        logger.error(f"Agent not found for restart: {e}")
        raise HTTPException(status_code=404, detail=e.message)
    except Exception as e:
        logger.error(f"Failed to restart agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to restart agent: {str(e)}")


@app.get("/health")
async def health_check() -> HealthStatus:
    """Health check endpoint."""
    return HealthStatus(
        status="ok",
        version="0.1.0",
        details={"service": "vitess-ai-agent", "uptime": "running"}
    )

app.include_router(router)

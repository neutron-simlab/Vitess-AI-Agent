"""
Agent registry for managing agent instances.

This module provides functions for creating, retrieving, and restarting agents.
"""
import logging
from langgraph.graph.state import CompiledStateGraph

from vitess_ai.server_agents.supervisor import create_default_supervisor, SupervisorAgent
from vitess_ai.core.config import global_config
from vitess_ai.schema.llm_models import Provider, get_default_model_for_provider
from vitess_ai.server.errors import AgentNotFoundError

logger = logging.getLogger(__name__)

# Simple in-memory agent registry
# Key format: (agent_id, provider, model) -> tuple(SupervisorAgent, CompiledStateGraph)
# Storing both supervisor instance and app allows us to restart the graph with new config
DEFAULT_AGENT = "supervisor"
_agent_registry: dict[tuple[str, str, str], tuple[SupervisorAgent, CompiledStateGraph]] = {}


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


import json
import os
from collections.abc import AsyncGenerator, Generator
from typing import Any

import httpx

from vitess_ai.schema.llm_models import Provider
from vitess_ai.schema.server import (
    ChatMessage,
    Feedback,
    ServiceMetadata,
    StreamInput,
    UserInput,
)


class AgentClientError(Exception):
    pass


class AgentClient:
    """Client for interacting with the agent service."""

    def __init__(
        self,
        base_url: str = "http://0.0.0.0",
        agent: str | None = None,
        timeout: float | None = None,
        get_info: bool = True,
    ) -> None:
        """
        Initialize the client.

        Args:
            base_url (str): The base URL of the agent service.
            agent (str): The name of the default agent to use.
            timeout (float, optional): The timeout for requests.
            get_info (bool, optional): Whether to fetch agent information on init.
                Default: True
        """
        self.base_url = base_url
        self.auth_secret = os.getenv("AUTH_SECRET")
        self.timeout = timeout
        self.info: ServiceMetadata | None = None
        self.agent: str | None = None
        if get_info:
            self.retrieve_info()
        if agent:
            self.update_agent(agent)

    @property
    def _headers(self) -> dict[str, str]:
        headers = {}
        if self.auth_secret:
            headers["Authorization"] = f"Bearer {self.auth_secret}"
        return headers

    def retrieve_info(self) -> None:
        try:
            response = httpx.get(
                f"{self.base_url}/info",
                headers=self._headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error getting service info: {e}")

        self.info = ServiceMetadata.model_validate(response.json())
        if not self.agent or self.agent not in [a.key for a in self.info.agents]:
            self.agent = self.info.default_agent

    def update_agent(self, agent: str, verify: bool = True) -> None:
        if verify:
            if not self.info:
                self.retrieve_info()
            agent_keys = [a.key for a in self.info.agents]  # type: ignore[union-attr]
            if agent not in agent_keys:
                raise AgentClientError(
                    f"Agent {agent} not found in available agents: {', '.join(agent_keys)}"
                )
        self.agent = agent

    async def ainvoke(
        self,
        message: str,
        model: str | None = None,
        provider: str | None = None,
        thread_id: str | None = None,
        user_id: str | None = None,
        agent_config: dict[str, Any] | None = None,
    ) -> ChatMessage:
        """
        Invoke the agent asynchronously. Only the final message is returned.

        Args:
            message (str): The message to send to the agent
            model (str, optional): LLM model to use for the agent
            provider (str, optional): LLM provider to use (openai or blablador)
            thread_id (str, optional): Thread ID for continuing a conversation
            user_id (str, optional): User ID for continuing a conversation across multiple threads
            agent_config (dict[str, Any], optional): Additional configuration to pass through to the agent

        Returns:
            AnyMessage: The response from the agent
        """
        if not self.agent:
            raise AgentClientError("No agent selected. Use update_agent() to select an agent.")
        request = UserInput(message=message)
        if thread_id:
            request.thread_id = thread_id
        if model:
            request.model = model  # type: ignore[assignment]
        if provider:
            # Convert string to Provider enum if needed
            if isinstance(provider, str):
                request.provider = Provider(provider)
            else:
                request.provider = provider
        if agent_config:
            request.agent_config = agent_config
        if user_id:
            request.user_id = user_id
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/{self.agent}/invoke",
                    json=request.model_dump(),
                    headers=self._headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise AgentClientError(f"Error: {e}")

        return ChatMessage.model_validate(response.json())

    def invoke(
        self,
        message: str,
        model: str | None = None,
        provider: str | None = None,
        thread_id: str | None = None,
        user_id: str | None = None,
        agent_config: dict[str, Any] | None = None,
    ) -> ChatMessage:
        """
        Invoke the agent synchronously. Only the final message is returned.

        Args:
            message (str): The message to send to the agent
            model (str, optional): LLM model to use for the agent
            provider (str, optional): LLM provider to use (openai or blablador)
            thread_id (str, optional): Thread ID for continuing a conversation
            user_id (str, optional): User ID for continuing a conversation across multiple threads
            agent_config (dict[str, Any], optional): Additional configuration to pass through to the agent

        Returns:
            ChatMessage: The response from the agent
        """
        if not self.agent:
            raise AgentClientError("No agent selected. Use update_agent() to select an agent.")
        request = UserInput(message=message)
        if thread_id:
            request.thread_id = thread_id
        if model:
            request.model = model  # type: ignore[assignment]
        if provider:
            # Convert string to Provider enum if needed
            if isinstance(provider, str):
                request.provider = Provider(provider)
            else:
                request.provider = provider
        if agent_config:
            request.agent_config = agent_config
        if user_id:
            request.user_id = user_id
        try:
            response = httpx.post(
                f"{self.base_url}/{self.agent}/invoke",
                json=request.model_dump(),
                headers=self._headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error: {e}")

        return ChatMessage.model_validate(response.json())

    def _extract_module_from_token_type(self, token_type: str) -> str:
        """
        Extract module name from token type string.
        
        Args:
            token_type: Token type string (e.g., "token_module_readin", "token_readin")
            
        Returns:
            Module name (e.g., "readin", "supervisor", "default")
        """
        if token_type == "token_stream":
            return "default"
        elif token_type == "token_supervisor":
            return "supervisor"
        elif token_type == "token_generic":
            return "default"
        elif token_type.startswith("token_module_"):
            # Extract module name: "token_module_readin" -> "readin"
            module_name = token_type.replace("token_module_", "", 1)
            return module_name
        elif token_type.startswith("token_"):
            # Support server tokens like "token_readin"
            module_name = token_type.replace("token_", "", 1)
            return module_name or "default"
        return "default"
    
    def _normalize_token(self, token_type: str, content: str) -> dict:
        """
        Normalize token into unified format.
        
        Args:
            token_type: Original token type string
            content: Token content string
            
        Returns:
            Normalized token dict with 'type' and 'content' keys
        """
        module_name = self._extract_module_from_token_type(token_type)
        return {
            "type": "token",
            "module": module_name,
            "content": content
        }
    
    def _parse_stream_line(self, line: str) -> ChatMessage | str | dict | None:
        """
        Parse a single SSE line into a normalized message or token.
        
        Returns:
            ChatMessage, normalized token dict, or None
        """
        line = line.strip()
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                return None
            try:
                parsed = json.loads(data)
            except Exception as e:
                raise Exception(f"Error JSON parsing message from server: {e}")
            
            parsed_type = parsed.get("type", "")
            
            # Handle complete messages
            if parsed_type == "message":
                try:
                    return ChatMessage.model_validate(parsed["content"])
                except Exception as e:
                    raise Exception(f"Server returned invalid message: {e}")
            
            # Handle errors
            elif parsed_type == "error":
                error_msg = "Error: " + parsed.get("content", "Unknown error")
                return ChatMessage(type="ai", content=error_msg)
            
            # Normalize all token types into unified format
            elif parsed_type.startswith("token"):
                content = parsed.get("content", "")
                return self._normalize_token(parsed_type, content)
            
            # Fallback for unknown types
            else:
                return {"type": "unknown", "content": parsed.get("content", str(parsed))}
        
        return None

    def stream(
        self,
        message: str,
        model: str | None = None,
        provider: str | None = None,
        thread_id: str | None = None,
        user_id: str | None = None,
        agent_config: dict[str, Any] | None = None,
        stream_tokens: bool = True,
    ) -> Generator[ChatMessage | str | dict, None, None]:
        """
        Stream the agent's response synchronously.

        Each intermediate message of the agent process is yielded as a ChatMessage.
        If stream_tokens is True (the default value), the response will also yield
        content tokens from streaming models as they are generated.

        Args:
            message (str): The message to send to the agent
            model (str, optional): LLM model to use for the agent
            provider (str, optional): LLM provider to use (openai or blablador)
            thread_id (str, optional): Thread ID for continuing a conversation
            user_id (str, optional): User ID for continuing a conversation across multiple threads
            agent_config (dict[str, Any], optional): Additional configuration to pass through to the agent
            stream_tokens (bool, optional): Stream tokens as they are generated
                Default: True

        Returns:
            Generator[ChatMessage | str | dict, None, None]: The response from the agent
        """
        if not self.agent:
            raise AgentClientError("No agent selected. Use update_agent() to select an agent.")
        request = StreamInput(message=message, stream_tokens=stream_tokens)
        if thread_id:
            request.thread_id = thread_id
        if user_id:
            request.user_id = user_id
        if model:
            request.model = model  # type: ignore[assignment]
        if provider:
            # Convert string to Provider enum if needed
            if isinstance(provider, str):
                request.provider = Provider(provider)
            else:
                request.provider = provider
        if agent_config:
            request.agent_config = agent_config
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/{self.agent}/stream",
                json=request.model_dump(),
                headers=self._headers,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.strip():
                        parsed = self._parse_stream_line(line)
                        if parsed is None:
                            break
                        yield parsed
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error: {e}")

    async def astream(
        self,
        message: str,
        model: str | None = None,
        provider: str | None = None,
        thread_id: str | None = None,
        user_id: str | None = None,
        agent_config: dict[str, Any] | None = None,
        stream_tokens: bool = True,
    ) -> AsyncGenerator[ChatMessage | str | dict, None]:
        """
        Stream the agent's response asynchronously.

        Each intermediate message of the agent process is yielded as an AnyMessage.
        If stream_tokens is True (the default value), the response will also yield
        content tokens from streaming models as they are generated.

        Args:
            message (str): The message to send to the agent
            model (str, optional): LLM model to use for the agent
            provider (str, optional): LLM provider to use (openai or blablador)
            thread_id (str, optional): Thread ID for continuing a conversation
            user_id (str, optional): User ID for continuing a conversation across multiple threads
            agent_config (dict[str, Any], optional): Additional configuration to pass through to the agent
            stream_tokens (bool, optional): Stream tokens as they are generated
                Default: True

        Returns:
            AsyncGenerator[ChatMessage | str, None]: The response from the agent
        """
        if not self.agent:
            raise AgentClientError("No agent selected. Use update_agent() to select an agent.")
        request = StreamInput(message=message, stream_tokens=stream_tokens)
        if thread_id:
            request.thread_id = thread_id
        if model:
            request.model = model  # type: ignore[assignment]
        if provider:
            # Convert string to Provider enum if needed
            if isinstance(provider, str):
                request.provider = Provider(provider)
            else:
                request.provider = provider
        if agent_config:
            request.agent_config = agent_config
        if user_id:
            request.user_id = user_id
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/{self.agent}/stream",
                    json=request.model_dump(),
                    headers=self._headers,
                    timeout=self.timeout,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.strip():
                            parsed = self._parse_stream_line(line)
                            if parsed is None:
                                break
                            yield parsed
            except httpx.HTTPError as e:
                raise AgentClientError(f"Error: {e}")

    async def acreate_feedback(
        self, run_id: str, key: str, score: float, kwargs: dict[str, Any] = {}
    ) -> None:
        """
        Create a feedback record for a run.

        This is a simple wrapper for the LangSmith create_feedback API, so the
        credentials can be stored and managed in the service rather than the client.
        See: https://api.smith.langchain.com/redoc#tag/feedback/operation/create_feedback_api_v1_feedback_post
        """
        request = Feedback(run_id=run_id, key=key, score=score, kwargs=kwargs)
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/feedback",
                    json=request.model_dump(),
                    headers=self._headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                response.json()
            except httpx.HTTPError as e:
                raise AgentClientError(f"Error: {e}")


    def is_token_message(self, message: ChatMessage | str | dict) -> bool:
        """
        Check if a message is a token message (normalized or legacy format).
        
        Args:
            message: Message to check
            
        Returns:
            True if message is a token, False otherwise
        """
        if isinstance(message, str):
            return True  # Legacy string token
        if isinstance(message, dict):
            msg_type = message.get("type", "")
            # Normalized format: {"type": "token", ...}
            # Legacy format: {"type": "token_*", ...}
            return msg_type == "token" or msg_type.startswith("token_")
        return False

    def get_token_module(self, message: ChatMessage | str | dict) -> str | None:
        """
        Get the module name from a normalized token message.
        
        Args:
            message: Token message (normalized or legacy format)
            
        Returns:
            Module name or None if not a token
        """
        if not self.is_token_message(message):
            return None
        
        if isinstance(message, dict):
            # Normalized format has "module" key
            if message.get("type") == "token":
                return message.get("module", "default")
            # Legacy format: extract from type
            legacy_type = message.get("type", "")
            if legacy_type.startswith("token_"):
                return self._extract_module_from_token_type(legacy_type)
        # Legacy string token
        return "default"

    def get_token_content(self, message: ChatMessage | str | dict) -> str | None:
        """
        Get the content from a token message (normalized or legacy format).
        
        Args:
            message: Token message
            
        Returns:
            Token content string or None
        """
        if isinstance(message, str):
            return message  # Legacy string token
        if isinstance(message, dict) and self.is_token_message(message):
            return message.get("content")
        return None

    def restart(
        self,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        """
        Restart the agent with new provider/model configuration.
        
        This method forces reinitialization of the agent graph with new LLM configuration,
        similar to refreshing the web page but keeping the new provider/model.
        
        Args:
            model (str, optional): New LLM model name to use
            provider (str, optional): New LLM provider to use (openai or blablador)
        
        Returns:
            dict: Dictionary with restart status and agent info
        """
        if not self.agent:
            raise AgentClientError("No agent selected. Use update_agent() to select an agent.")
        
        # Build query parameters
        params: dict[str, str] = {}
        if model:
            params["model"] = model
        if provider:
            params["provider"] = provider
        
        try:
            response = httpx.post(
                f"{self.base_url}/{self.agent}/restart",
                params=params,
                headers=self._headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error restarting agent: {e}")
        
        return response.json()
    
    def get_modules_info(self) -> dict[str, Any]:
        """
        Get module information from the server.
        
        This fetches the list of registered modules from the supervisor,
        including their names, display names, descriptions, and order.
        
        Returns:
            dict: Dictionary with status and modules list
        """
        try:
            response = httpx.get(
                f"{self.base_url}/config/modules",
                headers=self._headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error getting modules info: {e}")
        
        return response.json()
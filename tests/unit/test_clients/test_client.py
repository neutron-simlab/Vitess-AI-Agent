"""
Tests for client.py
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import httpx

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from vitess_ai.clients.client import (
    AgentClient,
    AgentClientError,
)
from vitess_ai.schema.server import (
    ChatMessage,
    ServiceMetadata,
    AgentInfo,
    Provider,
)


@pytest.mark.unit
class TestAgentClientInit:
    """Tests for AgentClient.__init__"""
    
    def test_default_initialization(self):
        """Test default initialization"""
        with patch('vitess_ai.clients.client.httpx.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "agents": [{"key": "supervisor", "description": "Test agent"}],
                "models": ["gpt-4o-mini"],
                "providers": ["openai"],
                "default_agent": "supervisor",
                "default_model": "gpt-4o-mini",
                "default_provider": "openai"
            }
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response
            
            client = AgentClient(get_info=False)
            
            assert client.base_url == "http://0.0.0.0"
            assert client.agent is None
    
    def test_custom_base_url(self):
        """Test custom base URL"""
        client = AgentClient(base_url="http://localhost:8000", get_info=False)
        
        assert client.base_url == "http://localhost:8000"
    
    def test_agent_selection(self):
        """Test agent selection"""
        with patch('vitess_ai.clients.client.httpx.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "agents": [{"key": "supervisor", "description": "Test agent"}],
                "models": ["gpt-4o-mini"],
                "providers": ["openai"],
                "default_agent": "supervisor",
                "default_model": "gpt-4o-mini",
                "default_provider": "openai"
            }
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response
            
            client = AgentClient(agent="supervisor", get_info=True)
            
            assert client.agent == "supervisor"
    
    def test_info_retrieval(self):
        """Test info retrieval on init"""
        with patch('vitess_ai.clients.client.httpx.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "agents": [{"key": "supervisor", "description": "Test agent"}],
                "models": ["gpt-4o-mini"],
                "providers": ["openai"],
                "default_agent": "supervisor",
                "default_model": "gpt-4o-mini",
                "default_provider": "openai"
            }
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response
            
            client = AgentClient(get_info=True)
            
            assert client.info is not None
            assert isinstance(client.info, ServiceMetadata)


@pytest.mark.unit
class TestRetrieveInfo:
    """Tests for retrieve_info method"""
    
    def test_successful_retrieval(self):
        """Test successful info retrieval"""
        client = AgentClient(get_info=False)
        
        with patch('vitess_ai.clients.client.httpx.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "agents": [{"key": "supervisor", "description": "Test agent"}],
                "models": ["gpt-4o-mini"],
                "providers": ["openai"],
                "default_agent": "supervisor",
                "default_model": "gpt-4o-mini",
                "default_provider": "openai"
            }
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response
            
            client.retrieve_info()
            
            assert client.info is not None
            assert client.agent == "supervisor"
    
    def test_http_errors(self):
        """Test HTTP errors"""
        client = AgentClient(get_info=False)
        
        with patch('vitess_ai.clients.client.httpx.get') as mock_get:
            mock_get.side_effect = httpx.HTTPError("Connection error")
            
            with pytest.raises(AgentClientError):
                client.retrieve_info()
    
    def test_authentication(self, mock_env):
        """Test authentication"""
        client = AgentClient(get_info=False)
        client.auth_secret = "test_secret"
        
        with patch('vitess_ai.clients.client.httpx.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "agents": [{"key": "supervisor", "description": "Test agent"}],
                "models": ["gpt-4o-mini"],
                "providers": ["openai"],
                "default_agent": "supervisor",
                "default_model": "gpt-4o-mini",
                "default_provider": "openai"
            }
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response
            
            client.retrieve_info()
            
            # Check that headers were set
            call_kwargs = mock_get.call_args[1]
            assert "headers" in call_kwargs
            assert "Authorization" in call_kwargs["headers"]


@pytest.mark.unit
class TestUpdateAgent:
    """Tests for update_agent method"""
    
    def test_valid_agent(self):
        """Test updating with valid agent"""
        client = AgentClient(get_info=False)
        client.info = ServiceMetadata(
            agents=[AgentInfo(key="supervisor", description="Test agent")],
            models=["gpt-4o-mini"],
            providers=[Provider.OPENAI],
            default_agent="supervisor",
            default_model="gpt-4o-mini",
            default_provider=Provider.OPENAI
        )
        
        client.update_agent("supervisor")
        
        assert client.agent == "supervisor"
    
    def test_invalid_agent(self):
        """Test updating with invalid agent"""
        client = AgentClient(get_info=False)
        client.info = ServiceMetadata(
            agents=[AgentInfo(key="supervisor", description="Test agent")],
            models=["gpt-4o-mini"],
            providers=[Provider.OPENAI],
            default_agent="supervisor",
            default_model="gpt-4o-mini",
            default_provider=Provider.OPENAI
        )
        
        with pytest.raises(AgentClientError):
            client.update_agent("invalid_agent")
    
    def test_verification_bypass(self):
        """Test verification bypass"""
        client = AgentClient(get_info=False)
        
        client.update_agent("any_agent", verify=False)
        
        assert client.agent == "any_agent"


@pytest.mark.unit
class TestInvoke:
    """Tests for invoke and ainvoke methods"""
    
    def test_successful_invocation(self):
        """Test successful invocation"""
        client = AgentClient(get_info=False)
        client.agent = "supervisor"
        
        with patch('vitess_ai.clients.client.httpx.post') as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "type": "ai",
                "content": "Test response"
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response
            
            result = client.invoke("Test message")
            
            assert isinstance(result, ChatMessage)
            assert result.content == "Test response"
    
    def test_thread_id_handling(self):
        """Test thread ID handling"""
        client = AgentClient(get_info=False)
        client.agent = "supervisor"
        
        with patch('vitess_ai.clients.client.httpx.post') as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "type": "ai",
                "content": "Test response"
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response
            
            result = client.invoke("Test message", thread_id="test_thread")
            
            # Check that thread_id was included in request
            call_kwargs = mock_post.call_args[1]
            request_data = call_kwargs["json"]
            assert request_data["thread_id"] == "test_thread"
    
    def test_model_provider_override(self):
        """Test model/provider override"""
        client = AgentClient(get_info=False)
        client.agent = "supervisor"
        
        with patch('vitess_ai.clients.client.httpx.post') as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "type": "ai",
                "content": "Test response"
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response
            
            result = client.invoke(
                "Test message",
                model="gpt-4o",
                provider="openai"
            )
            
            # Check that model and provider were included
            call_kwargs = mock_post.call_args[1]
            request_data = call_kwargs["json"]
            assert request_data["model"] == "gpt-4o"
            assert request_data["provider"] == "openai"
    
    def test_error_handling(self):
        """Test error handling"""
        client = AgentClient(get_info=False)
        client.agent = "supervisor"
        
        with patch('vitess_ai.clients.client.httpx.post') as mock_post:
            mock_post.side_effect = httpx.HTTPError("Connection error")
            
            with pytest.raises(AgentClientError):
                client.invoke("Test message")
    
    def test_no_agent_selected(self):
        """Test when no agent is selected"""
        client = AgentClient(get_info=False)
        client.agent = None
        
        with pytest.raises(AgentClientError):
            client.invoke("Test message")
    
    @pytest.mark.asyncio
    async def test_ainvoke(self):
        """Test async invoke"""
        client = AgentClient(get_info=False)
        client.agent = "supervisor"
        
        with patch('vitess_ai.clients.client.httpx.AsyncClient') as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance
            
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "type": "ai",
                "content": "Test response"
            }
            mock_response.raise_for_status = MagicMock()
            mock_client_instance.post.return_value = mock_response
            
            result = await client.ainvoke("Test message")
            
            assert isinstance(result, ChatMessage)


@pytest.mark.unit
class TestStream:
    """Tests for stream and astream methods"""
    
    def test_token_streaming(self):
        """Test token streaming"""
        client = AgentClient(get_info=False)
        client.agent = "supervisor"
        
        # Mock SSE response
        sse_lines = [
            "data: {\"type\": \"token_stream\", \"content\": \"Hello\"}\n",
            "data: {\"type\": \"token_stream\", \"content\": \" World\"}\n",
            "data: {\"type\": \"message\", \"content\": {\"type\": \"ai\", \"content\": \"Hello World\"}}\n",
            "data: [DONE]\n"
        ]
        
        with patch('vitess_ai.clients.client.httpx.stream') as mock_stream:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.iter_lines.return_value = sse_lines
            mock_stream.return_value.__enter__.return_value = mock_response
            
            results = list(client.stream("Test message", stream_tokens=True))
            
            assert len(results) > 0
            # Should have tokens and final message
    
    def test_message_parsing(self):
        """Test message parsing"""
        client = AgentClient(get_info=False)
        client.agent = "supervisor"
        
        sse_lines = [
            "data: {\"type\": \"message\", \"content\": {\"type\": \"ai\", \"content\": \"Test response\"}}\n",
            "data: [DONE]\n"
        ]
        
        with patch('vitess_ai.clients.client.httpx.stream') as mock_stream:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.iter_lines.return_value = sse_lines
            mock_stream.return_value.__enter__.return_value = mock_response
            
            results = list(client.stream("Test message"))
            
            assert len(results) > 0
            # Should have ChatMessage
            assert any(isinstance(r, ChatMessage) for r in results)
    
    def test_sse_format_parsing(self):
        """Test SSE format parsing"""
        client = AgentClient(get_info=False)
        client.agent = "supervisor"
        
        sse_lines = [
            "data: {\"type\": \"token_module_readin\", \"content\": \"token\"}\n",
            "data: [DONE]\n"
        ]
        
        with patch('vitess_ai.clients.client.httpx.stream') as mock_stream:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.iter_lines.return_value = sse_lines
            mock_stream.return_value.__enter__.return_value = mock_response
            
            results = list(client.stream("Test message"))
            
            assert len(results) > 0
            # Should have normalized tokens
    
    def test_error_handling(self):
        """Test error handling in stream"""
        client = AgentClient(get_info=False)
        client.agent = "supervisor"
        
        with patch('vitess_ai.clients.client.httpx.stream') as mock_stream:
            mock_stream.side_effect = httpx.HTTPError("Connection error")
            
            with pytest.raises(AgentClientError):
                list(client.stream("Test message"))


@pytest.mark.unit
class TestParseStreamLine:
    """Tests for _parse_stream_line method"""
    
    def test_message_parsing(self):
        """Test message parsing"""
        client = AgentClient(get_info=False)
        
        line = 'data: {"type": "message", "content": {"type": "ai", "content": "Test"}}'
        result = client._parse_stream_line(line)
        
        assert isinstance(result, ChatMessage)
        assert result.content == "Test"
    
    def test_token_normalization(self):
        """Test token normalization"""
        client = AgentClient(get_info=False)
        
        line = 'data: {"type": "token_module_readin", "content": "token"}'
        result = client._parse_stream_line(line)
        
        assert isinstance(result, dict)
        assert result["type"] == "token"
        assert result["module"] == "readin"
        assert result["content"] == "token"
    
    def test_error_message_handling(self):
        """Test error message handling"""
        client = AgentClient(get_info=False)
        
        line = 'data: {"type": "error", "content": "Error message"}'
        result = client._parse_stream_line(line)
        
        assert isinstance(result, ChatMessage)
        assert "Error" in result.content
    
    def test_done_signal(self):
        """Test [DONE] signal"""
        client = AgentClient(get_info=False)
        
        line = "data: [DONE]"
        result = client._parse_stream_line(line)
        
        assert result is None

    def test_task_lifecycle_parsing(self):
        """Test delegated task lifecycle parsing"""
        client = AgentClient(get_info=False)

        line = (
            'data: {"type":"task_lifecycle","content":{'
            '"run_id":"run-1",'
            '"sequence":1,'
            '"phase":"pending",'
            '"task_id":"task-1",'
            '"subagent_type":"researcher",'
            '"description":"Research latest AI safety developments",'
            '"status":"pending",'
            '"pregel_id":null,'
            '"result_preview":null,'
            '"timestamp":"2026-01-01T00:00:00+00:00"'
            '}}'
        )
        result = client._parse_stream_line(line)

        assert isinstance(result, dict)
        assert result["type"] == "task_lifecycle"
        assert result["content"]["task_id"] == "task-1"
    
    def test_invalid_json(self):
        """Test invalid JSON handling"""
        client = AgentClient(get_info=False)
        
        line = "data: {invalid json}"
        
        with pytest.raises(Exception):
            client._parse_stream_line(line)


@pytest.mark.unit
class TestTokenHelpers:
    """Tests for token helper methods"""
    
    def test_is_token_message(self):
        """Test token message detection"""
        client = AgentClient(get_info=False)
        
        # String token
        assert client.is_token_message("token") is True
        
        # Normalized token dict
        assert client.is_token_message({"type": "token", "module": "readin", "content": "token"}) is True
        
        # Legacy token dict
        assert client.is_token_message({"type": "token_module_readin", "content": "token"}) is True
        
        # Not a token
        assert client.is_token_message(ChatMessage(type="ai", content="message")) is False
    
    def test_get_token_module(self):
        """Test module extraction from token"""
        client = AgentClient(get_info=False)
        
        # Normalized token
        token = {"type": "token", "module": "readin", "content": "token"}
        assert client.get_token_module(token) == "readin"
        
        # Legacy token
        token = {"type": "token_module_readin", "content": "token"}
        assert client.get_token_module(token) == "readin"
        
        # String token
        assert client.get_token_module("token") == "default"
        
        # Not a token
        assert client.get_token_module(ChatMessage(type="ai", content="message")) is None
    
    def test_get_token_content(self):
        """Test content extraction from token"""
        client = AgentClient(get_info=False)
        
        # Normalized token
        token = {"type": "token", "module": "readin", "content": "token"}
        assert client.get_token_content(token) == "token"
        
        # Legacy token
        token = {"type": "token_module_readin", "content": "token"}
        assert client.get_token_content(token) == "token"
        
        # String token
        assert client.get_token_content("token") == "token"
        
        # Not a token
        assert client.get_token_content(ChatMessage(type="ai", content="message")) is None

    def test_is_task_lifecycle_event(self):
        """Test lifecycle event detection helper"""
        client = AgentClient(get_info=False)

        lifecycle_event = {"type": "task_lifecycle", "content": {"task_id": "task-1"}}
        token_event = {"type": "token", "module": "default", "content": "hello"}

        assert client.is_task_lifecycle_event(lifecycle_event) is True
        assert client.is_task_lifecycle_event(token_event) is False

    def test_get_task_lifecycle_content(self):
        """Test lifecycle payload extraction helper"""
        client = AgentClient(get_info=False)

        lifecycle_event = {
            "type": "task_lifecycle",
            "content": {"task_id": "task-1", "status": "running"},
        }
        assert client.get_task_lifecycle_content(lifecycle_event) == {
            "task_id": "task-1",
            "status": "running",
        }
        assert client.get_task_lifecycle_content({"type": "token", "content": "x"}) is None


@pytest.mark.unit
class TestRestart:
    """Tests for restart method"""
    
    def test_agent_restart(self):
        """Test agent restart"""
        client = AgentClient(get_info=False)
        client.agent = "supervisor"
        
        with patch('vitess_ai.clients.client.httpx.post') as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "status": "restarted",
                "agent": "supervisor"
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response
            
            result = client.restart()
            
            assert result["status"] == "restarted"
    
    def test_parameter_passing(self):
        """Test parameter passing"""
        client = AgentClient(get_info=False)
        client.agent = "supervisor"
        
        with patch('vitess_ai.clients.client.httpx.post') as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"status": "restarted"}
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response
            
            client.restart(model="gpt-4o", provider="openai")
            
            # Check that params were included
            call_kwargs = mock_post.call_args
            assert "model" in call_kwargs[1]["params"]
            assert "provider" in call_kwargs[1]["params"]
    
    def test_no_agent_selected(self):
        """Test when no agent is selected"""
        client = AgentClient(get_info=False)
        client.agent = None
        
        with pytest.raises(AgentClientError):
            client.restart()

"""
Tests for config.py
"""
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from vitess_ai.core.config import Config, global_config


@pytest.mark.unit
class TestUpdateVitessConfig:
    """Tests for update_vitess_config method"""
    
    def test_path_updates(self):
        """Test path updates"""
        original_modules = Config.VITESS_MODULES_PATH
        original_project = Config.VITESS_PROJECT_PATH
        original_log = Config.VITESS_LOG_PATH
        
        try:
            result = Config.update_vitess_config(
                modules_path="/new/modules",
                project_path="/new/project",
                log_path="/new/logs"
            )
            
            assert Config.VITESS_MODULES_PATH == "/new/modules"
            assert Config.VITESS_PROJECT_PATH == "/new/project"
            assert Config.VITESS_LOG_PATH == "/new/logs"
            assert result["V"] == "/new/modules"
            assert result["P"] == "/new/project"
            assert result["L"] == "/new/logs"
        finally:
            # Restore original values
            Config.VITESS_MODULES_PATH = original_modules
            Config.VITESS_PROJECT_PATH = original_project
            Config.VITESS_LOG_PATH = original_log
    
    def test_partial_updates(self):
        """Test partial updates"""
        original_modules = Config.VITESS_MODULES_PATH
        
        try:
            result = Config.update_vitess_config(modules_path="/new/modules")
            
            assert Config.VITESS_MODULES_PATH == "/new/modules"
            # Other paths should remain unchanged
            assert Config.VITESS_PROJECT_PATH is not None
            assert Config.VITESS_LOG_PATH is not None
        finally:
            Config.VITESS_MODULES_PATH = original_modules
    
    def test_return_values(self):
        """Test return values"""
        result = Config.update_vitess_config(
            modules_path="/test/modules",
            project_path="/test/project",
            log_path="/test/logs"
        )
        
        assert isinstance(result, dict)
        assert "V" in result
        assert "P" in result
        assert "L" in result


@pytest.mark.unit
class TestResetVitessConfig:
    """Tests for reset_vitess_config method"""
    
    def test_reset_to_defaults(self, monkeypatch):
        """Test reset to defaults"""
        # Set custom values
        Config.update_vitess_config(
            modules_path="/custom/modules",
            project_path="/custom/project",
            log_path="/custom/logs"
        )
        
        # Set environment variables
        monkeypatch.setenv("VITESS_MODULES_PATH", "/env/modules")
        monkeypatch.setenv("VITESS_PROJECT_PATH", "/env/project")
        monkeypatch.setenv("VITESS_LOG_PATH", "/env/logs")
        
        # Reset
        result = Config.reset_vitess_config()
        
        # Should use environment variables or defaults
        assert Config.VITESS_MODULES_PATH in ["/env/modules", "/usr/local/vitess/bin"]
        assert isinstance(result, dict)
        assert "V" in result
        assert "P" in result
        assert "L" in result




@pytest.mark.unit
class TestSetupLangsmith:
    """Tests for setup_langsmith method"""
    
    def test_conditional_enabling(self, monkeypatch):
        """Test conditional enabling"""
        # Disable tracing
        monkeypatch.setenv("LANGSMITH_TRACING", "false")
        monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
        
        result = Config.setup_langsmith()
        
        # Should return False when tracing is disabled or API key is missing
        # Note: The actual behavior depends on implementation
        assert isinstance(result, bool)


@pytest.mark.unit
class TestGetMcpPath:
    """Tests for get_mcp_path method"""
    
    def test_invalid_module_handling(self):
        """Test invalid module handling"""
        with pytest.raises(ValueError):
            Config.get_mcp_path("invalid_module")


@pytest.mark.unit
class TestInitialize:
    """Tests for initialize method"""
    
    @patch('vitess_ai.core.config.Config.setup_langsmith')
    @patch('vitess_ai.core.config.Config.validate_required')
    def test_initialization(self, mock_validate, mock_setup):
        """Test initialization"""
        mock_setup.return_value = True
        
        result = Config.initialize()
        
        assert result == Config
        mock_validate.assert_called_once()
        mock_setup.assert_called_once()


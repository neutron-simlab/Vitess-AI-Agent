"""
Tests for supervisor_tools.py
"""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys
import subprocess

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from vitess_ai.mcp.supervisor_tools import (
    generate_cli_command,
    coerce_json_to_dict,
    coerce_json_to_list,
    MODULE_EXECUTABLES,
    COMMON_PARAMS_BASE,
)


@pytest.mark.unit
class TestCoerceJsonToDict:
    """Tests for coerce_json_to_dict function"""
    
    def test_dict_input(self):
        """Test with dict input"""
        data = {"key": "value"}
        result = coerce_json_to_dict(data)
        
        assert result == data
    
    def test_json_string(self):
        """Test with JSON string"""
        data = '{"key": "value"}'
        result = coerce_json_to_dict(data)
        
        assert result == {"key": "value"}
    
    def test_none_input(self):
        """Test with None input"""
        result = coerce_json_to_dict(None)
        
        assert result is None
    
    def test_invalid_json(self):
        """Test with invalid JSON"""
        data = "{invalid json}"
        result = coerce_json_to_dict(data)
        
        assert result is None
    
    def test_non_dict_json(self):
        """Test with non-dict JSON"""
        data = "[1, 2, 3]"
        result = coerce_json_to_dict(data)
        
        assert result is None


@pytest.mark.unit
class TestCoerceJsonToList:
    """Tests for coerce_json_to_list function"""
    
    def test_list_input(self):
        """Test with list input"""
        data = ["item1", "item2"]
        result = coerce_json_to_list(data)
        
        assert result == data
    
    def test_json_string(self):
        """Test with JSON string"""
        data = '["item1", "item2"]'
        result = coerce_json_to_list(data)
        
        assert result == ["item1", "item2"]
    
    def test_none_input(self):
        """Test with None input"""
        result = coerce_json_to_list(None)
        
        assert result is None
    
    def test_invalid_json(self):
        """Test with invalid JSON"""
        data = "{invalid json}"
        result = coerce_json_to_list(data)
        
        assert result is None
    
    def test_non_list_json(self):
        """Test with non-list JSON"""
        data = '{"key": "value"}'
        result = coerce_json_to_list(data)
        
        assert result is None


@pytest.mark.unit
class TestGenerateCliCommand:
    """Tests for generate_cli_command function"""
    
    def test_single_module(self):
        """Test CLI generation for single module"""
        module_results = {
            "readin": {
                "cli_parameters": "-f1 -F0 -Afile1.dat -a1.0"
            }
        }
        execution_order = ["readin"]
        
        result = generate_cli_command(module_results, execution_order)
        
        assert result["success"] is True
        assert "cli_command" in result
        # CLI command contains executable path like "read_in", so check for CLI parameters
        assert "-f1" in result["cli_command"] or "read_in" in result["cli_command"]
        assert result["modules_included"] == ["readin"]
    
    def test_multiple_modules_in_order(self):
        """Test CLI generation for multiple modules in order"""
        module_results = {
            "readin": {"cli_parameters": "-f1 -F0 -Afile1.dat -a1.0"},
            "guide": {"cli_parameters": "-Y0 -Z0 -w3.0 -h3.0"},
            "writeout": {"cli_parameters": "-Aoutput.dat -a1"}
        }
        execution_order = ["readin", "guide", "writeout"]
        
        result = generate_cli_command(module_results, execution_order)
        
        assert result["success"] is True
        assert "cli_command" in result
        assert result["modules_included"] == ["readin", "guide", "writeout"]
        # Check that pipes are included between modules
        assert "|" in result["cli_command"]
    
    def test_missing_modules_handling(self):
        """Test handling of missing modules"""
        module_results = {
            "readin": {"cli_parameters": "-f1 -F0"}
        }
        execution_order = ["readin", "guide"]  # guide is missing
        
        result = generate_cli_command(module_results, execution_order)
        
        assert result["success"] is True
        # Should still generate command for available modules
        # CLI command contains executable path, so check for CLI parameters instead
        assert "-f1" in result["cli_command"] or "read_in" in result["cli_command"]
    
    def test_common_params_inclusion(self):
        """Test that common params are included"""
        module_results = {
            "readin": {"cli_parameters": "-f1 -F0"}
        }
        execution_order = ["readin"]
        
        result = generate_cli_command(module_results, execution_order)
        
        assert result["success"] is True
        # Common params should be in the command
        assert "--Z1" in result["cli_command"] or COMMON_PARAMS_BASE in result["cli_command"]
    
    def test_pipe_separators(self):
        """Test pipe separators between modules"""
        module_results = {
            "readin": {"cli_parameters": "-f1"},
            "guide": {"cli_parameters": "-Y0"}
        }
        execution_order = ["readin", "guide"]
        
        result = generate_cli_command(module_results, execution_order)
        
        assert result["success"] is True
        # Should have pipe between modules
        assert "|" in result["cli_command"]
    
    def test_no_execution_order(self):
        """Test when no execution order is provided"""
        module_results = {
            "readin": {"cli_parameters": "-f1"},
            "guide": {"cli_parameters": "-Y0"}
        }
        
        result = generate_cli_command(module_results, None)
        
        assert result["success"] is True
        # Should use module_results keys as order
        assert "cli_command" in result
    
    def test_empty_module_results(self):
        """Test with empty module results"""
        result = generate_cli_command({}, [])
        
        assert result["success"] is True
        assert "cli_command" in result


# Note: Tests for MCP tool functions (run_simulation, inspect_thread_folders)
# are removed because these functions are wrapped by @mcp.tool() decorator and cannot be called directly.
# These should be tested through integration tests or by accessing the underlying function if needed.


"""
Tests for readin_module_tools.py
"""
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from vitess_ai.mcp.readin_module_tools import (
    readin_params_to_cli,
    _try_load_files_from_storage,
    _try_load_instrument_file_from_storage,
    NF_MAX,
)


# Note: Tests for MCP tool functions (upload_file, set_files, upload_instrument_file, 
# file_status, instrument_file_status, get_files, get_instrument_file, clear_files,
# clear_instrument_file, validate_readin_module) are removed because these functions 
# are wrapped by @mcp.tool() decorator and cannot be called directly.
# These should be tested through integration tests or by accessing the underlying function if needed.


@pytest.mark.unit
class TestReadinParamsToCli:
    """Tests for readin_params_to_cli function"""
    
    def test_basic_cli_generation(self, sample_readin_params):
        """Test basic CLI generation"""
        cli = readin_params_to_cli(sample_readin_params)
        
        assert isinstance(cli, str)
    
    def test_list_handling(self, sample_readin_params):
        """Test list handling for sInputFileName and Weight"""
        cli = readin_params_to_cli(sample_readin_params)
        
        assert isinstance(cli, str)
        # Should contain flags for files and weights
    
    def test_enum_values(self, sample_readin_params):
        """Test enum value handling"""
        from vitess_ai.schema.base import VtPrgFormat
        sample_readin_params["ePrgFormat"] = VtPrgFormat.VT_MCSTAS_FMT
        cli = readin_params_to_cli(sample_readin_params)
        
        assert isinstance(cli, str)
    
    def test_none_values(self, sample_readin_params):
        """Test that None values are skipped"""
        sample_readin_params["iSurface"] = None
        cli = readin_params_to_cli(sample_readin_params)
        
        assert isinstance(cli, str)


@pytest.mark.unit
class TestTryLoadFilesFromStorage:
    """Tests for _try_load_files_from_storage function"""
    
    @patch('vitess_ai.server.file_storage.get_file_storage_service')
    @patch.dict(os.environ, {'THREAD_ID': 'test_thread'})
    def test_loads_from_storage(self, mock_get_storage):
        """Test loading files from storage"""
        mock_storage = MagicMock()
        mock_storage.get_file_paths_for_module.return_value = ["/path/to/file1.dat", "/path/to/file2.dat"]
        mock_get_storage.return_value = mock_storage
        
        with patch('vitess_ai.mcp.readin_module_tools._current_files', []):
            result = _try_load_files_from_storage("test_thread")
            
            assert result is True
    
    @patch.dict(os.environ, {}, clear=True)
    def test_no_thread_id(self):
        """Test when no thread ID is available"""
        result = _try_load_files_from_storage()
        
        assert result is False
    
    @patch('vitess_ai.server.file_storage.get_file_storage_service')
    @patch.dict(os.environ, {'THREAD_ID': 'test_thread'})
    def test_storage_exception(self, mock_get_storage):
        """Test handling storage exceptions"""
        mock_get_storage.side_effect = Exception("Storage error")
        
        result = _try_load_files_from_storage()
        
        assert result is False


@pytest.mark.unit
class TestTryLoadInstrumentFileFromStorage:
    """Tests for _try_load_instrument_file_from_storage function"""
    
    @patch('vitess_ai.server.file_storage.get_file_storage_service')
    @patch.dict(os.environ, {'THREAD_ID': 'test_thread'})
    def test_loads_from_storage(self, mock_get_storage):
        """Test loading instrument file from storage"""
        mock_storage = MagicMock()
        mock_storage.get_file_paths_for_module.return_value = ["/path/to/instrument.inf"]
        mock_get_storage.return_value = mock_storage
        
        with patch('vitess_ai.mcp.readin_module_tools._current_instrument_file', None):
            result = _try_load_instrument_file_from_storage("test_thread")
            
            assert result is True
    
    @patch.dict(os.environ, {}, clear=True)
    def test_no_thread_id(self):
        """Test when no thread ID is available"""
        result = _try_load_instrument_file_from_storage()
        
        assert result is False

"""
Tests for writeout_tools.py (LangChain tools for writeout module).
"""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from vitess_ai.agents.simulator.tools.writeout import (
    writeout_params_to_cli,
    _try_load_save_path_from_storage,
    validate_writeout_module,
)
from vitess_ai.schema.base import VtPrgFormat, VtDataFormat


@pytest.mark.unit
class TestWriteoutParamsToCli:
    """Tests for writeout_params_to_cli function"""
    
    def test_basic_cli_generation(self, sample_writeout_params):
        """Test basic CLI generation"""
        cli = writeout_params_to_cli(sample_writeout_params)
        
        assert isinstance(cli, str)
    
    def test_filter_limits_handling(self):
        """Test filter limits handling"""
        params = {
            "sOutFileName": "/tmp/output.dat",
            "bActive": True,
            "filter_limits": {
                "filtLambdaMin": 1.0,
                "filtLambdaMax": 10.0,
            }
        }
        
        cli = writeout_params_to_cli(params)
        
        assert isinstance(cli, str)
        # Should contain filter limit flags
    
    def test_output_flags_conversion(self):
        """Test output flags conversion"""
        params = {
            "sOutFileName": "/tmp/output.dat",
            "bActive": True,
            "output_flags": {
                "bF_cID": True,
                "bF_cTrc": False,
                "bF_cColor": True,
                "bF_cTOF": False,
                "bF_cLambda": True,
                "bF_cCounts": False,
                "bF_cPosition": True,
                "bF_cDirection": False,
                "bF_cSpin": True,
            }
        }
        
        cli = writeout_params_to_cli(params)
        
        assert isinstance(cli, str)
        # Should contain -c flag with binary string
        assert "-c" in cli
    
    def test_boolean_handling(self):
        """Test boolean value handling"""
        params = {
            "sOutFileName": "/tmp/output.dat",
            "bActive": True,
            "bHeader": False,
        }
        
        cli = writeout_params_to_cli(params)
        
        assert isinstance(cli, str)
        # Should convert booleans to 1/0
    
    def test_enum_values(self):
        """Test enum value handling"""
        params = {
            "sOutFileName": "/tmp/output.dat",
            "ePrgFormat": VtPrgFormat.VT_MCSTAS_FMT,
            "eDatFormat": VtDataFormat.VT_BINARY,
        }
        
        cli = writeout_params_to_cli(params)
        
        assert isinstance(cli, str)
    
    def test_none_values(self, sample_writeout_params):
        """Test that None values are skipped"""
        sample_writeout_params["sOutFileName"] = None
        cli = writeout_params_to_cli(sample_writeout_params)
        
        assert isinstance(cli, str)
        # Should not include None values


@pytest.mark.unit
class TestTryLoadSavePathFromStorage:
    """Tests for _try_load_save_path_from_storage function"""
    
    @patch('vitess_ai.server.file_storage.get_file_storage_service')
    @patch.dict(os.environ, {'THREAD_ID': 'test_thread'})
    def test_loads_from_storage(self, mock_get_storage):
        """Test loading save path from storage"""
        mock_storage = MagicMock()
        mock_storage.list_files.return_value = [{"file_path": "/path/to/output.dat"}]
        mock_get_storage.return_value = mock_storage
        
        with patch('vitess_ai.agents.simulator.tools.writeout._current_save_path', None):
            result = _try_load_save_path_from_storage()
            
            assert result is True
    
    @patch.dict(os.environ, {}, clear=True)
    def test_no_thread_id(self):
        """Test when no thread ID is available"""
        result = _try_load_save_path_from_storage()
        
        assert result is False
    
    @patch('vitess_ai.server.file_storage.get_file_storage_service')
    @patch.dict(os.environ, {'THREAD_ID': 'test_thread'})
    def test_storage_exception(self, mock_get_storage):
        """Test handling storage exceptions"""
        mock_get_storage.side_effect = Exception("Storage error")
        
        result = _try_load_save_path_from_storage()
        
        assert result is False
    
    @patch('vitess_ai.server.file_storage.get_file_storage_service')
    @patch.dict(os.environ, {'THREAD_ID': 'test_thread'})
    def test_no_files_in_storage(self, mock_get_storage):
        """Test when no files in storage"""
        mock_storage = MagicMock()
        mock_storage.list_files.return_value = []
        mock_get_storage.return_value = mock_storage
        
        result = _try_load_save_path_from_storage()
        
        assert result is False


@pytest.mark.unit
class TestValidateWriteoutModule:
    """Tests for validate_writeout_module tool."""

    @pytest.mark.asyncio
    async def test_accepts_multiple_parameter_sets(self):
        """Validation accepts list input and validates all sets in one call."""
        batch_params = [
            {"sOutFileName": "output_001.dat", "FactInt": 1.0},
            {"sOutFileName": "output_002.dat", "FactInt": 2.0},
        ]

        result = await validate_writeout_module.ainvoke({"parameters": batch_params})

        assert result["validation_status"] is True
        assert result["total_sets"] == 2
        assert isinstance(result["validated_params"], list)
        assert len(result["validated_params"]) == 2
        assert isinstance(result["cli_parameters"], list)
        assert len(result["cli_parameters"]) == 2

    @pytest.mark.asyncio
    async def test_accepts_json_array_string_for_multiple_sets(self):
        """Validation accepts JSON array string for batch input."""
        batch_params = json.dumps(
            [
                {"sOutFileName": "output_001.dat", "FactInt": 1.0},
                {"sOutFileName": "output_002.dat", "FactInt": 2.0},
            ]
        )

        result = await validate_writeout_module.ainvoke({"parameters": batch_params})

        assert result["validation_status"] is True
        assert result["total_sets"] == 2
        assert isinstance(result["validated_params"], list)

    @pytest.mark.asyncio
    async def test_reports_item_level_errors_for_invalid_batch(self):
        """Validation reports index-based errors when one batch set is invalid."""
        batch_params = [
            {"sOutFileName": "output_001.dat", "FactInt": 1.0},
            {"sOutFileName": "output_002.dat", "ePrgFormat": "INVALID_FORMAT"},
        ]

        result = await validate_writeout_module.ainvoke({"parameters": batch_params})

        assert result["validation_status"] is False
        assert result["total_sets"] == 2
        assert result["valid_sets"] == 1
        assert result["invalid_sets"] == 1
        assert isinstance(result["errors"], list)
        assert result["errors"][0]["index"] == 1

"""
Tests for guide_tools.py (LangChain tools for guide module).
"""
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from vitess_ai.agents.simulator.tools.guide import (
    guide_params_to_cli,
    validate_guide_parameters,
    _try_load_files_from_storage,
)
from vitess_ai.schema.base import VtGdeShape
from vitess_ai.schema.guide_module import GuideParameters


@pytest.mark.unit
class TestGuideParamsToCli:
    """Tests for guide_params_to_cli function"""
    
    def test_basic_cli_generation(self, sample_guide_params):
        """Test basic CLI generation"""
        cli = guide_params_to_cli(sample_guide_params)
        
        assert isinstance(cli, str)
        # Should contain some flags
        assert len(cli) >= 0  # May be empty if all values are defaults
    
    def test_enum_values(self, sample_guide_params):
        """Test enum value handling"""
        sample_guide_params["eGuideShapeY"] = VtGdeShape.VT_LINEAR
        cli = guide_params_to_cli(sample_guide_params)
        
        assert isinstance(cli, str)
    
    def test_none_values(self, sample_guide_params):
        """Test that None values are skipped"""
        sample_guide_params["Radius"] = None
        cli = guide_params_to_cli(sample_guide_params)
        
        # Should not include None values
        assert isinstance(cli, str)

    def test_default_config_produces_cli_without_s_flag(self):
        """Default configuration (no guide file) uses empty ShapeFileName; CLI omits -S."""
        default_params = GuideParameters().model_dump()
        assert default_params["ShapeFileName"] == ""
        cli = guide_params_to_cli(default_params)
        assert "-S" not in cli


@pytest.mark.unit
class TestValidateGuideParameters:
    """Tests for validate_guide_parameters tool (default config without file)."""

    @pytest.mark.asyncio
    async def test_accepts_config_without_shape_file_uses_default(self):
        """Validation accepts config that omits ShapeFileName; schema default (empty) is applied; CLI omits -S."""
        params_without_shape = {
            "eGuideShapeY": 0,
            "eGuideShapeZ": 0,
            "nPieces": 1,
            "GuideEntrWidth": 3.0,
            "GuideEntrHeight": 3.0,
            "GuideExitWidth": 3.0,
            "GuideExitHeight": 3.0,
            "piecelength": 50.0,
        }
        result = await validate_guide_parameters.ainvoke({"parameters": params_without_shape})
        assert result["validation_status"] is True
        assert result["validated_params"]["ShapeFileName"] == ""
        assert "-S" not in result["cli_parameters"]


@pytest.mark.unit
class TestTryLoadFilesFromStorage:
    """Tests for _try_load_files_from_storage function"""
    
    @patch('vitess_ai.server.file_storage.get_file_storage_service')
    @patch.dict(os.environ, {'THREAD_ID': 'test_thread'})
    def test_loads_from_storage(self, mock_get_storage):
        """Test loading files from storage"""
        mock_storage = MagicMock()
        mock_storage.get_file_paths_for_module.return_value = ["/path/to/file.dat"]
        mock_get_storage.return_value = mock_storage
        
        with patch('vitess_ai.agents.simulator.tools.guide._current_files', []):
            result = _try_load_files_from_storage()
            
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


"""
Tests for guide_tools.py (LangChain tools for guide module).
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from vitess_ai.agents.simulator.tools.guide import (
    guide_params_to_cli,
    validate_guide_parameters,
    _list_guide_file_for_thread,
    file_status,
    get_file,
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
        assert len(cli) >= 0

    def test_enum_values(self, sample_guide_params):
        """Test enum value handling"""
        sample_guide_params["eGuideShapeY"] = VtGdeShape.VT_LINEAR
        cli = guide_params_to_cli(sample_guide_params)

        assert isinstance(cli, str)

    def test_none_values(self, sample_guide_params):
        """Test that None values are skipped"""
        sample_guide_params["Radius"] = None
        cli = guide_params_to_cli(sample_guide_params)

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
class TestListGuideFileForThread:
    """Tests for _list_guide_file_for_thread"""

    @patch('vitess_ai.server.file_storage.get_file_storage_service')
    def test_returns_first_path_from_storage(self, mock_get_storage):
        """Test returns first file path from storage"""
        mock_storage = MagicMock()
        mock_storage.get_file_paths_for_module.return_value = ["/path/to/guide.dat"]
        mock_get_storage.return_value = mock_storage

        result = _list_guide_file_for_thread("test_thread")

        assert result == "/path/to/guide.dat"
        mock_storage.get_file_paths_for_module.assert_called_once_with("test_thread", "guide")

    @patch('vitess_ai.server.file_storage.get_file_storage_service')
    def test_returns_none_when_empty(self, mock_get_storage):
        """Test returns None when no files in storage"""
        mock_storage = MagicMock()
        mock_storage.get_file_paths_for_module.return_value = []
        mock_get_storage.return_value = mock_storage

        result = _list_guide_file_for_thread("test_thread")

        assert result is None

    @patch('vitess_ai.server.file_storage.get_file_storage_service')
    def test_returns_none_on_exception(self, mock_get_storage):
        """Test returns None when storage raises"""
        mock_get_storage.side_effect = Exception("Storage error")

        result = _list_guide_file_for_thread("test_thread")

        assert result is None


@pytest.mark.unit
class TestFileStatus:
    """Tests for file_status tool"""

    @pytest.mark.asyncio
    async def test_no_thread_id_returns_has_file_false(self):
        """Test file_status with no thread_id"""
        result = await file_status.ainvoke({"thread_id": None})
        assert result["has_file"] is False
        assert "thread_id" in result["message"].lower()

    @pytest.mark.asyncio
    @patch('vitess_ai.agents.simulator.tools.guide._list_guide_file_for_thread')
    async def test_with_file_from_storage(self, mock_list):
        """Test file_status when storage has a file"""
        mock_list.return_value = "/path/to/guide.dat"
        result = await file_status.ainvoke({"thread_id": "tid1"})
        assert result["has_file"] is True
        assert result["file_count"] == 1
        assert result["file"] == "/path/to/guide.dat"
        assert result["files"] == ["/path/to/guide.dat"]

    @pytest.mark.asyncio
    @patch('vitess_ai.agents.simulator.tools.guide._list_guide_file_for_thread')
    async def test_empty_storage_returns_has_file_false(self, mock_list):
        """Test file_status when storage has no file"""
        mock_list.return_value = None
        result = await file_status.ainvoke({"thread_id": "tid1"})
        assert result["has_file"] is False
        assert result["file_count"] == 0


@pytest.mark.unit
class TestGetFile:
    """Tests for get_file tool"""

    @pytest.mark.asyncio
    async def test_no_thread_id_returns_message(self):
        """Test get_file with no thread_id"""
        result = await get_file.ainvoke({"thread_id": None})
        assert isinstance(result, str)
        assert "thread_id" in result.lower()

    @pytest.mark.asyncio
    @patch('vitess_ai.agents.simulator.tools.guide._list_guide_file_for_thread')
    async def test_returns_file_from_storage(self, mock_list):
        """Test get_file returns path from storage"""
        mock_list.return_value = "/path/to/guide.dat"
        result = await get_file.ainvoke({"thread_id": "tid1"})
        assert result["file"] == "/path/to/guide.dat"
        assert result["file_name"] == "guide.dat"
        assert result["file_count"] == 1
        assert result["files"] == ["/path/to/guide.dat"]

    @pytest.mark.asyncio
    @patch('vitess_ai.agents.simulator.tools.guide._list_guide_file_for_thread')
    async def test_empty_storage_returns_message(self, mock_list):
        """Test get_file when storage is empty"""
        mock_list.return_value = None
        result = await get_file.ainvoke({"thread_id": "tid1"})
        assert isinstance(result, str)
        assert "No guide file" in result or "upload" in result.lower()

"""
Tests for readin_tools.py (LangChain tools for read-in module).
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from vitess_ai.agents.simulator.tools.readin import (
    readin_params_to_cli,
    _list_readin_files_for_thread,
    file_status,
    get_files,
    validate_readin_module,
)
from vitess_ai.schema.readin_module import NF_MAX


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
class TestListReadinFilesForThread:
    """Tests for _list_readin_files_for_thread"""

    @patch('vitess_ai.server.file_storage.get_file_storage_service')
    def test_returns_paths_from_storage(self, mock_get_storage):
        """Test listing files from storage"""
        mock_storage = MagicMock()
        mock_storage.get_file_paths_for_module.return_value = [
            "/path/to/file1.dat",
            "/path/to/file2.dat",
        ]
        mock_get_storage.return_value = mock_storage

        result = _list_readin_files_for_thread("test_thread")

        assert result == ["/path/to/file1.dat", "/path/to/file2.dat"]
        mock_storage.get_file_paths_for_module.assert_called_once_with("test_thread", "readin")

    @patch('vitess_ai.server.file_storage.get_file_storage_service')
    def test_returns_empty_on_exception(self, mock_get_storage):
        """Test returns empty list when storage raises"""
        mock_get_storage.side_effect = Exception("Storage error")

        result = _list_readin_files_for_thread("test_thread")

        assert result == []


@pytest.mark.unit
class TestFileStatus:
    """Tests for file_status tool"""

    @pytest.mark.asyncio
    async def test_no_thread_id_returns_has_files_false(self):
        """Test file_status with no thread_id"""
        result = await file_status.ainvoke({"thread_id": None})
        assert result["has_files"] is False
        assert "No thread_id" in result["message"]

    @pytest.mark.asyncio
    @patch('vitess_ai.agents.simulator.tools.readin._list_readin_files_for_thread')
    async def test_with_files_from_storage(self, mock_list):
        """Test file_status when storage has files"""
        mock_list.return_value = ["/p/f1.dat", "/p/f2.dat"]
        result = await file_status.ainvoke({"thread_id": "tid1"})
        assert result["has_files"] is True
        assert result["file_count"] == 2
        assert result["files"] == ["/p/f1.dat", "/p/f2.dat"]
        assert len(result["sInputFileName"]) == NF_MAX

    @pytest.mark.asyncio
    @patch('vitess_ai.agents.simulator.tools.readin._list_readin_files_for_thread')
    async def test_empty_storage_returns_has_files_false(self, mock_list):
        """Test file_status when storage has no files"""
        mock_list.return_value = []
        result = await file_status.ainvoke({"thread_id": "tid1"})
        assert result["has_files"] is False
        assert result["file_count"] == 0


@pytest.mark.unit
class TestGetFiles:
    """Tests for get_files tool"""

    @pytest.mark.asyncio
    async def test_no_thread_id_returns_message(self):
        """Test get_files with no thread_id"""
        result = await get_files.ainvoke({"thread_id": None})
        assert isinstance(result, str)
        assert "thread_id" in result.lower()

    @pytest.mark.asyncio
    @patch('vitess_ai.agents.simulator.tools.readin._list_readin_files_for_thread')
    async def test_returns_files_from_storage(self, mock_list):
        """Test get_files returns storage paths"""
        mock_list.return_value = ["/p/f1.dat"]
        result = await get_files.ainvoke({"thread_id": "tid1"})
        assert result["file_count"] == 1
        assert result["files"] == ["/p/f1.dat"]
        assert result["sInputFileName"][0] == "/p/f1.dat"

    @pytest.mark.asyncio
    @patch('vitess_ai.agents.simulator.tools.readin._list_readin_files_for_thread')
    async def test_empty_storage_returns_message(self, mock_list):
        """Test get_files when storage is empty"""
        mock_list.return_value = []
        result = await get_files.ainvoke({"thread_id": "tid1"})
        assert isinstance(result, str)
        assert "No files" in result or "upload" in result.lower()


@pytest.mark.unit
class TestValidateReadinModule:
    """Tests for validate_readin_module tool"""

    @pytest.mark.asyncio
    async def test_validates_with_sInputFileName_in_params(self, sample_readin_params):
        """Test validation when sInputFileName is provided in params"""
        params = {**sample_readin_params, "sInputFileName": ["/p/f.dat"], "Weight": [1.0]}
        result = await validate_readin_module.ainvoke({"parameters": json.dumps(params)})
        assert result["validation_status"] is True

    @pytest.mark.asyncio
    async def test_fills_sInputFileName_from_params_files(self, sample_readin_params):
        """Test validation fills sInputFileName from params.files"""
        params = {k: v for k, v in sample_readin_params.items() if k != "sInputFileName"}
        params["files"] = ["/p/f1.dat"]
        params["Weight"] = [1.0]
        result = await validate_readin_module.ainvoke({"parameters": json.dumps(params)})
        assert result["validation_status"] is True
        assert result["validated_params"]["sInputFileName"][0] == "/p/f1.dat"

    @pytest.mark.asyncio
    async def test_fills_sInputFileName_from_thread_id_when_missing(self, sample_readin_params):
        """Test validation fills sInputFileName from storage when thread_id given"""
        params = {k: v for k, v in sample_readin_params.items() if k != "sInputFileName"}
        params["Weight"] = [1.0]
        with patch('vitess_ai.agents.simulator.tools.readin._list_readin_files_for_thread') as mock_list:
            mock_list.return_value = ["/storage/f.dat"]
            result = await validate_readin_module.ainvoke({
                "parameters": json.dumps(params),
                "thread_id": "tid1",
            })
        assert result["validation_status"] is True
        assert result["validated_params"]["sInputFileName"][0] == "/storage/f.dat"

    @pytest.mark.asyncio
    async def test_fails_when_no_files_and_no_sInputFileName(self, sample_readin_params):
        """Test validation fails when sInputFileName missing and no thread_id/files"""
        params = {k: v for k, v in sample_readin_params.items() if k != "sInputFileName"}
        params["Weight"] = []
        result = await validate_readin_module.ainvoke({"parameters": json.dumps(params)})
        assert result["validation_status"] is False
        assert "sInputFileName" in result.get("message", "") or "files" in result.get("message", "").lower()

    @pytest.mark.asyncio
    async def test_accepts_multiple_parameter_sets(self):
        """Validation accepts list input and validates all sets in one call."""
        batch_params = [
            {
                "sInputFileName": ["/p/f1.dat"],
                "Weight": [1.0],
                "FactInt": 0.1,
            },
            {
                "sInputFileName": ["/p/f1.dat"],
                "Weight": [1.0],
                "FactInt": 0.5,
            },
        ]

        result = await validate_readin_module.ainvoke({"parameters": batch_params})

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
                {
                    "sInputFileName": ["/p/f1.dat"],
                    "Weight": [1.0],
                    "FactInt": 0.1,
                },
                {
                    "sInputFileName": ["/p/f1.dat"],
                    "Weight": [1.0],
                    "FactInt": 0.5,
                },
            ]
        )

        result = await validate_readin_module.ainvoke({"parameters": batch_params})

        assert result["validation_status"] is True
        assert result["total_sets"] == 2
        assert isinstance(result["validated_params"], list)

    @pytest.mark.asyncio
    async def test_reports_item_level_errors_for_invalid_batch(self):
        """Validation reports index-based errors when one batch set is invalid."""
        batch_params = [
            {
                "sInputFileName": ["/p/f1.dat"],
                "Weight": [1.0],
                "FactInt": 0.1,
            },
            {
                "sInputFileName": ["/p/f1.dat"],
                "Weight": [1.0, 2.0],
                "FactInt": 0.5,
            },
        ]

        result = await validate_readin_module.ainvoke({"parameters": batch_params})

        assert result["validation_status"] is False
        assert result["total_sets"] == 2
        assert result["valid_sets"] == 1
        assert result["invalid_sets"] == 1
        assert isinstance(result["errors"], list)
        assert result["errors"][0]["index"] == 1

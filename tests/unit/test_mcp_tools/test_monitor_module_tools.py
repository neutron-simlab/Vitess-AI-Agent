"""
Tests for monitor.py validation tools (Monitor1D and Monitor2D).
"""
import json
import pytest
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from vitess_ai.agents.simulator.tools.monitor import (
    validate_monitor1d_module,
    validate_monitor2d_module,
)


@pytest.mark.unit
class TestValidateMonitor1DModule:
    """Tests for validate_monitor1d_module tool."""

    @pytest.mark.asyncio
    async def test_accepts_multiple_parameter_sets(self):
        """Validation accepts list input and validates all sets in one call."""
        batch_params = [
            {},
            {"nBinsX": 200, "xMin": -1.0, "xMax": 1.0},
        ]

        result = await validate_monitor1d_module.ainvoke({"parameters": batch_params})

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
                {},
                {"nBinsX": 200, "xMin": -1.0, "xMax": 1.0},
            ]
        )

        result = await validate_monitor1d_module.ainvoke({"parameters": batch_params})

        assert result["validation_status"] is True
        assert result["total_sets"] == 2
        assert isinstance(result["validated_params"], list)

    @pytest.mark.asyncio
    async def test_reports_item_level_errors_for_invalid_batch(self):
        """Validation reports index-based errors when one batch set is invalid."""
        batch_params = [
            {"nBinsX": 100},
            {"nBinsX": "invalid"},
        ]

        result = await validate_monitor1d_module.ainvoke({"parameters": batch_params})

        assert result["validation_status"] is False
        assert result["total_sets"] == 2
        assert result["valid_sets"] == 1
        assert result["invalid_sets"] == 1
        assert isinstance(result["errors"], list)
        assert result["errors"][0]["index"] == 1


@pytest.mark.unit
class TestValidateMonitor2DModule:
    """Tests for validate_monitor2d_module tool."""

    @pytest.mark.asyncio
    async def test_accepts_multiple_parameter_sets(self):
        """Validation accepts list input and validates all sets in one call."""
        batch_params = [
            {},
            {"nBinsX": 120, "nBinsY": 140, "xMin": -1.5, "xMax": 1.5},
        ]

        result = await validate_monitor2d_module.ainvoke({"parameters": batch_params})

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
                {},
                {"nBinsX": 120, "nBinsY": 140},
            ]
        )

        result = await validate_monitor2d_module.ainvoke({"parameters": batch_params})

        assert result["validation_status"] is True
        assert result["total_sets"] == 2
        assert isinstance(result["validated_params"], list)

    @pytest.mark.asyncio
    async def test_reports_item_level_errors_for_invalid_batch(self):
        """Validation reports index-based errors when one batch set is invalid."""
        batch_params = [
            {"nBinsX": 100, "nBinsY": 100},
            {"format": "invalid"},
        ]

        result = await validate_monitor2d_module.ainvoke({"parameters": batch_params})

        assert result["validation_status"] is False
        assert result["total_sets"] == 2
        assert result["valid_sets"] == 1
        assert result["invalid_sets"] == 1
        assert isinstance(result["errors"], list)
        assert result["errors"][0]["index"] == 1

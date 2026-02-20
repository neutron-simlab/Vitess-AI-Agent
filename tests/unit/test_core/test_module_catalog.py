"""
Tests for central module catalog definitions.
"""
from pathlib import Path
import sys

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from vitess_ai.modules import (
    get_cli_executable_mapping,
    get_graph_module_metadata,
    get_upload_module_names,
)


@pytest.mark.unit
class TestModuleCatalog:
    """Validate graph and upload catalog consistency."""

    def test_graph_modules_have_stable_order(self):
        modules = get_graph_module_metadata()
        names = [module.name for module in modules]
        orders = [module.order for module in modules]

        assert names == ["readin", "guide", "writeout", "monitor1d", "monitor2d"]
        assert orders == sorted(orders)

    def test_graph_modules_have_validation_patterns(self):
        modules = get_graph_module_metadata()

        for module in modules:
            assert module.validation_tool_patterns

    def test_upload_modules_include_auxiliary_instrument(self):
        upload_modules = get_upload_module_names(include_auxiliary=True)
        assert "instrument" in upload_modules
        assert "readin" in upload_modules
        assert "writeout" in upload_modules

    def test_cli_executable_mapping_covers_graph_modules(self):
        mapping = get_cli_executable_mapping()
        assert mapping["readin"] == "$V/read_in"
        assert mapping["guide"] == "$V/guide_parallel"
        assert mapping["writeout"] == "$V/writeout"

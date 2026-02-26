"""
Tests for high-throughput simulation runner tools (simplified version).

Tests cover:
- Simulation matrix writing/reading
- JSON params to CLI conversion
- MCP delegation for simulation execution
"""
import json
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from vitess_ai.agents.high_throughput.tools import (
    _convert_simulation_to_module_results,
    _resolve_thread_id,
    MODULE_CLI_CONVERTERS,
)


@pytest.fixture
def sample_simulation_matrix():
    """Sample simulation matrix with 3 simulations varying FactInt."""
    return {
        "metadata": {
            "created_at": "2026-02-20T09:00:00+00:00",
            "thread_id": "test-thread-123",
            "total_simulations": 3,
            "varied_parameters": [
                {"module": "readin", "parameter": "FactInt", "values": [0.1, 0.5, 1.0]}
            ]
        },
        "simulations": [
            {
                "id": "sim_001",
                "readin": {
                    "ePrgFormat": 1,
                    "eDatFormat": 0,
                    "sInputFileName": ["/data/test/source.dat"],
                    "Weight": [1.0],
                    "FactInt": 0.1,
                    "iSurface": -1,
                    "iDetectColor": -1,
                    "nRep": 1,
                },
                "guide": {
                    "eGuideShapeY": 0,
                    "eGuideShapeZ": 0,
                    "ShapeFileName": "/data/test/guide_shape.dat",
                    "nPieces": 1,
                    "GuideEntrWidth": 3.0,
                    "GuideEntrHeight": 3.0,
                    "GuideExitWidth": 3.0,
                    "GuideExitHeight": 3.0,
                    "piecelength": 50.0,
                    "Radius": 0.0,
                    "D_Foc2Y": 0.0,
                    "D_Foc2Z": 0.0,
                    "MValGenL": 3.0,
                    "MValGenR": 3.0,
                    "MValGenTB": 3.0,
                },
                "writeout": {
                    "sOutFileName": "output_001.txt",
                    "bActive": True,
                    "bHeader": True,
                    "ePrgFormat": 1,
                    "eDatFormat": 1,
                    "eSeparator": 0,
                    "iDetectColor": -1,
                    "FactInt": 1.0,
                },
            },
            {
                "id": "sim_002",
                "readin": {
                    "ePrgFormat": 1,
                    "eDatFormat": 0,
                    "sInputFileName": ["/data/test/source.dat"],
                    "Weight": [1.0],
                    "FactInt": 0.5,
                    "iSurface": -1,
                    "iDetectColor": -1,
                    "nRep": 1,
                },
                "guide": {
                    "eGuideShapeY": 0,
                    "eGuideShapeZ": 0,
                    "ShapeFileName": "/data/test/guide_shape.dat",
                    "nPieces": 1,
                    "GuideEntrWidth": 3.0,
                    "GuideEntrHeight": 3.0,
                    "GuideExitWidth": 3.0,
                    "GuideExitHeight": 3.0,
                    "piecelength": 50.0,
                    "Radius": 0.0,
                    "D_Foc2Y": 0.0,
                    "D_Foc2Z": 0.0,
                    "MValGenL": 3.0,
                    "MValGenR": 3.0,
                    "MValGenTB": 3.0,
                },
                "writeout": {
                    "sOutFileName": "output_002.txt",
                    "bActive": True,
                    "bHeader": True,
                    "ePrgFormat": 1,
                    "eDatFormat": 1,
                    "eSeparator": 0,
                    "iDetectColor": -1,
                    "FactInt": 1.0,
                },
            },
            {
                "id": "sim_003",
                "readin": {
                    "ePrgFormat": 1,
                    "eDatFormat": 0,
                    "sInputFileName": ["/data/test/source.dat"],
                    "Weight": [1.0],
                    "FactInt": 1.0,
                    "iSurface": -1,
                    "iDetectColor": -1,
                    "nRep": 1,
                },
                "guide": {
                    "eGuideShapeY": 0,
                    "eGuideShapeZ": 0,
                    "ShapeFileName": "/data/test/guide_shape.dat",
                    "nPieces": 1,
                    "GuideEntrWidth": 3.0,
                    "GuideEntrHeight": 3.0,
                    "GuideExitWidth": 3.0,
                    "GuideExitHeight": 3.0,
                    "piecelength": 50.0,
                    "Radius": 0.0,
                    "D_Foc2Y": 0.0,
                    "D_Foc2Z": 0.0,
                    "MValGenL": 3.0,
                    "MValGenR": 3.0,
                    "MValGenTB": 3.0,
                },
                "writeout": {
                    "sOutFileName": "output_003.txt",
                    "bActive": True,
                    "bHeader": True,
                    "ePrgFormat": 1,
                    "eDatFormat": 1,
                    "eSeparator": 0,
                    "iDetectColor": -1,
                    "FactInt": 1.0,
                },
            },
        ]
    }


@pytest.fixture
def sample_readin_params():
    """Sample readin parameters."""
    return {
        "ePrgFormat": 1,
        "eDatFormat": 0,
        "sInputFileName": ["/data/test/source.dat"],
        "Weight": [1.0],
        "FactInt": 0.5,
        "iSurface": -1,
        "iDetectColor": -1,
        "nRep": 1,
    }


@pytest.fixture
def sample_guide_params():
    """Sample guide parameters."""
    return {
        "eGuideShapeY": 0,
        "eGuideShapeZ": 0,
        "ShapeFileName": "/data/test/guide_shape.dat",
        "nPieces": 1,
        "GuideEntrWidth": 3.0,
        "GuideEntrHeight": 3.0,
        "GuideExitWidth": 3.0,
        "GuideExitHeight": 3.0,
        "piecelength": 50.0,
        "Radius": 0.0,
        "D_Foc2Y": 0.0,
        "D_Foc2Z": 0.0,
        "MValGenL": 3.0,
        "MValGenR": 3.0,
        "MValGenTB": 3.0,
    }


@pytest.fixture
def sample_writeout_params():
    """Sample writeout parameters."""
    return {
        "sOutFileName": "output.txt",
        "bActive": True,
        "bHeader": True,
        "ePrgFormat": 1,
        "eDatFormat": 1,
        "eSeparator": 0,
        "iDetectColor": -1,
        "FactInt": 1.0,
    }


@pytest.mark.unit
class TestModuleCLIConverters:
    """Tests for MODULE_CLI_CONVERTERS mapping."""

    def test_all_core_modules_have_converters(self):
        """Verify all core modules have CLI converters."""
        expected_modules = ["readin", "guide", "writeout", "monitor1d", "monitor2d"]
        
        for module in expected_modules:
            assert module in MODULE_CLI_CONVERTERS, f"Missing converter for {module}"
            assert callable(MODULE_CLI_CONVERTERS[module])

    def test_readin_converter_produces_cli_string(self, sample_readin_params):
        """Test readin params to CLI conversion."""
        converter = MODULE_CLI_CONVERTERS["readin"]
        cli = converter(sample_readin_params)
        
        assert isinstance(cli, str)
        assert len(cli) > 0
        assert "-f" in cli or "-A" in cli

    def test_guide_converter_produces_cli_string(self, sample_guide_params):
        """Test guide params to CLI conversion."""
        converter = MODULE_CLI_CONVERTERS["guide"]
        cli = converter(sample_guide_params)
        
        assert isinstance(cli, str)
        assert len(cli) > 0

    def test_writeout_converter_produces_cli_string(self, sample_writeout_params):
        """Test writeout params to CLI conversion."""
        converter = MODULE_CLI_CONVERTERS["writeout"]
        cli = converter(sample_writeout_params)
        
        assert isinstance(cli, str)
        assert len(cli) > 0


@pytest.mark.unit
class TestConvertSimulationToModuleResults:
    """Tests for _convert_simulation_to_module_results function."""

    def test_converts_all_modules_successfully(
        self, sample_readin_params, sample_guide_params, sample_writeout_params
    ):
        """Test successful conversion of all modules."""
        simulation = {
            "id": "sim_001",
            "readin": sample_readin_params,
            "guide": sample_guide_params,
            "writeout": sample_writeout_params,
        }
        execution_order = ["readin", "guide", "writeout"]
        
        result = _convert_simulation_to_module_results(simulation, execution_order)
        
        assert result["success"] is True
        assert len(result["errors"]) == 0
        assert "readin" in result["module_results"]
        assert "guide" in result["module_results"]
        assert "writeout" in result["module_results"]

    def test_module_results_have_cli_parameters(
        self, sample_readin_params, sample_guide_params, sample_writeout_params
    ):
        """Test that converted results include cli_parameters."""
        simulation = {
            "readin": sample_readin_params,
            "guide": sample_guide_params,
            "writeout": sample_writeout_params,
        }
        execution_order = ["readin", "guide", "writeout"]
        
        result = _convert_simulation_to_module_results(simulation, execution_order)
        
        for module_name in execution_order:
            module_result = result["module_results"][module_name]
            assert "cli_parameters" in module_result
            assert isinstance(module_result["cli_parameters"], str)
            assert len(module_result["cli_parameters"]) > 0

    def test_reports_missing_module_params(self, sample_readin_params):
        """Test error reporting when module params are missing."""
        simulation = {
            "readin": sample_readin_params,
        }
        execution_order = ["readin", "guide", "writeout"]
        
        result = _convert_simulation_to_module_results(simulation, execution_order)
        
        assert result["success"] is False
        assert len(result["errors"]) == 2
        assert any("guide" in e for e in result["errors"])
        assert any("writeout" in e for e in result["errors"])

    def test_reports_unknown_module(self, sample_readin_params):
        """Test error reporting for unknown module."""
        simulation = {
            "readin": sample_readin_params,
            "unknown_module": {"param": "value"},
        }
        execution_order = ["readin", "unknown_module"]
        
        result = _convert_simulation_to_module_results(simulation, execution_order)
        
        assert result["success"] is False
        assert any("unknown_module" in e for e in result["errors"])

    def test_rejects_error_shaped_module_result(
        self, sample_readin_params, sample_guide_params, sample_writeout_params
    ):
        """Test that validation error payloads are rejected (dict key checks, no regex)."""
        simulation = {
            "id": "sim_001",
            "readin": sample_readin_params,
            "guide": {"validation_status": False, "errors": "Weight length mismatch", "message": "Invalid"},
            "writeout": sample_writeout_params,
        }
        execution_order = ["readin", "guide", "writeout"]

        result = _convert_simulation_to_module_results(simulation, execution_order)

        assert result["success"] is False
        assert any("guide" in e and "invalid or failed validation" in e for e in result["errors"])
        assert "readin" in result["module_results"]
        assert "guide" not in result["module_results"]
        assert "writeout" in result["module_results"]


@pytest.mark.unit
class TestResolveThreadId:
    """Tests for _resolve_thread_id function."""

    def test_returns_provided_thread_id(self):
        """Test that provided thread_id is returned."""
        result = _resolve_thread_id("my-thread-123")
        assert result == "my-thread-123"

    def test_returns_env_thread_id(self, monkeypatch):
        """Test fallback to THREAD_ID env var."""
        monkeypatch.setenv("THREAD_ID", "env-thread-456")
        result = _resolve_thread_id(None)
        assert result == "env-thread-456"

    def test_returns_none_when_no_thread_id(self, monkeypatch):
        """Test returns None when no thread_id available."""
        monkeypatch.delenv("THREAD_ID", raising=False)
        result = _resolve_thread_id(None)
        assert result is None


@pytest.mark.unit
class TestSimulationMatrixIntegration:
    """Integration tests for simulation matrix workflow."""

    def test_full_conversion_pipeline(self, sample_simulation_matrix):
        """Test converting full simulation matrix to run specs."""
        simulations = sample_simulation_matrix["simulations"]
        execution_order = ["readin", "guide", "writeout"]
        
        run_specs = []
        for sim in simulations:
            conversion = _convert_simulation_to_module_results(sim, execution_order)
            if conversion["success"]:
                run_specs.append({
                    "run_name": sim.get("id"),
                    "module_results": conversion["module_results"],
                    "execution_order": execution_order,
                })
        
        assert len(run_specs) == 3
        
        for run_spec in run_specs:
            assert "run_name" in run_spec
            assert run_spec["run_name"].startswith("sim_")
            assert "module_results" in run_spec
            
            for module_name in execution_order:
                module_result = run_spec["module_results"][module_name]
                assert "cli_parameters" in module_result
                assert "parameters" in module_result

    def test_factint_variation_preserved_in_cli(self, sample_simulation_matrix):
        """Test that FactInt variation is reflected in CLI strings."""
        simulations = sample_simulation_matrix["simulations"]
        execution_order = ["readin", "guide", "writeout"]
        
        cli_strings = []
        for sim in simulations:
            conversion = _convert_simulation_to_module_results(sim, execution_order)
            readin_cli = conversion["module_results"]["readin"]["cli_parameters"]
            cli_strings.append(readin_cli)
        
        assert len(cli_strings) == 3
        assert cli_strings[0] != cli_strings[1]
        assert cli_strings[1] != cli_strings[2]


@pytest.mark.asyncio
@pytest.mark.unit
class TestAsyncTools:
    """Tests for async tool functions."""

    async def test_write_simulation_matrix(self, temp_dir, sample_simulation_matrix, monkeypatch):
        """Test write_simulation_matrix tool."""
        from vitess_ai.agents.high_throughput.tools import write_simulation_matrix
        
        monkeypatch.setenv("THREAD_ID", "test-thread")
        monkeypatch.setattr(
            "vitess_ai.agents.high_throughput.tools.global_config.VITESS_PROJECT_PATH",
            str(temp_dir)
        )
        
        thread_dir = temp_dir / "test-thread" / "outputs"
        thread_dir.mkdir(parents=True, exist_ok=True)
        
        result = await write_simulation_matrix.ainvoke({
            "simulations": sample_simulation_matrix["simulations"],
            "varied_parameters": sample_simulation_matrix["metadata"]["varied_parameters"],
            "thread_id": "test-thread",
        })
        
        assert result["success"] is True
        assert "file_path" in result
        assert Path(result["file_path"]).exists()
        
        saved_data = json.loads(Path(result["file_path"]).read_text())
        assert len(saved_data["simulations"]) == 3

    async def test_write_simulation_matrix_rejects_error_shaped(self, temp_dir, monkeypatch):
        """Test write_simulation_matrix rejects simulations with error-shaped module data."""
        from vitess_ai.agents.high_throughput.tools import write_simulation_matrix

        monkeypatch.setenv("THREAD_ID", "test-thread")
        monkeypatch.setattr(
            "vitess_ai.agents.high_throughput.tools.global_config.VITESS_PROJECT_PATH",
            str(temp_dir),
        )

        simulations = [
            {
                "id": "sim_001",
                "readin": {"validation_status": False, "errors": "sInputFileName required"},
                "guide": {"ShapeFileName": "guide.dat"},
                "writeout": {"sOutFileName": "out.dat"},
            },
        ]
        result = await write_simulation_matrix.ainvoke({
            "simulations": simulations,
            "varied_parameters": [],
            "thread_id": "test-thread",
        })

        assert result["success"] is False
        assert "invalid" in result["message"].lower() or "error" in result["message"].lower()
        assert "sim_001" in result["message"] or "readin" in result["message"]
        assert result.get("file_path") is None

    async def test_read_simulation_matrix(self, temp_dir, sample_simulation_matrix, monkeypatch):
        """Test read_simulation_matrix tool."""
        from vitess_ai.agents.high_throughput.tools import read_simulation_matrix
        
        monkeypatch.setenv("THREAD_ID", "test-thread")
        monkeypatch.setattr(
            "vitess_ai.agents.high_throughput.tools.global_config.VITESS_PROJECT_PATH",
            str(temp_dir)
        )
        
        output_dir = temp_dir / "test-thread" / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        matrix_file = output_dir / "simulation_matrix.json"
        matrix_file.write_text(json.dumps(sample_simulation_matrix))
        
        result = await read_simulation_matrix.ainvoke({"thread_id": "test-thread"})
        
        assert result["success"] is True
        assert result["total_simulations"] == 3
        assert "matrix" in result

    async def test_convert_matrix_to_run_specs(self, temp_dir, sample_simulation_matrix, monkeypatch):
        """Test convert_matrix_to_run_specs tool."""
        from vitess_ai.agents.high_throughput.tools import convert_matrix_to_run_specs
        
        monkeypatch.setenv("THREAD_ID", "test-thread")
        monkeypatch.setattr(
            "vitess_ai.agents.high_throughput.tools.global_config.VITESS_PROJECT_PATH",
            str(temp_dir)
        )
        
        output_dir = temp_dir / "test-thread" / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        matrix_file = output_dir / "simulation_matrix.json"
        matrix_file.write_text(json.dumps(sample_simulation_matrix))
        
        result = await convert_matrix_to_run_specs.ainvoke({
            "thread_id": "test-thread",
            "execution_order": ["readin", "guide", "writeout"],
        })
        
        assert result["success"] is True
        assert result["converted_runs"] == 3
        assert len(result["run_specs"]) == 3
        
        for run_spec in result["run_specs"]:
            assert "run_name" in run_spec
            assert "module_results" in run_spec
            assert "execution_order" in run_spec
            
            for module in ["readin", "guide", "writeout"]:
                assert module in run_spec["module_results"]
                assert "cli_parameters" in run_spec["module_results"][module]

    async def test_convert_matrix_file_not_found(self, temp_dir, monkeypatch):
        """Test convert_matrix_to_run_specs when file not found."""
        from vitess_ai.agents.high_throughput.tools import convert_matrix_to_run_specs
        
        monkeypatch.setattr(
            "vitess_ai.agents.high_throughput.tools.global_config.VITESS_PROJECT_PATH",
            str(temp_dir)
        )
        
        output_dir = temp_dir / "test-thread" / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        result = await convert_matrix_to_run_specs.ainvoke({
            "thread_id": "test-thread",
        })
        
        assert result["success"] is False
        assert "not found" in result["message"]


@pytest.mark.unit
class TestCLIFlagGeneration:
    """Tests for CLI flag generation accuracy."""

    def test_readin_factint_in_cli(self):
        """Test FactInt parameter appears in readin CLI."""
        from vitess_ai.agents.simulator.tools.readin import readin_params_to_cli
        
        params = {
            "ePrgFormat": 1,
            "eDatFormat": 0,
            "sInputFileName": ["/data/source.dat"],
            "Weight": [1.0],
            "FactInt": 2.5,
        }
        
        cli = readin_params_to_cli(params)
        
        assert "-I2.5" in cli or "-I 2.5" in cli

    def test_guide_shape_file_in_cli(self):
        """Test ShapeFileName parameter appears in guide CLI."""
        from vitess_ai.agents.simulator.tools.guide import guide_params_to_cli
        
        params = {
            "eGuideShapeY": 0,
            "eGuideShapeZ": 0,
            "ShapeFileName": "/data/guide_shape.dat",
            "nPieces": 1,
            "GuideEntrWidth": 3.0,
            "GuideEntrHeight": 3.0,
            "GuideExitWidth": 3.0,
            "GuideExitHeight": 3.0,
            "piecelength": 50.0,
        }
        
        cli = guide_params_to_cli(params)
        
        assert "guide_shape.dat" in cli

    def test_writeout_output_file_in_cli(self):
        """Test sOutFileName parameter appears in writeout CLI."""
        from vitess_ai.agents.simulator.tools.writeout import writeout_params_to_cli
        
        params = {
            "sOutFileName": "/data/output.dat",
            "bActive": True,
            "bHeader": True,
            "ePrgFormat": 1,
            "eDatFormat": 1,
        }
        
        cli = writeout_params_to_cli(params)
        
        assert "output.dat" in cli

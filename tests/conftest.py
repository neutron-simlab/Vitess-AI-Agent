"""
Shared fixtures and test utilities for pytest tests
"""
import tempfile
import shutil
from pathlib import Path
from typing import Generator
import pytest

from vitess_ai.agents.simulator import ModuleMetadata, BaseModuleAgent


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for file tests"""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def create_temp_file(temp_dir: Path):
    """Helper to create temporary test files"""
    def _create(name: str, content: str = "test content") -> Path:
        file_path = temp_dir / name
        file_path.write_text(content)
        return file_path
    return _create


@pytest.fixture
def mock_env(monkeypatch):
    """Mock environment variables"""
    env_vars = {
        "THREAD_ID": "test_thread_123",
        "OPENAI_API_KEY": "test_openai_key",
        "BLABLADOR_API_KEY": "test_blablador_key",
        "BLABLADOR_BASE_URL": "https://test.blablador.com",
        "VITESS_MODULES_PATH": "/tmp/vitess/bin",
        "VITESS_PROJECT_PATH": "/tmp/vitess_project",
        "VITESS_LOG_PATH": "/tmp/vitess_logs",
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    return env_vars


@pytest.fixture
def sample_module_metadata():
    """Sample module metadata for testing"""
    def _create(name: str = "test_module", order: int = 1, optional: bool = False):
        class TestAgent(BaseModuleAgent):
            pass
        
        return ModuleMetadata(
            name=name,
            display_name=f"Test {name.title()}",
            description=f"Test module {name}",
            agent_class=TestAgent,
            optional=optional,
            order=order
        )
    return _create


@pytest.fixture
def sample_guide_params():
    """Sample guide parameters for testing"""
    return {
        "eGuideShapeY": 0,  # VT_CONSTANT
        "eGuideShapeZ": 0,  # VT_CONSTANT
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
def sample_readin_params():
    """Sample readin parameters for testing"""
    return {
        "ePrgFormat": 1,  # VT_VITESS_FMT
        "eDatFormat": 0,  # VT_EXPONENTIAL
        "sInputFileName": ["file1.dat", "file2.dat"],
        "Weight": [1.0, 1.0],
        "FactInt": 1.0,
        "iSurface": -1,
    }


@pytest.fixture
def sample_writeout_params():
    """Sample writeout parameters for testing"""
    return {
        "sOutFileName": "/tmp/output.dat",
        "bActive": True,
        "bHeader": True,
        "ePrgFormat": 1,  # VT_VITESS_FMT
        "eDatFormat": 1,  # VT_FLOAT
        "eSeparator": 0,  # VT_BLANK
        "iDetectColor": -1,
    }


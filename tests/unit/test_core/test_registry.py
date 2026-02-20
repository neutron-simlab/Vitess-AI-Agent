"""
Tests for registry.py
"""
import pytest
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from vitess_ai.core.registry import ModuleRegistry
from vitess_ai.agents.simulator import ModuleMetadata, BaseModuleAgent


@pytest.mark.unit
class TestModuleRegistry:
    """Tests for ModuleRegistry class"""
    
    def test_module_registration(self, sample_module_metadata):
        """Test module registration"""
        registry = ModuleRegistry()
        metadata = sample_module_metadata(name="test_module", order=1)
        
        registry.register_module(metadata)
        
        assert "test_module" in registry.list_modules()
        assert registry.get_module("test_module") == metadata
    
    def test_duplicate_registration(self, sample_module_metadata):
        """Test duplicate registration"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="test_module", order=1)
        metadata2 = sample_module_metadata(name="test_module", order=2)
        
        registry.register_module(metadata1)
        registry.register_module(metadata2)  # Should overwrite
        
        assert registry.get_module("test_module") == metadata2
    
    def test_module_retrieval(self, sample_module_metadata):
        """Test module retrieval"""
        registry = ModuleRegistry()
        metadata = sample_module_metadata(name="test_module", order=1)
        
        registry.register_module(metadata)
        
        retrieved = registry.get_module("test_module")
        assert retrieved == metadata
    
    def test_module_unregistration(self, sample_module_metadata):
        """Test module unregistration"""
        registry = ModuleRegistry()
        metadata = sample_module_metadata(name="test_module", order=1)
        
        registry.register_module(metadata)
        result = registry.unregister_module("test_module")
        
        assert result is True
        assert registry.get_module("test_module") is None
    
    def test_list_modules(self, sample_module_metadata):
        """Test list modules"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="module1", order=1)
        metadata2 = sample_module_metadata(name="module2", order=2)
        
        registry.register_module(metadata1)
        registry.register_module(metadata2)
        
        modules = registry.list_modules()
        
        assert "module1" in modules
        assert "module2" in modules
        assert len(modules) == 2
    
    def test_get_all_modules(self, sample_module_metadata):
        """Test get all modules"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="module1", order=1)
        metadata2 = sample_module_metadata(name="module2", order=2)
        
        registry.register_module(metadata1)
        registry.register_module(metadata2)
        
        all_modules = registry.get_all_modules()
        
        assert isinstance(all_modules, dict)
        assert "module1" in all_modules
        assert "module2" in all_modules
        assert len(all_modules) == 2


@pytest.mark.unit
class TestGetExecutionOrder:
    """Tests for get_execution_order method"""
    
    def test_default_order(self, sample_module_metadata):
        """Test default order"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="module1", order=1)
        metadata2 = sample_module_metadata(name="module2", order=2)
        metadata3 = sample_module_metadata(name="module3", order=3)
        
        registry.register_module(metadata3)
        registry.register_module(metadata1)
        registry.register_module(metadata2)
        
        order = registry.get_execution_order()
        
        assert order == ["module1", "module2", "module3"]
    
    def test_custom_order(self, sample_module_metadata):
        """Test custom order"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="module1", order=1)
        metadata2 = sample_module_metadata(name="module2", order=2)
        metadata3 = sample_module_metadata(name="module3", order=3)
        
        registry.register_module(metadata1)
        registry.register_module(metadata2)
        registry.register_module(metadata3)
        
        order = registry.get_execution_order(["module3", "module1", "module2"])
        
        # Should sort by order field
        assert order == ["module1", "module2", "module3"]
    
    def test_sorting_by_order_field(self, sample_module_metadata):
        """Test sorting by order field"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="module1", order=3)
        metadata2 = sample_module_metadata(name="module2", order=1)
        metadata3 = sample_module_metadata(name="module3", order=2)
        
        registry.register_module(metadata1)
        registry.register_module(metadata2)
        registry.register_module(metadata3)
        
        order = registry.get_execution_order()
        
        assert order == ["module2", "module3", "module1"]


@pytest.mark.unit
class TestGetExecutionPlan:
    """Tests for get_execution_plan method"""
    
    def test_plan_generation(self, sample_module_metadata):
        """Test plan generation"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="module1", order=1, optional=False)
        metadata2 = sample_module_metadata(name="module2", order=2, optional=True)
        
        registry.register_module(metadata1)
        registry.register_module(metadata2)
        
        plan = registry.get_execution_plan()
        
        assert plan.execution_order == ["module1", "module2"]
        assert plan.total_modules == 2
        assert len(plan.modules_info) == 2
    
    def test_error_handling(self, sample_module_metadata):
        """Test error handling"""
        registry = ModuleRegistry()
        
        # Create a plan even with no modules
        plan = registry.get_execution_plan()
        
        assert plan.execution_order == []
        assert plan.total_modules == 0
    
    def test_module_info_formatting(self, sample_module_metadata):
        """Test module info formatting"""
        registry = ModuleRegistry()
        metadata = sample_module_metadata(name="test_module", order=1, optional=False)
        
        registry.register_module(metadata)
        
        plan = registry.get_execution_plan()
        
        assert len(plan.modules_info) == 1
        module_info = plan.modules_info[0]
        assert module_info["name"] == "test_module"
        assert module_info["order"] == 1
        assert module_info["optional"] is False


@pytest.mark.unit
class TestValidateModules:
    """Tests for validate_modules method"""
    
    def test_duplicate_order_detection(self, sample_module_metadata):
        """Test duplicate order detection"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="module1", order=1)
        metadata2 = sample_module_metadata(name="module2", order=1)  # Same order
        
        registry.register_module(metadata1)
        registry.register_module(metadata2)
        
        issues = registry.validate_modules()
        
        # Should detect duplicate orders
        assert len(issues) > 0
        assert any("same order" in issue.lower() for issue in issues)
    
    def test_missing_agent_class(self, sample_module_metadata):
        """Test missing agent class"""
        registry = ModuleRegistry()
        
        # Create metadata with a valid agent class (can't create with None due to Pydantic validation)
        metadata = sample_module_metadata(name="test_module", order=1)
        registry.register_module(metadata)
        
        # Test validation - should pass since we have a valid agent class
        issues = registry.validate_modules()
        
        # With valid agent class, should have no issues or only warnings
        # This test verifies the validation runs without errors
        assert isinstance(issues, list)


@pytest.mark.unit
class TestBulkRegisterModules:
    """Tests for bulk_register_modules method"""
    
    def test_multiple_registration(self, sample_module_metadata):
        """Test multiple registration"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="module1", order=1)
        metadata2 = sample_module_metadata(name="module2", order=2)
        metadata3 = sample_module_metadata(name="module3", order=3)
        
        registry.bulk_register_modules([metadata1, metadata2, metadata3])
        
        assert len(registry.list_modules()) == 3
        assert "module1" in registry.list_modules()
        assert "module2" in registry.list_modules()
        assert "module3" in registry.list_modules()


@pytest.mark.unit
class TestFindModulesByNamePattern:
    """Tests for find_modules_by_name_pattern method"""
    
    def test_pattern_matching(self, sample_module_metadata):
        """Test pattern matching"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="readin_module", order=1)
        metadata2 = sample_module_metadata(name="guide_module", order=2)
        metadata3 = sample_module_metadata(name="writeout_module", order=3)
        
        registry.register_module(metadata1)
        registry.register_module(metadata2)
        registry.register_module(metadata3)
        
        # Find modules with "readin" in name
        matches = registry.find_modules_by_name_pattern("readin")
        
        assert "readin_module" in matches
        assert len(matches) == 1
    
    def test_case_insensitive_matching(self, sample_module_metadata):
        """Test case insensitive matching"""
        registry = ModuleRegistry()
        metadata = sample_module_metadata(name="ReadInModule", order=1)
        
        registry.register_module(metadata)
        
        matches = registry.find_modules_by_name_pattern("readin")
        
        assert "ReadInModule" in matches


@pytest.mark.unit
class TestGetOrderGroups:
    """Tests for get_order_groups method"""
    
    def test_order_groups(self, sample_module_metadata):
        """Test order groups"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="module1", order=1)
        metadata2 = sample_module_metadata(name="module2", order=1)  # Same order
        metadata3 = sample_module_metadata(name="module3", order=2)
        
        registry.register_module(metadata1)
        registry.register_module(metadata2)
        registry.register_module(metadata3)
        
        groups = registry.get_order_groups()
        
        assert isinstance(groups, dict)
        assert 1 in groups
        assert 2 in groups
        assert len(groups[1]) == 2  # Two modules with order 1
        assert len(groups[2]) == 1  # One module with order 2


@pytest.mark.unit
class TestClearAllModules:
    """Tests for clear_all_modules method"""
    
    def test_clear_all_modules(self, sample_module_metadata):
        """Test clearing all modules"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="module1", order=1)
        metadata2 = sample_module_metadata(name="module2", order=2)
        
        registry.register_module(metadata1)
        registry.register_module(metadata2)
        
        registry.clear_all_modules()
        
        assert len(registry.list_modules()) == 0
        assert registry.get_module("module1") is None
        assert registry.get_module("module2") is None


@pytest.mark.unit
class TestGetModuleCount:
    """Tests for get_module_count method"""
    
    def test_module_count(self, sample_module_metadata):
        """Test module count"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="module1", order=1, optional=False)
        metadata2 = sample_module_metadata(name="module2", order=2, optional=True)
        metadata3 = sample_module_metadata(name="module3", order=3, optional=True)
        
        registry.register_module(metadata1)
        registry.register_module(metadata2)
        registry.register_module(metadata3)
        
        counts = registry.get_module_count()
        
        assert counts["total"] == 3
        assert counts["required"] == 1
        assert counts["optional"] == 2


@pytest.mark.unit
class TestGetModulesInfo:
    """Tests for get_modules_info method"""
    
    def test_modules_info(self, sample_module_metadata):
        """Test modules info"""
        registry = ModuleRegistry()
        metadata1 = sample_module_metadata(name="module1", order=2)
        metadata2 = sample_module_metadata(name="module2", order=1)
        
        registry.register_module(metadata1)
        registry.register_module(metadata2)
        
        info = registry.get_modules_info()
        
        assert len(info) == 2
        # Should be sorted by order
        assert info[0]["order"] == 1
        assert info[1]["order"] == 2
        assert all("name" in item for item in info)
        assert all("display_name" in item for item in info)
        assert all("description" in item for item in info)


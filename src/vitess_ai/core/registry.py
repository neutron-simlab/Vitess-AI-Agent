"""
registry.py - Simplified Module Registry (No Dependencies)
Handles module registration and simple execution planning
"""
import logging
from typing import Dict, List, Optional, Any
from vitess_ai.schema.supervisor import ExecutionPlan
from vitess_ai.server_agents.base_module_agent import ModuleMetadata


class ModuleRegistry:
    """Registry for managing simulation modules - no dependencies needed!"""
    
    def __init__(self):
        self._modules: Dict[str, ModuleMetadata] = {}
        self._logger = logging.getLogger(__name__)
    
    def register_module(self, module_metadata: ModuleMetadata) -> None:
        """Register a new module"""
        if module_metadata.name in self._modules:
            self._logger.warning(f"Module '{module_metadata.name}' already registered, overwriting")
        
        self._modules[module_metadata.name] = module_metadata
        self._logger.info(f"Registered module: {module_metadata.name}")
    
    def unregister_module(self, module_name: str) -> bool:
        """Unregister a module"""
        if module_name in self._modules:
            del self._modules[module_name]
            self._logger.info(f"Unregistered module: {module_name}")
            return True
        return False
    
    def get_module(self, module_name: str) -> Optional[ModuleMetadata]:
        """Get a module definition"""
        return self._modules.get(module_name)
    
    def list_modules(self) -> List[str]:
        """List all registered module names"""
        return list(self._modules.keys())
    
    def get_all_modules(self) -> Dict[str, ModuleMetadata]:
        """Get all module definitions"""
        return self._modules.copy()
    
    def get_execution_order(self, requested_modules: Optional[List[str]] = None) -> List[str]:
        """Get execution order"""
        if requested_modules is None:
            requested_modules = list(self._modules.keys())
        
        # Simple: sort by order (1, 2, 3, etc.)
        def get_order(module_name: str) -> int:
            module_metadata = self._modules.get(module_name)
            return module_metadata.order if module_metadata else 999
        
        return sorted(requested_modules, key=get_order)
    
    def get_execution_plan(self, requested_modules: Optional[List[str]] = None) -> ExecutionPlan:
        """Get execution plan for modules"""
        try:
            execution_order = self.get_execution_order(requested_modules)
            
            modules_info = []
            for module_name in execution_order:
                module_metadata = self._modules.get(module_name)
                if module_metadata:
                    modules_info.append({
                        "name": module_name,
                        "display_name": module_metadata.display_name,
                        "optional": module_metadata.optional,
                        "order": module_metadata.order
                    })
            
            return ExecutionPlan(
                execution_order=execution_order,
                total_modules=len(execution_order),
                modules_info=modules_info
            )
        except Exception as e:
            return ExecutionPlan(
                execution_order=[],
                total_modules=0,
                error=str(e)
            )
    
    def get_modules_info(self) -> List[Dict[str, Any]]:
        """Get formatted information about all modules"""
        modules = []
        for name, module_metadata in self._modules.items():
            modules.append({
                "name": name,
                "display_name": module_metadata.display_name,
                "description": module_metadata.description,
                "optional": module_metadata.optional,
                "order": module_metadata.order
            })
        return sorted(modules, key=lambda x: x["order"])
    
    def clear_all_modules(self) -> None:
        """Clear all registered modules"""
        count = len(self._modules)
        self._modules.clear()
        self._logger.info(f"Cleared {count} modules from registry")
    
    def bulk_register_modules(self, modules: List[ModuleMetadata]) -> None:
        """Register multiple modules at once"""
        for module_metadata in modules:
            self.register_module(module_metadata)
        self._logger.info(f"Bulk registered {len(modules)} modules")
    
    def validate_modules(self) -> List[str]:
        """Basic validation of registered modules"""
        issues = []
        
        # Check for duplicate orders (warning, not error)
        orders = {}
        for name, module_metadata in self._modules.items():
            if module_metadata.order in orders:
                issues.append(f"Modules '{name}' and '{orders[module_metadata.order]}' have same order {module_metadata.order}")
            else:
                orders[module_metadata.order] = name
        
        # Check for missing agent classes
        for name, module_metadata in self._modules.items():
            if not module_metadata.agent_class:
                issues.append(f"Module '{name}' has no agent class")
        
        return issues
    
    def get_module_count(self) -> Dict[str, int]:
        """Get counts of different module types"""
        total = len(self._modules)
        optional = sum(1 for m in self._modules.values() if m.optional)
        required = total - optional
        
        return {
            "total": total,
            "required": required,
            "optional": optional
        }
    
    def find_modules_by_name_pattern(self, pattern: str) -> List[str]:
        """Find modules matching a name pattern"""
        import re
        matching = []
        for module_name in self._modules.keys():
            if re.search(pattern, module_name, re.IGNORECASE):
                matching.append(module_name)
        return matching
    
    def get_order_groups(self) -> Dict[int, List[str]]:
        """Group modules by order level"""
        groups = {}
        for name, module_metadata in self._modules.items():
            order = module_metadata.order
            if order not in groups:
                groups[order] = []
            groups[order].append(name)
        return groups
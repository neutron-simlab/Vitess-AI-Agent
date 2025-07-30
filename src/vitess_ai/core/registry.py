"""
registry.py - Simplified Module Registry (No Dependencies)
Handles module registration and simple execution planning
"""
import logging
from typing import Dict, List, Optional
from vitess_ai.schema.supervisor_modules import ExecutionPlan
from vitess_ai.agents.base_module_agent import ModuleMetadata


class ModuleRegistry:
    """Registry for managing simulation modules - no dependencies needed!"""
    
    def __init__(self):
        self._modules: Dict[str, ModuleMetadata] = {}
        self._logger = logging.getLogger(__name__)
    
    def register_module(self, module_def: ModuleMetadata) -> None:
        """Register a new module"""
        if module_def.name in self._modules:
            self._logger.warning(f"Module '{module_def.name}' already registered, overwriting")
        
        self._modules[module_def.name] = module_def
        self._logger.info(f"Registered module: {module_def.name}")
    
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
        """Get execution order - just sort by order since no dependencies"""
        if requested_modules is None:
            requested_modules = list(self._modules.keys())
        
        # Simple: sort by order (1, 2, 3, etc.)
        def get_order(module_name: str) -> int:
            module_def = self._modules.get(module_name)
            return module_def.order if module_def else 999
        
        return sorted(requested_modules, key=get_order)
    
    def get_execution_plan(self, requested_modules: Optional[List[str]] = None) -> ExecutionPlan:
        """Get execution plan for modules"""
        try:
            execution_order = self.get_execution_order(requested_modules)
            
            modules_info = []
            for module_name in execution_order:
                module_def = self._modules.get(module_name)
                if module_def:
                    modules_info.append({
                        "name": module_name,
                        "display_name": module_def.display_name,
                        "optional": module_def.optional,
                        "order": module_def.order
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
    
    def get_modules_info(self) -> List[Dict[str, any]]:
        """Get formatted information about all modules"""
        modules = []
        for name, module_def in self._modules.items():
            modules.append({
                "name": name,
                "display_name": module_def.display_name,
                "description": module_def.description,
                "optional": module_def.optional,
                "order": module_def.order
            })
        return sorted(modules, key=lambda x: x["order"])
    
    def clear_all_modules(self) -> None:
        """Clear all registered modules"""
        count = len(self._modules)
        self._modules.clear()
        self._logger.info(f"Cleared {count} modules from registry")
    
    def bulk_register_modules(self, modules: List[ModuleMetadata]) -> None:
        """Register multiple modules at once"""
        for module_def in modules:
            self.register_module(module_def)
        self._logger.info(f"Bulk registered {len(modules)} modules")
    
    def validate_modules(self) -> List[str]:
        """Basic validation of registered modules"""
        issues = []
        
        # Check for duplicate orders (warning, not error)
        orders = {}
        for name, module_def in self._modules.items():
            if module_def.order in orders:
                issues.append(f"Modules '{name}' and '{orders[module_def.order]}' have same order {module_def.order}")
            else:
                orders[module_def.order] = name
        
        # Check for missing agent classes
        for name, module_def in self._modules.items():
            if not module_def.agent_class:
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
        for name, module_def in self._modules.items():
            order = module_def.order
            if order not in groups:
                groups[order] = []
            groups[order].append(name)
        return groups
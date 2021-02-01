# vim: ts=4:sw=4:et:cc=120
#

from ace.api import get_api
from ace.api.analysis import AnalysisModuleType
from ace.api.local import LocalAceAPI
from ace.module.base import AnalysisModule
from ace.module.manager import AnalysisModuleManager, SCALE_UP, SCALE_DOWN, NO_SCALING

import pytest


class CustomAnalysisModule(AnalysisModule):
    pass


class CustomAnalysisModule2(AnalysisModule):
    pass


@pytest.mark.unit
def test_add_module():
    manager = AnalysisModuleManager()
    module = CustomAnalysisModule()
    assert manager.add_module(module) is module
    assert module in manager.analysis_modules
    # insert same instance twice fails
    assert manager.add_module(module) is None
    module = CustomAnalysisModule()
    # insert another instance of a class already added fails
    assert manager.add_module(module) is None
    module_2 = CustomAnalysisModule2()
    assert manager.add_module(module_2) is module_2
    assert len(manager.analysis_modules) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_registration():
    # registration OK
    amt = AnalysisModuleType("test", "", additional_cache_keys=["yara:6f5902ac237024bdd0c176cb93063dc4"])

    assert await get_api().register_analysis_module_type(amt)

    manager = AnalysisModuleManager()
    manager.add_module(CustomAnalysisModule(amt))
    assert await manager.verify_registration()
    # missing registration
    amt = AnalysisModuleType("missing", "")
    manager = AnalysisModuleManager()
    manager.add_module(CustomAnalysisModule(amt))
    assert not await manager.verify_registration()
    # version mismatch
    amt = AnalysisModuleType("test", "", version="1.0.1")
    manager = AnalysisModuleManager()
    manager.add_module(CustomAnalysisModule(amt))
    assert not await manager.verify_registration()
    # extended version mismatch
    amt = AnalysisModuleType("test", "", additional_cache_keys=["yara:71bec09d78fe6abdb94244a4cc89c740"])
    manager = AnalysisModuleManager()
    manager.add_module(CustomAnalysisModule(amt))
    assert not await manager.verify_registration()
    # extended version mismatch but upgrade ok
    class UpgradableAnalysisModule(AnalysisModule):
        def upgrade(self):
            self.type.additional_cache_keys = ["yara:6f5902ac237024bdd0c176cb93063dc4"]

    # starts out with the wrong set of yara rules but upgrade() fixes that
    amt = AnalysisModuleType("test", "", additional_cache_keys=["yara:71bec09d78fe6abdb94244a4cc89c740"])
    manager = AnalysisModuleManager()
    manager.add_module(UpgradableAnalysisModule(amt))
    assert await manager.verify_registration()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scaling_task_creation():
    class CustomManager(AnalysisModuleManager):
        direction = SCALE_DOWN

        def compute_scaling(self, module):
            return self.direction

        def _new_module_task(self, module, whoami):
            self.module_tasks.append(object())

        def total_task_count(self):
            return sum(iter(self.module_task_count.values()))

    amt = AnalysisModuleType("test", "")
    result = await get_api().register_analysis_module_type(amt)
    manager = CustomManager()
    module = AnalysisModule(amt, limit=2)
    manager.add_module(module)

    # no tasks to start
    assert manager.total_task_count() == 0

    # starts with one task
    manager.initialize_module_tasks()
    assert manager.total_task_count() == 1

    # scale up to 2 tasks
    manager.direction = SCALE_UP
    result = await manager.module_loop(module, "test")
    assert manager.total_task_count() == 2

    # should not scale past limit
    result = await manager.module_loop(module, "test")
    assert manager.total_task_count() == 2

    # scale down to one task
    manager.direction = SCALE_DOWN
    result = await manager.module_loop(module, "test")
    assert manager.total_task_count() == 1

    # scale down does not drop below one task
    result = await manager.module_loop(module, "test")
    assert manager.total_task_count() == 1

    # after shutdown it drops to zero tasks
    manager.shutdown = True
    await manager.module_loop(module, "test")
    assert manager.total_task_count() == 0
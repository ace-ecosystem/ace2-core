# vim: ts=4:sw=4:et:cc=120
#

from ace.api.local import LocalAceAPI
from ace.module.base import AnalysisModule
from ace.module.manager import AnalysisModuleManager

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_manager_start(event_loop):
    await AnalysisModuleManager().run()

# vim: ts=4:sw=4:et:cc=120

from typing import Union

from ace.analysis import AnalysisModuleType
from ace.system import ACESystem


class RemoteAnalysisModuleTrackingInterface(ACESystem):
    async def register_analysis_module_type(self, amt: AnalysisModuleType) -> AnalysisModuleType:
        return await self.get_api().register_analysis_module_type(amt)

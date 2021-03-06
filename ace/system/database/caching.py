# vim: ts=4:sw=4:et:cc=120

import datetime

from dataclasses import dataclass
from typing import Union, Optional

import ace

from ace.analysis import AnalysisModuleType
from ace.system.base import CachingBaseInterface
from ace.system.database.schema import AnalysisResultCache
from ace.system.requests import AnalysisRequest
from ace.time import utc_now

from sqlalchemy import func
from sqlalchemy.sql import select, delete


class DatabaseCachingInterface(CachingBaseInterface):
    async def i_get_cached_analysis_result(self, cache_key: str) -> Union[AnalysisRequest, None]:
        async with self.get_db() as db:
            result = (
                await db.execute(select(AnalysisResultCache).where(AnalysisResultCache.cache_key == cache_key))
            ).one_or_none()
            if result is None:
                return None

            result = result[0]
            if result.expiration_date is not None and utc_now() > result.expiration_date:
                return None

            return AnalysisRequest.from_json(result.json_data, system=self)

    async def i_cache_analysis_result(self, cache_key: str, request: AnalysisRequest, expiration: Optional[int]) -> str:
        expiration_date = None
        # XXX using system side time
        if expiration is not None:
            expiration_date = utc_now() + datetime.timedelta(seconds=expiration)

        cache_result = AnalysisResultCache(
            cache_key=cache_key,
            expiration_date=expiration_date,
            analysis_module_type=request.type.name,
            json_data=request.to_json(),
        )

        async with self.get_db() as db:
            await db.merge(cache_result)
            await db.commit()

        return cache_key

    async def i_delete_expired_cached_analysis_results(self):
        async with self.get_db() as db:
            await db.execute(delete(AnalysisResultCache).where(AnalysisResultCache.expiration_date < utc_now()))
            await db.commit()

    async def i_delete_cached_analysis_results_by_module_type(self, amt: AnalysisModuleType):
        async with self.get_db() as db:
            await db.execute(delete(AnalysisResultCache).where(AnalysisResultCache.analysis_module_type == amt.name))
            await db.commit()

    async def i_get_cache_size(self, amt: Optional[AnalysisModuleType] = None) -> int:
        async with self.get_db() as db:
            if amt:
                return (
                    await db.execute(
                        select(func.count(AnalysisResultCache.cache_key)).where(
                            AnalysisResultCache.analysis_module_type == amt.name
                        )
                    )
                ).scalar()
            else:
                return (await db.execute(select(func.count(AnalysisResultCache.cache_key)))).scalar()

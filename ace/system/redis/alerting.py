# vim: ts=4:sw=4:et:cc=120
#

#
# NOTE the timeout option for get_alerts has to be an int for Redis < version 6
# so we're using integers for now

from typing import Optional

from ace.system.base import AlertingBaseInterface
from ace.exceptions import UnknownAlertSystemError
from ace.time import utc_now

KEY_ALERT_SYSTEMS = "alert_systems"


def get_alert_queue(name: str) -> str:
    return f"alert_system:{name}"


class RedisAlertTrackingInterface(AlertingBaseInterface):
    async def i_register_alert_system(self, name: str) -> bool:
        async with self.get_redis_connection() as rc:
            return await rc.hsetnx(KEY_ALERT_SYSTEMS, name, str(utc_now())) == 1

    async def i_unregister_alert_system(self, name: str) -> bool:
        async with self.get_redis_connection() as rc:
            return await rc.hdel(KEY_ALERT_SYSTEMS, name) == 1

    async def i_submit_alert(self, root_uuid: str) -> bool:
        async with self.get_redis_connection() as rc:
            result = False
            for name in await rc.hkeys(KEY_ALERT_SYSTEMS):
                result = True
                name = name.decode()
                await rc.rpush(get_alert_queue(name), root_uuid)

        return result

    async def i_get_alerts(self, name: str, timeout: Optional[int] = None) -> list[str]:
        async with self.get_redis_connection() as rc:
            if not await rc.hexists(KEY_ALERT_SYSTEMS, name):
                raise UnknownAlertSystemError(name)

            result = []

            if timeout is None:
                while True:
                    alert_uuid = await rc.lpop(get_alert_queue(name))
                    if alert_uuid is None:
                        break

                    result.append(alert_uuid.decode())

                return result

            else:
                # if a timeout is specified then only a single alert is returned
                # if we have a timeout when we use BLPOP
                result = await rc.blpop(get_alert_queue(name), timeout=timeout)
                if result is None:
                    return []

                # this returns a tuple of results (key, item1)
                _, result = result
                return [result.decode()]

    async def i_get_alert_count(self, name: str) -> int:
        async with self.get_redis_connection() as rc:
            if not await rc.hexists(KEY_ALERT_SYSTEMS, name):
                raise UnknownAlertSystemError(name)

            return await rc.llen(get_alert_queue(name))

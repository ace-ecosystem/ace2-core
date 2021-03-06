# vim: ts=4:sw=4:et:cc=120
#
#
#

from typing import Optional, Union

from ace import coreapi
from ace.exceptions import MissingEncryptionSettingsError


class AuthenticationBaseInterface:
    @coreapi
    async def create_api_key(
        self, name: str, description: Optional[str] = None, is_admin: Optional[bool] = False
    ) -> str:
        """Creates a new api_key. Returns the newly created api_key."""
        if not self.encryption_settings:
            raise MissingEncryptionSettingsError()

        return await self.i_create_api_key(name, description, is_admin)

    async def i_create_api_key(self, name: str, description: Optional[str] = None) -> Union[str, None]:
        raise NotImplementedError()

    @coreapi
    async def delete_api_key(self, name: str) -> bool:
        """Deletes the given api key. Returns True if the key was deleted, False otherwise."""
        if not self.encryption_settings:
            raise MissingEncryptionSettingsError()

        return await self.i_delete_api_key(name)

    async def i_delete_api_key(self, name: str) -> bool:
        raise NotImplementedError()

    @coreapi
    async def verify_api_key(self, api_key: str, is_admin: Optional[bool] = False) -> bool:
        """Returns True if the given api key is valid, False otherwise. If
        is_admin is True then the api_key must also be an admin key to pass
        verification."""
        return await self.i_verify_api_key(api_key, is_admin)

    async def i_verify_api_key(self, api_key: str) -> bool:
        raise NotImplementedError()

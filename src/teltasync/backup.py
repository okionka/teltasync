"""Configuration backup and restore endpoint bindings for the Teltonika API.

403 Forbidden on backup endpoints typically means the API user lacks
the required role — ensure the router user has 'admin' access level.
"""
import io
import logging
from typing import BinaryIO

import aiohttp

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel

_LOGGER = logging.getLogger(__name__)

# Export paths tried in order
_EXPORT_PATHS = [
    "system/config/export",
    "system/config",
    "system/backup",
    "system/configuration/backup",
    "system/settings/export",
]

# Import / restore paths
_IMPORT_PATHS = [
    "system/config/import",
    "system/config/restore",
    "system/restore",
    "system/configuration/restore",
    "system/settings/import",
]


class BackupResult(TeltasyncBaseModel):
    pass


class Backup:
    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def export_config(self) -> bytes:
        """
        Download router configuration as binary archive.

        Raises PermissionError on 403 (insufficient API user privileges).
        Raises RuntimeError when no compatible endpoint is found.
        """
        for path in _EXPORT_PATHS:
            try:
                async with await self.auth.request("GET", path) as resp:
                    if resp.status == 404:
                        _LOGGER.debug("Backup path not found: %s", path)
                        continue
                    if resp.status == 403:
                        raise PermissionError(
                            f"Access denied to backup endpoint '{path}'. "
                            "Ensure the API user has admin privileges on the router: "
                            "System → Administration → Users → set role to 'admin'."
                        )
                    resp.raise_for_status()
                    data = await resp.read()
                    _LOGGER.info("Config exported via %s (%d bytes)", path, len(data))
                    return data
            except PermissionError:
                raise
            except aiohttp.ClientResponseError as err:
                if err.status == 404:
                    continue
                _LOGGER.warning("Backup path %s error: %s %s", path, err.status, err.message)

        raise RuntimeError(
            f"No backup endpoint available. Tried: {', '.join(_EXPORT_PATHS)}. "
            "Check that Modbus/API is enabled under Services → API on the router."
        )

    async def import_config(self, data: bytes | BinaryIO) -> ApiResponse[BackupResult]:
        """Upload configuration backup to restore router settings."""
        if hasattr(data, "read"):
            raw = data.read()
        else:
            raw = data

        for path in _IMPORT_PATHS:
            try:
                form = aiohttp.FormData()
                form.add_field(
                    "file",
                    io.BytesIO(raw),
                    filename="config.tar.gz",
                    content_type="application/octet-stream",
                )
                async with await self.auth.request("POST", path, data=form) as resp:
                    if resp.status == 404:
                        continue
                    if resp.status == 403:
                        raise PermissionError(
                            f"Access denied to restore endpoint '{path}'. "
                            "Ensure the API user has admin privileges."
                        )
                    resp.raise_for_status()
                    json_response = await resp.json()
                    return ApiResponse[BackupResult](**json_response)
            except PermissionError:
                raise
            except aiohttp.ClientResponseError as err:
                if err.status == 404:
                    continue
                _LOGGER.warning("Restore path %s error: %s", path, err)

        raise RuntimeError(
            f"No restore endpoint available. Tried: {', '.join(_IMPORT_PATHS)}."
        )

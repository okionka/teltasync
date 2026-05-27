"""Configuration backup and restore endpoint bindings for the Teltonika API."""

import io
from typing import BinaryIO

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel


class BackupResult(TeltasyncBaseModel):
    """Minimal response wrapper for backup operations."""


class Backup:
    """API wrapper for /system/config backup/restore endpoints."""

    # Endpoint paths (tried in order for firmware compatibility)
    _EXPORT_PATHS = [
        "system/config/export",
        "system/configuration/export",
        "system/backup",
    ]
    _IMPORT_PATHS = [
        "system/config/import",
        "system/configuration/import",
        "system/restore",
    ]

    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def export_config(self) -> bytes:
        """
        Download the router configuration as a binary archive.

        Returns raw bytes (typically a .tar.gz or .bin file).
        Raises RuntimeError when no compatible endpoint is found.
        """
        import aiohttp

        for path in self._EXPORT_PATHS:
            try:
                async with await self.auth.request("GET", path) as resp:
                    if resp.status == 404:
                        continue
                    resp.raise_for_status()
                    return await resp.read()
            except aiohttp.ClientResponseError as err:
                if err.status == 404:
                    continue
                raise

        raise RuntimeError(
            "No backup endpoint found — "
            f"tried: {', '.join(self._EXPORT_PATHS)}"
        )

    async def import_config(self, data: bytes | BinaryIO) -> ApiResponse[BackupResult]:
        """
        Upload a configuration archive to restore router settings.

        Args:
            data: Raw bytes or file-like object containing the backup archive.

        Returns:
            ApiResponse indicating success or failure.
        """
        import aiohttp

        if hasattr(data, "read"):
            raw = data.read()
        else:
            raw = data

        form = aiohttp.FormData()
        form.add_field(
            "file",
            io.BytesIO(raw),
            filename="config.tar.gz",
            content_type="application/octet-stream",
        )

        for path in self._IMPORT_PATHS:
            try:
                async with await self.auth.request(
                    "POST", path, data=form
                ) as resp:
                    if resp.status == 404:
                        continue
                    resp.raise_for_status()
                    json_response = await resp.json()
                    return ApiResponse[BackupResult](**json_response)
            except aiohttp.ClientResponseError as err:
                if err.status == 404:
                    continue
                raise

        raise RuntimeError(
            "No restore endpoint found — "
            f"tried: {', '.join(self._IMPORT_PATHS)}"
        )

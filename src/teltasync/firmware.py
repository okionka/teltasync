"""Firmware status and update endpoint bindings for the Teltonika API.

Based on RUTX50 WebUI: System → Firmware → Update Firmware
Fields observed:
  Current: fw_version, build_date, modem_fw, kernel_version
  Available: fw_version (from server check)
"""

import logging
from typing import Any

import aiohttp
from pydantic import AliasChoices, Field, field_validator

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel

_LOGGER = logging.getLogger(__name__)

# Firmware info paths — tried in order
_STATUS_PATHS = [
    "system/firmware",
    "system/firmware/status",
    "system/device/firmware",
    "system/update/status",
]

# Firmware server-check paths
_CHECK_PATHS = [
    "system/firmware/check",
    "system/firmware/actions/check",
    "system/update/check",
]

# Firmware install paths
_INSTALL_PATHS = [
    "system/firmware/update",
    "system/firmware/actions/update",
    "system/firmware/actions/flash",
    "system/update/actions/install",
]


class CurrentFirmwareInfo(TeltasyncBaseModel):
    """Installed firmware details — matches RUTX50 WebUI 'Current firmware information'."""

    fw_version: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "fw_version", "fwVersion", "version", "firmware_version",
            "firmwareVersion", "current_version",
        ),
        description="Installed firmware version, e.g. RUTX_R_00.07.10.2",
    )
    build_date: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "build_date", "buildDate", "fw_build_date", "fwBuildDate",
        ),
        description="Firmware build date",
    )
    modem_fw: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "modem_fw", "modemFw", "internal_modem_firmware_version",
            "modem_firmware", "modemFirmware",
        ),
        description="Internal modem firmware version",
    )
    kernel_version: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "kernel_version", "kernelVersion", "kernel",
        ),
        description="Linux kernel version",
    )


class AvailableFirmwareInfo(TeltasyncBaseModel):
    """Server-side available firmware — matches RUTX50 WebUI 'Firmware available on server'."""

    fw_version: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "fw_version", "fwVersion", "version", "firmware_version",
            "firmwareVersion", "latest_version", "latestVersion",
        ),
        description="Available firmware version on server, e.g. RUTX_R_00.07.22.3",
    )
    modem_update_available: bool | None = Field(
        None,
        validation_alias=AliasChoices(
            "modem_update_available", "modemUpdateAvailable",
            "internal_modem", "internalModem",
        ),
        description="Whether a modem firmware update is also available",
    )
    url: str | None = Field(None, description="Firmware download URL")
    size: int | None = Field(None, description="File size in bytes")
    changelog: str | None = Field(None, description="Release notes / changelog")

    @field_validator("modem_update_available", mode="before")
    @classmethod
    def _parse_modem_update(cls, v: Any) -> bool | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        s = str(v).lower()
        return s in ("true", "1", "update available", "available")


class FirmwareStatus(TeltasyncBaseModel):
    """Combined firmware status — installed version + available update."""

    current: CurrentFirmwareInfo | None = None
    update: AvailableFirmwareInfo | None = None

    @property
    def installed_version(self) -> str | None:
        return self.current.fw_version if self.current else None

    @property
    def latest_version(self) -> str | None:
        return self.update.fw_version if self.update else None

    @property
    def update_available(self) -> bool:
        iv = self.installed_version
        lv = self.latest_version
        return bool(lv and iv and lv != iv)


async def _try_paths(
    auth: Auth,
    paths: list[str],
    method: str = "GET",
    **kwargs: Any,
) -> dict | None:
    """Try a list of API paths, return the first successful JSON response."""
    for path in paths:
        try:
            async with await auth.request(method, path, **kwargs) as resp:
                if resp.status == 404:
                    continue
                if resp.status >= 400:
                    _LOGGER.debug("Firmware path %s returned %s", path, resp.status)
                    continue
                json_response = await resp.json()
                _LOGGER.debug("Firmware path %s OK: %s", path, json_response)
                return json_response
        except aiohttp.ClientResponseError as err:
            if err.status == 404:
                continue
            _LOGGER.debug("Firmware path %s error: %s", path, err)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Firmware path %s exception: %s", path, err)
    return None


class Firmware:
    """API wrapper for firmware status and update endpoints."""

    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def get_status(self) -> ApiResponse[FirmwareStatus]:
        """
        Return installed firmware info and available update.

        Tries multiple paths for firmware compatibility.
        Falls back to an empty FirmwareStatus on failure so the
        Update entity can still show the installed version from system_info.
        """
        raw = await _try_paths(self.auth, _STATUS_PATHS)
        if raw is None:
            return ApiResponse[FirmwareStatus](
                success=False,
                data=FirmwareStatus(),
            )

        data = raw.get("data", raw)

        # The API may return a flat dict or a nested {current: {}, update: {}}
        if isinstance(data, dict):
            # Flat structure: fw_version at top level
            if "fw_version" in data or "fwVersion" in data or "version" in data:
                current = CurrentFirmwareInfo(**data)
                # Look for update info nested or at same level
                update_raw = data.get("update") or data.get("server") or data.get("available")
                update = AvailableFirmwareInfo(**update_raw) if update_raw else None
                status = FirmwareStatus(current=current, update=update)
            else:
                # Nested structure: {current: {...}, update: {...}}
                current_raw = data.get("current") or data.get("installed")
                update_raw  = data.get("update")  or data.get("available") or data.get("server")
                current = CurrentFirmwareInfo(**current_raw) if current_raw else None
                update  = AvailableFirmwareInfo(**update_raw) if update_raw else None
                status  = FirmwareStatus(current=current, update=update)
        else:
            status = FirmwareStatus()

        return ApiResponse[FirmwareStatus](success=True, data=status)

    async def check_update(self) -> ApiResponse[AvailableFirmwareInfo]:
        """Trigger a server-side firmware update check."""
        raw = await _try_paths(self.auth, _CHECK_PATHS, method="POST")
        if raw is None:
            raw = await _try_paths(self.auth, _CHECK_PATHS, method="GET")
        if raw is None:
            return ApiResponse[AvailableFirmwareInfo](success=False, data=None)

        data = raw.get("data", raw)
        if isinstance(data, dict):
            info = AvailableFirmwareInfo(**data)
            return ApiResponse[AvailableFirmwareInfo](success=True, data=info)
        return ApiResponse[AvailableFirmwareInfo](success=False, data=None)

    async def install_update(self) -> ApiResponse[dict]:
        """Start firmware update installation from server."""
        raw = await _try_paths(self.auth, _INSTALL_PATHS, method="POST")
        if raw is None:
            return ApiResponse[dict](success=False, data=None)
        return ApiResponse[dict](success=True, data=raw.get("data", raw))

# Backward-compatible alias
FirmwareUpdateInfo = AvailableFirmwareInfo

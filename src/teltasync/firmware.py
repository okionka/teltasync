"""Firmware status and update endpoint bindings for the Teltonika API.

RUTX50 WebUI: System → Firmware → Update Firmware
  Current:   fw_version=RUTX_R_00.07.10.2, build_date, modem_fw, kernel_version
  Available: fw_version=RUTX_R_00.07.22.3  (from server check)
"""
import logging
from typing import Any

import aiohttp
from pydantic import AliasChoices, Field, field_validator

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CurrentFirmwareInfo(TeltasyncBaseModel):
    fw_version: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "fw_version", "fwVersion", "version",
            "firmware_version", "firmwareVersion", "current_version",
        ),
    )
    build_date: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "build_date", "buildDate", "fw_build_date", "fwBuildDate",
        ),
    )
    modem_fw: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "modem_fw", "modemFw", "internal_modem_firmware_version",
            "modem_firmware", "modemFirmware",
        ),
    )
    kernel_version: str | None = Field(
        None,
        validation_alias=AliasChoices("kernel_version", "kernelVersion", "kernel"),
    )


class AvailableFirmwareInfo(TeltasyncBaseModel):
    fw_version: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "fw_version", "fwVersion", "version",
            "firmware_version", "firmwareVersion",
            "latest_version", "latestVersion",
        ),
    )
    modem_update_available: bool | None = Field(
        None,
        validation_alias=AliasChoices(
            "modem_update_available", "modemUpdateAvailable",
            "internal_modem", "internalModem",
        ),
    )
    url: str | None = None
    changelog: str | None = None

    @field_validator("modem_update_available", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> bool | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("true", "1", "update available", "available")


# Backward-compatible alias
FirmwareUpdateInfo = AvailableFirmwareInfo


class FirmwareStatus(TeltasyncBaseModel):
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
        iv, lv = self.installed_version, self.latest_version
        return bool(lv and iv and lv != iv)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _try_paths(
    auth: Auth, paths: list[str], method: str = "GET", **kwargs: Any
) -> dict | None:
    for path in paths:
        try:
            async with await auth.request(method, path, **kwargs) as resp:
                if resp.status == 404:
                    continue
                if resp.status >= 400:
                    continue
                data = await resp.json()
                _LOGGER.debug("Firmware %s %s → %s", method, path, data)
                return data
        except aiohttp.ClientResponseError as err:
            if err.status == 404:
                continue
            _LOGGER.debug("Firmware %s %s error: %s", method, path, err)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Firmware %s %s exc: %s", method, path, err)
    return None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class Firmware:
    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def get_current(self) -> CurrentFirmwareInfo | None:
        """GET current firmware info from the router."""
        raw = await _try_paths(self.auth, [
            "system/firmware",
            "system/firmware/status",
            "system/device/firmware",
        ])
        if not raw:
            return None
        data = raw.get("data", raw)
        if not isinstance(data, dict):
            return None
        # Handle nested {current: {...}} or flat
        block = data.get("current") or data.get("installed") or data
        try:
            info = CurrentFirmwareInfo(**block)
            if info.fw_version:
                return info
        except Exception:  # noqa: BLE001
            pass
        return None

    async def check_update(self) -> AvailableFirmwareInfo | None:
        """Ask the router to check for a newer firmware on the server."""
        raw = await _try_paths(self.auth, [
            "system/firmware/check",
            "system/firmware/actions/check",
            "system/update/check",
        ], method="POST")
        if raw is None:
            # Some firmware uses GET for the check
            raw = await _try_paths(self.auth, [
                "system/firmware/check",
                "system/firmware/latest",
                "system/update/latest",
            ], method="GET")
        if not raw:
            return None
        data = raw.get("data", raw)
        if not isinstance(data, dict):
            return None
        block = data.get("update") or data.get("available") or data.get("server") or data
        try:
            info = AvailableFirmwareInfo(**block)
            if info.fw_version:
                return info
        except Exception:  # noqa: BLE001
            pass
        return None

    async def get_status(self) -> ApiResponse[FirmwareStatus]:
        """Combined: current info + update check."""
        current = await self.get_current()
        update  = await self.check_update()
        status  = FirmwareStatus(current=current, update=update)
        return ApiResponse[FirmwareStatus](success=True, data=status)

    async def install_update(self) -> ApiResponse[dict]:
        """Trigger OTA firmware installation from server."""
        raw = await _try_paths(self.auth, [
            "system/firmware/update",
            "system/firmware/actions/update",
            "system/firmware/actions/flash",
            "system/update/actions/install",
        ], method="POST")
        if raw is None:
            return ApiResponse[dict](success=False, data=None)
        return ApiResponse[dict](success=True, data=raw.get("data", raw))

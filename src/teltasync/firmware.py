"""Firmware status and update endpoint bindings for the Teltonika API."""

from pydantic import Field

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel


class FirmwareInfo(TeltasyncBaseModel):
    """Current firmware version details."""

    version: str | None = Field(None, description="Installed firmware version")
    build_date: str | None = Field(None, description="Firmware build date")
    channel: str | None = Field(None, description="Update channel: 'stable', 'beta'")


class FirmwareUpdateInfo(TeltasyncBaseModel):
    """Available firmware update from the update server."""

    version: str | None = Field(None, description="Available firmware version")
    url: str | None = Field(None, description="Download URL")
    size: int | None = Field(None, description="File size in bytes")
    release_notes: str | None = Field(None, description="Release notes")
    changelog: str | None = Field(None, description="Changelog text")


class FirmwareStatus(TeltasyncBaseModel):
    """Combined firmware status — installed version and available update."""

    current: FirmwareInfo | None = None
    update: FirmwareUpdateInfo | None = None

    @property
    def update_available(self) -> bool:
        """Return True when a newer version is available."""
        return (
            self.update is not None
            and self.update.version is not None
            and self.update.version != (self.current.version if self.current else None)
        )


class Firmware:
    """API wrapper for /system/firmware endpoints."""

    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def get_status(self) -> ApiResponse[FirmwareStatus]:
        """Return installed firmware info and available update."""
        async with await self.auth.request(
            "GET", "system/firmware/status"
        ) as resp:
            json_response = await resp.json()
            return ApiResponse[FirmwareStatus](**json_response)

    async def check_update(self) -> ApiResponse[FirmwareUpdateInfo]:
        """Trigger an update check and return available firmware info."""
        async with await self.auth.request(
            "POST", "system/firmware/check"
        ) as resp:
            json_response = await resp.json()
            return ApiResponse[FirmwareUpdateInfo](**json_response)

    async def install_update(self) -> ApiResponse[dict]:
        """Start firmware update installation."""
        async with await self.auth.request(
            "POST", "system/firmware/update"
        ) as resp:
            json_response = await resp.json()
            return ApiResponse[dict](**json_response)

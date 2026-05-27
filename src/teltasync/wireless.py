"""Wireless interface endpoint bindings for the Teltonika API."""

from pydantic import Field

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel


class WirelessInterface(TeltasyncBaseModel):
    """A single wireless interface entry from /wireless/interfaces/status."""

    id: str | None = Field(None, description="Interface ID, e.g. 'wlan0'")
    ssid: str | None = Field(None, description="SSID broadcast name")
    enabled: bool | None = Field(None, description="Interface enabled state")
    mode: str | None = Field(None, description="Mode: 'ap', 'sta' etc.")
    band: str | None = Field(None, description="Frequency band: '2g', '5g'")
    channel: int | None = Field(None, description="Radio channel")
    clients: int | None = Field(None, description="Number of connected clients")
    encryption: str | None = Field(None, description="Encryption type")


class Wireless:
    """API wrapper for /wireless endpoints."""

    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def get_interfaces(self) -> ApiResponse[list[WirelessInterface]]:
        """Return status of all wireless interfaces."""
        async with await self.auth.request(
            "GET", "wireless/interfaces/status"
        ) as resp:
            json_response = await resp.json()
            return ApiResponse[list[WirelessInterface]](**json_response)

    async def set_enabled(self, interface_id: str, enabled: bool) -> ApiResponse[dict]:
        """Enable or disable a wireless interface."""
        async with await self.auth.request(
            "PUT",
            f"wireless/interfaces/{interface_id}",
            json={"enabled": enabled},
        ) as resp:
            json_response = await resp.json()
            return ApiResponse[dict](**json_response)

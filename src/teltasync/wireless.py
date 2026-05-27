"""Wireless interface endpoint bindings for the Teltonika API."""

import logging
from typing import Any

from pydantic import AliasChoices, Field, field_validator

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel

_LOGGER = logging.getLogger(__name__)


class WirelessInterface(TeltasyncBaseModel):
    """A single wireless interface entry from /wireless/interfaces/status."""

    id: str | None = Field(
        None,
        validation_alias=AliasChoices("id", "name", "ifname", "interface"),
        description="Interface ID, e.g. 'wlan0'",
    )
    ssid: str | None = Field(None)
    enabled: bool | None = Field(
        None,
        validation_alias=AliasChoices("enabled", "is_enabled", "status", "active"),
    )
    mode: str | None = Field(None)
    band: str | None = Field(
        None,
        validation_alias=AliasChoices("band", "frequency", "freq", "radio"),
        description="Frequency band: '2g', '5g', '2.4ghz', '5ghz'",
    )
    channel: int | None = Field(None)
    clients: int | None = Field(
        None,
        validation_alias=AliasChoices("clients", "connected_clients", "stations"),
    )
    encryption: str | None = Field(None)

    @field_validator("enabled", mode="before")
    @classmethod
    def _parse_enabled(cls, v: Any) -> bool | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, int):
            return bool(v)
        s = str(v).lower()
        if s in ("true", "1", "enabled", "up", "on", "active"):
            return True
        if s in ("false", "0", "disabled", "down", "off"):
            return False
        return None

    @property
    def band_label(self) -> str:
        """Human-readable band label: '2.4 GHz' or '5 GHz'."""
        b = (self.band or "").lower()
        if "5" in b:
            return "5 GHz"
        if "2" in b or "24" in b:
            return "2.4 GHz"
        # Infer from id: wlan0=2.4GHz, wlan1=5GHz (common convention)
        if self.id:
            idx = "".join(c for c in self.id if c.isdigit())
            if idx == "0":
                return "2.4 GHz"
            if idx == "1":
                return "5 GHz"
        return self.id or "WiFi" 


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
        """Enable or disable a wireless interface. Tries PUT and POST with RutOS envelope."""
        candidates = [
            ("PUT",  f"wireless/interfaces/{interface_id}",
             {"data": {"enabled": enabled}}),
            ("PUT",  f"wireless/interfaces/{interface_id}",
             {"enabled": enabled}),
            ("POST", f"wireless/interfaces/{interface_id}/actions/enable"
             if enabled else f"wireless/interfaces/{interface_id}/actions/disable",
             {"data": {}}),
        ]
        import aiohttp
        for method, path, body in candidates:
            try:
                async with await self.auth.request(method, path, json=body) as resp:
                    _LOGGER.warning(
                        "WiFi set_enabled: %s %s body=%s → HTTP %s",
                        method, path, body, resp.status,
                    )
                    if resp.status in (404, 501, 405):
                        continue
                    resp.raise_for_status()
                    return ApiResponse[dict](**await resp.json())
            except aiohttp.ClientResponseError as err:
                if err.status in (404, 501, 405):
                    continue
                raise
        raise RuntimeError(f"Cannot toggle WiFi interface {interface_id}")

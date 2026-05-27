"""GPS endpoint bindings for the Teltonika API."""

from pydantic import Field, field_validator

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel


class GpsStatusData(TeltasyncBaseModel):
    """GPS status data returned by /gps/status."""

    enabled: bool | None = Field(None, description="GPS enabled state")
    fix: bool | None = Field(None, description="GPS fix acquired")
    fix_status: str | None = Field(
        None, description="Human-readable fix status, e.g. 'Fix' / 'No fix'"
    )
    latitude: float | None = Field(None, description="Latitude in decimal degrees")
    longitude: float | None = Field(None, description="Longitude in decimal degrees")
    altitude: float | None = Field(None, description="Altitude in metres")
    speed: float | None = Field(None, description="Speed in km/h")
    num_satellites: int | None = Field(None, description="Number of visible satellites")
    accuracy: float | None = Field(None, description="Horizontal accuracy (HDOP)")
    datetime: str | None = Field(
        None, description="UTC datetime string (YYYY-MM-DD hh:mm:ss)"
    )
    date: str | None = Field(None, description="UTC date (YYYY-MM-DD)")
    time: str | None = Field(None, description="UTC time (hh:mm:ss)")

    @field_validator("latitude", "longitude", "altitude", "speed", "accuracy", mode="before")
    @classmethod
    def _parse_float(cls, v: object) -> float | None:
        if v is None or v == "" or v == "N/A":
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    @field_validator("num_satellites", mode="before")
    @classmethod
    def _parse_int(cls, v: object) -> int | None:
        if v is None or v == "" or v == "N/A":
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None


class Gps:
    """API wrapper for /gps endpoints."""

    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def get_status(self) -> ApiResponse[GpsStatusData]:
        """Return current GPS fix and position data."""
        async with await self.auth.request("GET", "gps/status") as resp:
            json_response = await resp.json()
            return ApiResponse[GpsStatusData](**json_response)

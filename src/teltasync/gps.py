"""GPS endpoint bindings for the Teltonika API."""

import logging
from typing import Any

import aiohttp
from pydantic import AliasChoices, Field, field_validator, model_validator

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel

_LOGGER = logging.getLogger(__name__)

# Firmware-version-dependent paths tried in order
_GPS_PATHS = [
    "gps/status",
    "gps/position",
    "gps",
]


def _to_float(v: Any) -> float | None:
    if v is None or v == "" or v == "N/A" or v == "unknown":
        return None
    try:
        f = float(v)
        return None if f == 0.0 else f   # 0.0 = no fix placeholder
    except (ValueError, TypeError):
        return None


def _to_int(v: Any) -> int | None:
    if v is None or v == "" or v == "N/A" or v == "unknown":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


class GpsStatusData(TeltasyncBaseModel):
    """GPS status data returned by the GPS endpoint.

    Field aliases cover the varying naming conventions across RutOS firmware
    versions (full names, short names, camelCase from alias_generator).
    """

    enabled: bool | None = Field(None, description="GPS enabled state")

    fix: bool | None = Field(
        None,
        validation_alias=AliasChoices("fix", "hasFix", "has_fix", "fixAcquired"),
        description="GPS fix acquired",
    )
    fix_status: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "fix_status", "fixStatus", "status", "fixState", "fix_state"
        ),
        description="Human-readable fix status, e.g. 'Fix' / 'No fix'",
    )

    latitude: float | None = Field(
        None,
        validation_alias=AliasChoices("latitude", "lat", "Lat", "latitude_d"),
        description="Latitude in decimal degrees",
    )
    longitude: float | None = Field(
        None,
        validation_alias=AliasChoices(
            "longitude", "lon", "lng", "Long", "longitude_d"
        ),
        description="Longitude in decimal degrees",
    )
    altitude: float | None = Field(
        None,
        validation_alias=AliasChoices("altitude", "alt", "Alt", "elevation"),
        description="Altitude in metres",
    )
    speed: float | None = Field(
        None,
        validation_alias=AliasChoices("speed", "spd", "groundSpeed", "ground_speed"),
        description="Speed in km/h",
    )
    num_satellites: int | None = Field(
        None,
        validation_alias=AliasChoices(
            "num_satellites", "numSatellites", "satellites",
            "sats", "numSat", "num_sat",
        ),
        description="Number of visible satellites",
    )
    accuracy: float | None = Field(
        None,
        validation_alias=AliasChoices("accuracy", "hdop", "hDop", "h_dop", "pdop"),
        description="Horizontal accuracy (HDOP)",
    )
    datetime: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "datetime", "dateTime", "date_time", "timestamp", "utc_datetime"
        ),
        description="UTC datetime string (YYYY-MM-DD hh:mm:ss)",
    )
    date: str | None = Field(
        None,
        validation_alias=AliasChoices("date", "utc_date", "gpsDate"),
        description="UTC date (YYYY-MM-DD)",
    )
    time: str | None = Field(
        None,
        validation_alias=AliasChoices("time", "utc_time", "gpsTime"),
        description="UTC time (hh:mm:ss)",
    )

    @field_validator("latitude", "longitude", "altitude", "speed", "accuracy", mode="before")
    @classmethod
    def _parse_float(cls, v: Any) -> float | None:
        return _to_float(v)

    @field_validator("num_satellites", mode="before")
    @classmethod
    def _parse_int(cls, v: Any) -> int | None:
        return _to_int(v)

    @field_validator("fix", mode="before")
    @classmethod
    def _parse_fix(cls, v: Any) -> bool | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, int):
            return bool(v)
        s = str(v).lower()
        if s in ("true", "1", "fix", "fixed", "yes", "acquired"):
            return True
        if s in ("false", "0", "no fix", "nofix", "no", "none", ""):
            return False
        return None

    @model_validator(mode="after")
    def _derive_fix_status(self) -> "GpsStatusData":
        """Derive fix_status from fix bool if not provided by API."""
        if self.fix_status is None and self.fix is not None:
            self.fix_status = "Fix" if self.fix else "No fix"
        return self


class Gps:
    """API wrapper for /gps endpoints."""

    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def get_status(self) -> ApiResponse[GpsStatusData]:
        """
        Return current GPS fix and position data.
        Tries multiple endpoint paths for firmware compatibility.
        """
        last_err: Exception | None = None

        for path in _GPS_PATHS:
            try:
                async with await self.auth.request("GET", path) as resp:
                    if resp.status == 404:
                        continue
                    resp.raise_for_status()
                    json_response = await resp.json()
                    _LOGGER.debug("GPS response from %s: %s", path, json_response)
                    return ApiResponse[GpsStatusData](**json_response)
            except aiohttp.ClientResponseError as err:
                if err.status == 404:
                    continue
                last_err = err
            except Exception as err:  # noqa: BLE001
                last_err = err

        if last_err:
            raise last_err

        # All paths returned 404 — return empty response
        return ApiResponse[GpsStatusData](success=False, data=None)

"""GPS endpoint bindings for the Teltonika API."""

import logging
from typing import Any

import aiohttp
from pydantic import AliasChoices, Field, field_validator, model_validator

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel

_LOGGER = logging.getLogger(__name__)

# All known GPS endpoint paths across RutOS firmware versions — tried in order
_GPS_PATHS = [
    "gps/position/status",        # RUTX50 RutOS 7.x primary
    "gps/status",                 # common
    "gps/position",               # alternative
    "gps",                        # bare endpoint
    "gps/position/coordinates",   # RUT956 possible path
    "device/gps/status",          # legacy
    "tracking/position",          # RUT956/TRB series
]


def _to_float(v: Any) -> float | None:
    """Parse float, return None only for truly empty values — NOT for 0.0."""
    if v is None or v == "" or v == "N/A" or v == "unknown" or v == "n/a":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _to_int(v: Any) -> int | None:
    if v is None or v == "" or v == "N/A" or v == "unknown":
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


class GpsStatusData(TeltasyncBaseModel):
    """GPS status — AliasChoices covers all known RutOS field name variants."""

    enabled: bool | None = Field(None)

    fix: bool | None = Field(
        None,
        validation_alias=AliasChoices(
            "fix", "hasFix", "has_fix", "fixAcquired", "fix_acquired",
        ),
    )
    fix_status: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "fix_status", "fixStatus", "status", "fixState", "fix_state",
            "fixQuality", "fix_quality",
        ),
    )

    latitude: float | None = Field(
        None,
        validation_alias=AliasChoices(
            "latitude", "lat", "Lat", "latitude_d", "lat_d",
        ),
    )
    longitude: float | None = Field(
        None,
        validation_alias=AliasChoices(
            "longitude", "lon", "lng", "Long", "longitude_d", "lon_d",
        ),
    )
    altitude: float | None = Field(
        None,
        validation_alias=AliasChoices(
            "altitude", "alt", "Alt", "elevation", "height",
        ),
    )
    speed: float | None = Field(
        None,
        validation_alias=AliasChoices(
            "speed", "spd", "groundSpeed", "ground_speed", "kmh",
        ),
    )
    num_satellites: int | None = Field(
        None,
        validation_alias=AliasChoices(
            "num_satellites", "numSatellites", "satellites",
            "sats", "numSat", "num_sat", "sat_count",
        ),
    )
    accuracy: float | None = Field(
        None,
        validation_alias=AliasChoices(
            "accuracy", "hdop", "hDop", "h_dop", "pdop",
            "horizontal_accuracy", "horizontalAccuracy",
        ),
    )
    datetime: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "datetime", "dateTime", "date_time",
            "timestamp", "utc_datetime", "time",
        ),
    )
    date: str | None = Field(
        None,
        validation_alias=AliasChoices("date", "utc_date", "gpsDate"),
    )

    @field_validator(
        "latitude", "longitude", "altitude", "speed", "accuracy", mode="before"
    )
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
        if s in ("true", "1", "fix", "fixed", "yes", "acquired", "3d", "2d"):
            return True
        if s in ("false", "0", "no fix", "nofix", "no", "none", ""):
            return False
        return None

    @model_validator(mode="after")
    def _derive_fix_status(self) -> "GpsStatusData":
        if self.fix_status is None and self.fix is not None:
            self.fix_status = "Fix" if self.fix else "No fix"
        return self


class Gps:
    """API wrapper for GPS endpoints."""

    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def get_status(self) -> ApiResponse[GpsStatusData]:
        """
        Fetch GPS status. Tries all known endpoint paths in order.
        Logs the successful path and raw response at WARNING level for debugging.
        """
        last_err: Exception | None = None

        for path in _GPS_PATHS:
            try:
                async with await self.auth.request("GET", path) as resp:
                    if resp.status == 404:
                        _LOGGER.debug("GPS path not found: %s", path)
                        continue
                    resp.raise_for_status()
                    json_response = await resp.json()
                    _LOGGER.warning(
                        "GPS endpoint hit: %s | raw response: %s",
                        path, json_response,
                    )
                    return ApiResponse[GpsStatusData](**json_response)
            except aiohttp.ClientResponseError as err:
                if err.status == 404:
                    continue
                _LOGGER.warning("GPS path %s error: %s", path, err)
                last_err = err
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("GPS path %s exception: %s", path, err)
                last_err = err

        _LOGGER.warning(
            "GPS: no endpoint responded from %s — last error: %s",
            _GPS_PATHS, last_err,
        )
        return ApiResponse[GpsStatusData](success=False, data=None)

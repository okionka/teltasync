"""Data usage endpoint bindings for the Teltonika API."""
import logging
from typing import Any

import aiohttp
from pydantic import AliasChoices, Field, field_validator

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel

_LOGGER = logging.getLogger(__name__)

# Paths tried in order per modem
_MODEM_PATHS = [
    "modems/{id}/data_usage",           # returns data if available
    "modems/{id}/statistics",           # alternative stats endpoint
    "network/mobile/statistics",        # general mobile stats
    "modems/{id}/mobile_data",          # another variant
    "network/mobile/data_limit",        # fallback (may be 403)
    "mobile/data_usage",                # legacy fallback
]


def _to_mb(v: Any) -> int | None:
    if v is None or v == "" or v == "N/A":
        return None
    try:
        val = int(float(str(v)))
        # If value > 100 000, assume bytes → convert to MB
        return val // (1024 * 1024) if val > 100_000 else val
    except (ValueError, TypeError):
        return None


class SimUsageData(TeltasyncBaseModel):
    sim: int | None = None

    rx_today: int | None = Field(None, validation_alias=AliasChoices("rx_today","received_today","rx_day","rxToday"))
    tx_today: int | None = Field(None, validation_alias=AliasChoices("tx_today","sent_today","tx_day","txToday"))
    rx_last_24h: int | None = Field(None, validation_alias=AliasChoices("rx_last_24h","received_last_24h","rx_24h","rxLast24h"))
    tx_last_24h: int | None = Field(None, validation_alias=AliasChoices("tx_last_24h","sent_last_24h","tx_24h","txLast24h"))
    rx_week: int | None = Field(None, validation_alias=AliasChoices("rx_week","received_week","rx_this_week","rxWeek"))
    tx_week: int | None = Field(None, validation_alias=AliasChoices("tx_week","sent_week","tx_this_week","txWeek"))
    rx_last_7d: int | None = Field(None, validation_alias=AliasChoices("rx_last_7d","received_last_7d","rx_7d","rxLast7d"))
    tx_last_7d: int | None = Field(None, validation_alias=AliasChoices("tx_last_7d","sent_last_7d","tx_7d","txLast7d"))
    rx_month: int | None = Field(None, validation_alias=AliasChoices("rx_month","received_month","rx_this_month","rxMonth"))
    tx_month: int | None = Field(None, validation_alias=AliasChoices("tx_month","sent_month","tx_this_month","txMonth"))
    rx_last_30d: int | None = Field(None, validation_alias=AliasChoices("rx_last_30d","received_last_30d","rx_30d","rxLast30d"))
    tx_last_30d: int | None = Field(None, validation_alias=AliasChoices("tx_last_30d","sent_last_30d","tx_30d","txLast30d"))
    rx_last_month: int | None = Field(None, validation_alias=AliasChoices("rx_last_month","received_last_month","rxLastMonth"))
    tx_last_month: int | None = Field(None, validation_alias=AliasChoices("tx_last_month","sent_last_month","txLastMonth"))
    rx_last_week: int | None = Field(None, validation_alias=AliasChoices("rx_last_week","received_last_week","rxLastWeek"))
    tx_last_week: int | None = Field(None, validation_alias=AliasChoices("tx_last_week","sent_last_week","txLastWeek"))

    @field_validator(
        "rx_today","tx_today","rx_last_24h","tx_last_24h",
        "rx_week","tx_week","rx_last_7d","tx_last_7d",
        "rx_month","tx_month","rx_last_30d","tx_last_30d",
        "rx_last_month","tx_last_month","rx_last_week","tx_last_week",
        mode="before",
    )
    @classmethod
    def _convert(cls, v: Any) -> int | None:
        return _to_mb(v)


class ModemDataUsage(TeltasyncBaseModel):
    modem_id: str = ""
    sim1: SimUsageData | None = None
    sim2: SimUsageData | None = None


def _parse_sim_block(raw: dict, sim_index: int) -> SimUsageData | None:
    if not raw:
        return None

    def _b(*keys: str) -> int | None:
        for k in keys:
            v = raw.get(k)
            if v is not None:
                return _to_mb(v)
        return None

    # Shape A: {"sim1": {...}, "sim2": {...}}
    block = raw.get(f"sim{sim_index}")

    # Shape C: {"1_rx_today": ..., "2_rx_today": ...}
    if block is None:
        prefix = f"{sim_index}_"
        extracted = {k[len(prefix):]: v for k, v in raw.items() if k.startswith(prefix)}
        block = extracted or None

    if not block:
        # Shape D: flat dict — try only for sim1
        if sim_index == 1 and any(
            k in raw for k in ("rx_today", "rxToday", "received_today")
        ):
            block = raw
        else:
            return None

    def _bb(*keys: str) -> int | None:
        for k in keys:
            v = block.get(k)
            if v is not None:
                return _to_mb(v)
        return None

    return SimUsageData(
        sim=sim_index,
        rx_today=_bb("rx_today","received_today","rxToday"),
        tx_today=_bb("tx_today","sent_today","txToday"),
        rx_last_24h=_bb("rx_last_24h","received_last_24h","rx_24h","rxLast24h"),
        tx_last_24h=_bb("tx_last_24h","sent_last_24h","tx_24h","txLast24h"),
        rx_week=_bb("rx_week","received_week","rxWeek"),
        tx_week=_bb("tx_week","sent_week","txWeek"),
        rx_last_7d=_bb("rx_last_7d","received_last_7d","rx_7d","rxLast7d"),
        tx_last_7d=_bb("tx_last_7d","sent_last_7d","tx_7d","txLast7d"),
        rx_month=_bb("rx_month","received_month","rxMonth"),
        tx_month=_bb("tx_month","sent_month","txMonth"),
        rx_last_30d=_bb("rx_last_30d","received_last_30d","rx_30d","rxLast30d"),
        tx_last_30d=_bb("tx_last_30d","sent_last_30d","tx_30d","txLast30d"),
        rx_last_month=_bb("rx_last_month","received_last_month","rxLastMonth"),
        tx_last_month=_bb("tx_last_month","sent_last_month","txLastMonth"),
        rx_last_week=_bb("rx_last_week","received_last_week","rxLastWeek"),
        tx_last_week=_bb("tx_last_week","sent_last_week","txLastWeek"),
    )


class DataUsage:
    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def get_modem_usage(self, modem_id: str) -> ModemDataUsage | None:
        for path_tpl in _MODEM_PATHS:
            path = path_tpl.format(id=modem_id)
            try:
                async with await self.auth.request("GET", path) as resp:
                    if resp.status == 404:
                        continue
                    resp.raise_for_status()
                    raw = await resp.json()
                    _LOGGER.warning(
                        "DataUsage path %s → %s", path, raw
                    )  # WARNING so it shows without debug mode
                    data = raw.get("data", raw)
                    if not data:
                        continue

                    # Shape B: list of per-SIM dicts
                    if isinstance(data, list):
                        sim_map: dict[int, dict] = {}
                        for item in data:
                            if isinstance(item, dict):
                                idx = item.get("sim") or item.get("sim_index")
                                if idx is not None:
                                    sim_map[int(idx)] = item
                        if sim_map:
                            data = {f"sim{k}": v for k, v in sim_map.items()}

                    if isinstance(data, dict):
                        # Skip responses that only contain status fields (no usage data)
                        usage_keys = {k for k in data if any(
                            w in k.lower() for w in
                            ("rx", "tx", "received", "sent", "bytes", "mb", "today",
                             "week", "month", "sim")
                        )}
                        if not usage_keys:
                            _LOGGER.debug(
                                "DataUsage %s: response has no usage data, keys=%s",
                                path, list(data.keys()),
                            )
                            continue
                        sim1 = _parse_sim_block(data, 1)
                        sim2 = _parse_sim_block(data, 2)
                        if sim1 or sim2:
                            return ModemDataUsage(
                                modem_id=modem_id, sim1=sim1, sim2=sim2
                            )
            except aiohttp.ClientResponseError as err:
                if err.status == 404:
                    continue
                _LOGGER.warning("DataUsage %s: %s", path, err)
            except Exception as err:
                _LOGGER.warning("DataUsage %s: %s", path, err)

        _LOGGER.warning(
            "DataUsage: no endpoint found for modem %s (tried %s)",
            modem_id, _MODEM_PATHS,
        )
        return None

"""Data usage endpoint bindings for the Teltonika API."""

from pydantic import Field, field_validator

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel

# Paths tried in order (firmware version dependent)
_PATHS = [
    "modems/{modem_id}/data_usage",      # preferred per-modem path
    "network/mobile/data_limit",          # legacy path
    "mobile/data_usage",                  # alternative
]


def _bytes_to_mb(v: object) -> int | None:
    """Convert raw value to MB. Treats values >10 000 as bytes."""
    if v is None or v == "" or v == "N/A":
        return None
    try:
        val = int(v)
        return val // (1024 * 1024) if val > 10_000 else val
    except (ValueError, TypeError):
        return None


class SimUsageData(TeltasyncBaseModel):
    """Data usage statistics for a single SIM card."""

    sim: int | None = Field(None, description="SIM index (1 or 2)")

    # ---- Today ----
    rx_today: int | None = Field(None, description="MB received today")
    tx_today: int | None = Field(None, description="MB sent today")

    # ---- Last 24 h ----
    rx_last_24h: int | None = Field(None, description="MB received in last 24 hours")
    tx_last_24h: int | None = Field(None, description="MB sent in last 24 hours")

    # ---- This calendar week ----
    rx_week: int | None = Field(None, description="MB received this week")
    tx_week: int | None = Field(None, description="MB sent this week")

    # ---- Last 7 days ----
    rx_last_7d: int | None = Field(None, description="MB received in last 7 days")
    tx_last_7d: int | None = Field(None, description="MB sent in last 7 days")

    # ---- This calendar month ----
    rx_month: int | None = Field(None, description="MB received this month")
    tx_month: int | None = Field(None, description="MB sent this month")

    # ---- Last 30 days ----
    rx_last_30d: int | None = Field(None, description="MB received in last 30 days")
    tx_last_30d: int | None = Field(None, description="MB sent in last 30 days")

    # ---- Last calendar month ----
    rx_last_month: int | None = Field(None, description="MB received last month")
    tx_last_month: int | None = Field(None, description="MB sent last month")

    # ---- Last calendar week ----
    rx_last_week: int | None = Field(None, description="MB received last week")
    tx_last_week: int | None = Field(None, description="MB sent last week")

    @field_validator(
        "rx_today", "tx_today",
        "rx_last_24h", "tx_last_24h",
        "rx_week", "tx_week",
        "rx_last_7d", "tx_last_7d",
        "rx_month", "tx_month",
        "rx_last_30d", "tx_last_30d",
        "rx_last_month", "tx_last_month",
        "rx_last_week", "tx_last_week",
        mode="before",
    )
    @classmethod
    def _convert_bytes(cls, v: object) -> int | None:
        return _bytes_to_mb(v)


class ModemDataUsage(TeltasyncBaseModel):
    """Data usage for all SIM cards of a single modem."""

    modem_id: str = Field(description="Modem ID")
    sim1: SimUsageData | None = None
    sim2: SimUsageData | None = None


def _parse_sim_block(raw: dict, sim_index: int) -> SimUsageData | None:
    """
    Extract a SIM usage block from various API response shapes:
      Shape A: { "sim1": {...}, "sim2": {...} }
      Shape B: [ { "sim": 1, ... }, { "sim": 2, ... } ]
      Shape C: flat dict with prefixed keys { "1_rx_today": ..., "2_rx_today": ... }
    """
    # Shape A
    block = raw.get(f"sim{sim_index}")

    # Shape C  (flat prefixed keys)
    if block is None:
        prefix = f"{sim_index}_"
        extracted = {k[len(prefix):]: v for k, v in raw.items() if k.startswith(prefix)}
        block = extracted or None

    if not block:
        return None

    def _b(*keys: str) -> int | None:
        for k in keys:
            v = block.get(k)
            if v is not None:
                return _bytes_to_mb(v)
        return None

    return SimUsageData(
        sim=sim_index,
        rx_today     = _b("rx_today",    "received_today",    "rx_day"),
        tx_today     = _b("tx_today",    "sent_today",        "tx_day"),
        rx_last_24h  = _b("rx_last_24h", "received_last_24h", "rx_24h"),
        tx_last_24h  = _b("tx_last_24h", "sent_last_24h",     "tx_24h"),
        rx_week      = _b("rx_week",     "received_week",     "rx_this_week"),
        tx_week      = _b("tx_week",     "sent_week",         "tx_this_week"),
        rx_last_7d   = _b("rx_last_7d",  "received_last_7d",  "rx_7d", "rx_last_7_days"),
        tx_last_7d   = _b("tx_last_7d",  "sent_last_7d",      "tx_7d", "tx_last_7_days"),
        rx_month     = _b("rx_month",    "received_month",    "rx_this_month"),
        tx_month     = _b("tx_month",    "sent_month",        "tx_this_month"),
        rx_last_30d  = _b("rx_last_30d", "received_last_30d", "rx_30d", "rx_last_30_days"),
        tx_last_30d  = _b("tx_last_30d", "sent_last_30d",     "tx_30d", "tx_last_30_days"),
        rx_last_month= _b("rx_last_month","received_last_month"),
        tx_last_month= _b("tx_last_month","sent_last_month"),
        rx_last_week = _b("rx_last_week", "received_last_week"),
        tx_last_week = _b("tx_last_week", "sent_last_week"),
    )


class DataUsage:
    """API wrapper for modem data usage endpoints."""

    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def get_modem_usage(self, modem_id: str) -> ModemDataUsage | None:
        """
        Fetch data usage statistics for a single modem.
        Tries multiple endpoint paths for firmware compatibility.
        Returns None when no endpoint is available.
        """
        import aiohttp

        for path_template in _PATHS:
            path = path_template.format(modem_id=modem_id)
            try:
                async with await self.auth.request("GET", path) as resp:
                    if resp.status == 404:
                        continue
                    resp.raise_for_status()
                    json_response = await resp.json()

                raw = json_response.get("data", json_response)
                if not raw:
                    return None

                # Shape B: list of per-SIM dicts
                if isinstance(raw, list):
                    sim_map: dict[int, dict] = {}
                    for item in raw:
                        sim_idx = item.get("sim") or item.get("sim_index")
                        if sim_idx is not None:
                            sim_map[int(sim_idx)] = item
                    raw = {f"sim{k}": v for k, v in sim_map.items()}

                return ModemDataUsage(
                    modem_id=modem_id,
                    sim1=_parse_sim_block(raw, 1),
                    sim2=_parse_sim_block(raw, 2),
                )
            except aiohttp.ClientResponseError as err:
                if err.status == 404:
                    continue
                raise

        return None

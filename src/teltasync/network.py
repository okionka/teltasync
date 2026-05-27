"""Network interface endpoint bindings for the Teltonika API."""

from pydantic import Field

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel


class InterfaceData(TeltasyncBaseModel):
    """A single network interface entry from /interfaces/status."""

    name: str | None = Field(None, description="Interface name, e.g. 'mob1s1a1'")
    type: str | None = Field(
        None, description="Interface type: 'mobile', 'ethernet', 'wifi'"
    )
    up: bool | None = Field(None, description="Interface up state")
    proto: str | None = Field(None, description="Protocol, e.g. 'dhcp', 'static'")
    ipaddr: str | None = Field(None, description="IPv4 address")
    netmask: str | None = Field(None, description="Subnet mask")
    ip6addr: str | None = Field(None, description="IPv6 address")
    gateway: str | None = Field(None, description="Default gateway")
    dns: list[str] | None = Field(None, description="DNS server list")
    rx_bytes: int | None = Field(None, description="Received bytes since boot")
    tx_bytes: int | None = Field(None, description="Transmitted bytes since boot")
    rx_packets: int | None = Field(None, description="Received packets since boot")
    tx_packets: int | None = Field(None, description="Transmitted packets since boot")


_WAN_PREFIXES = ("mob", "wwan", "ppp", "eth", "wlan", "wifi")


def _interface_priority(iface: InterfaceData) -> int:
    name = iface.name or ""
    for i, prefix in enumerate(_WAN_PREFIXES):
        if name.startswith(prefix):
            return i
    return 99


class WanStatusData(TeltasyncBaseModel):
    """Derived WAN summary — the first active interface ranked by type."""

    ip_address: str | None = Field(None, description="WAN IPv4 address")
    wan_type: str | None = Field(
        None, description="WAN type: 'mobile', 'ethernet', 'wifi'"
    )
    interface: str | None = Field(None, description="Active WAN interface name")


def _infer_type(name: str) -> str:
    if name.startswith(("mob", "wwan", "ppp")):
        return "mobile"
    if name.startswith("eth"):
        return "ethernet"
    if name.startswith(("wlan", "wifi")):
        return "wifi"
    return "unknown"


class Network:
    """API wrapper for /interfaces endpoints."""

    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def get_interfaces(self) -> ApiResponse[list[InterfaceData]]:
        """Return the status of all network interfaces."""
        async with await self.auth.request("GET", "interfaces/status") as resp:
            json_response = await resp.json()
            return ApiResponse[list[InterfaceData]](**json_response)

    async def get_wan_status(self) -> WanStatusData | None:
        """
        Derive WAN status from the interface list.

        Returns the first active interface, preferring mobile over ethernet over wifi.
        Returns None when no active WAN interface is found.
        """
        response = await self.get_interfaces()
        if not response.success or not response.data:
            return None

        active = [i for i in response.data if i.up and i.ipaddr]
        if not active:
            active = [i for i in response.data if i.ipaddr]
        if not active:
            return None

        active.sort(key=_interface_priority)
        best = active[0]
        return WanStatusData(
            ip_address=best.ipaddr,
            wan_type=best.type or _infer_type(best.name or ""),
            interface=best.name,
        )

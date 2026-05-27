"""High-level facade combining Teltonika endpoint clients."""

from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any

from aiohttp import ClientSession

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.backup import Backup
from teltasync.data_usage import DataUsage, ModemDataUsage
from teltasync.exceptions import (
    TeltonikaAuthenticationError,
    TeltonikaConnectionError,
    TeltonikaException,
)
from teltasync.firmware import Firmware, FirmwareStatus, FirmwareUpdateInfo
from teltasync.gps import Gps, GpsStatusData
from teltasync.modems import Modems, ModemStatusFull, ModemStatusOffline
from teltasync.network import Network, WanStatusData
from teltasync.system import DeviceStatusData, System
from teltasync.unauthorized import UnauthorizedClient, UnauthorizedStatusData
from teltasync.wireless import Wireless, WirelessInterface

AUTH_ERROR_CODES = {120, 121, 122, 123}


class Teltasync:  # pylint: disable=too-many-instance-attributes
    """Convenience client exposing common router operations."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        session: ClientSession | None = None,
        verify_ssl: bool = True,
    ):  # pylint: disable=too-many-arguments
        """Initialize the client with connection and credential settings."""

        self._session = session
        self._own_session = session is None
        self._base_url = base_url
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl

        self._auth: Auth | None = None
        self._system: System | None = None
        self._modems: Modems | None = None
        self._unauthorized: UnauthorizedClient | None = None
        self._gps: Gps | None = None
        self._network: Network | None = None
        self._data_usage: DataUsage | None = None
        self._wireless: Wireless | None = None
        self._firmware: Firmware | None = None
        self._backup: Backup | None = None

    @classmethod
    async def create(
        cls,
        base_url: str,
        username: str,
        password: str,
        *,
        verify_ssl: bool = True,
    ) -> "Teltasync":
        """Create a client with an internally managed aiohttp session."""

        return cls(
            base_url=base_url,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
        )

    @property
    def session(self) -> ClientSession:
        """Return the aiohttp session, creating one when needed."""

        if self._session is None:
            self._session = ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the internally owned session, if present."""

        if self._own_session and self._session:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "Teltasync":
        """Enter async context manager scope."""

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context manager scope and close managed resources."""

        await self.close()

    async def get_device_info(self) -> UnauthorizedStatusData:
        """Fetch device metadata available from the unauthorized endpoint."""

        await self._ensure_session()
        response = await self.unauthorized.get_status()
        if response.success and response.data:
            return response.data
        raise TeltonikaConnectionError("Failed to get device info")

    async def validate_credentials(self) -> bool:
        """Validate credentials by attempting login and then logout."""

        try:
            await self._ensure_session()
            await self.auth.authenticate()
        except TeltonikaAuthenticationError:
            return False
        finally:
            await self.logout()
        return True

    async def get_system_info(self) -> DeviceStatusData:
        """Fetch system/device status details."""

        await self._ensure_session()
        response = await self.system.get_device_status()
        if response.success and response.data:
            return response.data
        raise TeltonikaConnectionError("Failed to get system info")

    async def get_modem_status(self) -> list[ModemStatusFull | ModemStatusOffline]:
        """Fetch the status of all modems reported by the device."""

        await self._ensure_session()
        response = await self.modems.get_status()
        if response.success and response.data:
            return response.data
        raise TeltonikaConnectionError("Failed to get modem status")

    async def _run_modem_action(
        self,
        action: Callable[[str], Awaitable[ApiResponse[dict[str, Any]]]],
        modem_id: str,
        action_name: str,
    ) -> None:
        """Execute a modem action and raise on an unsuccessful API response."""
        await self._ensure_session()
        response = await action(modem_id)
        if response and response.success:
            return

        message = f"Failed to {action_name}"
        if not response or not response.errors:
            raise TeltonikaConnectionError(message)

        first_error = response.errors[0]
        if first_error.code in AUTH_ERROR_CODES:
            raise TeltonikaAuthenticationError(
                f"{first_error.error} (code {first_error.code})"
            )

        raise TeltonikaException(first_error.error)

    async def reboot_modem(self, modem_id: str) -> None:
        """Reboot the specified modem."""
        await self._run_modem_action(self.modems.reboot_modem, modem_id, "reboot modem")

    async def restart_connection(self, modem_id: str) -> None:
        """Restart the connection for the specified modem."""
        await self._run_modem_action(
            self.modems.restart_connection,
            modem_id,
            "restart modem connection",
        )

    async def switch_sim(self, modem_id: str) -> None:
        """Switch to the next SIM of the specified modem."""
        await self._run_modem_action(
            self.modems.switch_sim, modem_id, "switch modem SIM"
        )

    async def set_sim(self, modem_id: str, sim_index: int) -> bool:
        """Set a specific SIM card (1 or 2) as active on the given modem."""
        await self._ensure_session()
        response = await self.modems.set_sim(modem_id, sim_index)
        return bool(response and response.success)

    async def reboot_device(self) -> bool:
        """Trigger device reboot and return whether it was accepted."""

        await self._ensure_session()
        response = await self.system.reboot()
        return bool(response and response.success)

    async def get_gps_status(self) -> GpsStatusData | None:
        """
        Fetch current GPS position, speed, satellite count and fix status.

        Returns ``None`` when the device has no GPS capability or GPS is disabled.
        """
        await self._ensure_session()
        response = await self.gps.get_status()
        if response.success and response.data:
            return response.data
        return None

    async def get_wan_status(self) -> WanStatusData | None:
        """
        Fetch WAN IP address and interface type from the active network interface.

        Returns ``None`` when no active WAN interface is found.
        """
        await self._ensure_session()
        return await self.network.get_wan_status()

    async def get_modem_data_usage(self, modem_id: str) -> ModemDataUsage | None:
        """
        Fetch per-SIM data usage statistics (today / last 24 h / week / month …)
        for the specified modem.

        Returns ``None`` when the endpoint is not available on this firmware version.
        """
        await self._ensure_session()
        return await self.data_usage.get_modem_usage(modem_id)

    async def get_wireless_interfaces(self) -> list[WirelessInterface]:
        """
        Fetch all wireless interfaces with their enabled state, SSID, band, clients.

        Returns an empty list when the endpoint is not available.
        """
        await self._ensure_session()
        response = await self.wireless.get_interfaces()
        if response.success and response.data:
            return response.data
        return []

    async def set_wifi_enabled(self, interface_id: str, enabled: bool) -> bool:
        """
        Enable or disable a wireless interface.

        Returns True when the operation was accepted by the router.
        """
        await self._ensure_session()
        response = await self.wireless.set_enabled(interface_id, enabled)
        return bool(response and response.success)

    async def get_firmware_status(self) -> FirmwareStatus | None:
        """
        Fetch installed firmware version and available update info.

        Returns None when the endpoint is not available on this firmware version.
        """
        await self._ensure_session()
        try:
            response = await self.firmware.get_status()
            if response.success and response.data:
                return response.data
        except Exception:  # noqa: BLE001
            pass
        return None

    async def check_firmware_update(self) -> FirmwareUpdateInfo | None:
        """
        Trigger an online firmware update check.

        Returns FirmwareUpdateInfo when an update is available, None otherwise.
        """
        await self._ensure_session()
        try:
            response = await self.firmware.check_update()
            if response.success and response.data:
                return response.data
        except Exception:  # noqa: BLE001
            pass
        return None

    async def install_firmware_update(self) -> bool:
        """
        Start the firmware update installation.

        Returns True when the router accepted the request.
        Note: The router will reboot during the update process.
        """
        await self._ensure_session()
        response = await self.firmware.install_update()
        return bool(response and response.success)

    async def export_config(self) -> bytes:
        """
        Create and download a configuration backup.
        Flow: generate → wait → download.
        Returns raw bytes of the backup archive.
        """
        await self._ensure_session()
        return await self.backup.generate_and_download()

    async def get_backup_status(self):
        """Return current backup generation status."""
        await self._ensure_session()
        return await self.backup.get_status()

    async def restore_upload_validate(self, data: bytes):
        """
        Upload a backup and validate it.
        Returns BackupMetadata — call restore_apply() to complete restore.
        """
        await self._ensure_session()
        return await self.backup.restore(data)

    async def restore_apply(self) -> bool:
        """Apply the previously validated backup. Router will reboot."""
        await self._ensure_session()
        response = await self.backup.apply()
        return bool(response and response.success)

    async def logout(self) -> bool:
        """Log out of the authenticated API session."""

        await self._ensure_session()
        response = await self.auth.logout()
        return bool(response and response.success)

    @property
    def auth(self) -> Auth:
        """Return lazy-initialized authentication client."""

        if self._auth is None:
            self._auth = Auth(
                self.session,
                self._base_url,
                self._username,
                self._password,
                check_certificate=self._verify_ssl,
            )
        return self._auth

    @property
    def system(self) -> System:
        """Return lazy-initialized system endpoint client."""

        if self._system is None:
            self._system = System(self.auth)
        return self._system

    @property
    def modems(self) -> Modems:
        """Return lazy-initialized modems endpoint client."""

        if self._modems is None:
            self._modems = Modems(self.auth)
        return self._modems

    @property
    def unauthorized(self) -> UnauthorizedClient:
        """Return lazy-initialized unauthorized endpoint client."""

        if self._unauthorized is None:
            self._unauthorized = UnauthorizedClient(
                self.session,
                self._base_url,
                check_certificate=self._verify_ssl,
            )
        return self._unauthorized

    @property
    def gps(self) -> Gps:
        """Return lazy-initialized GPS endpoint client."""

        if self._gps is None:
            self._gps = Gps(self.auth)
        return self._gps

    @property
    def network(self) -> Network:
        """Return lazy-initialized network endpoint client."""

        if self._network is None:
            self._network = Network(self.auth)
        return self._network

    @property
    def data_usage(self) -> DataUsage:
        """Return lazy-initialized data usage endpoint client."""

        if self._data_usage is None:
            self._data_usage = DataUsage(self.auth)
        return self._data_usage

    @property
    def wireless(self) -> Wireless:
        """Return lazy-initialized wireless endpoint client."""

        if self._wireless is None:
            self._wireless = Wireless(self.auth)
        return self._wireless

    @property
    def firmware(self) -> Firmware:
        """Return lazy-initialized firmware endpoint client."""

        if self._firmware is None:
            self._firmware = Firmware(self.auth)
        return self._firmware

    @property
    def backup(self) -> Backup:
        """Return lazy-initialized backup/restore endpoint client."""

        if self._backup is None:
            self._backup = Backup(self.auth)
        return self._backup

    async def _ensure_session(self) -> ClientSession:
        """Internal helper to guarantee session initialization."""

        return self.session

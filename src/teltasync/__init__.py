"""Teltonika API library."""

from teltasync.exceptions import (
    TeltonikaAuthenticationError,
    TeltonikaConnectionError,
    TeltonikaException,
    TeltonikaInvalidCredentialsError,
)
from teltasync.backup import Backup, BackupMetadata, BackupStatus
from teltasync.data_usage import DataUsage, ModemDataUsage, SimUsageData
from teltasync.firmware import Firmware, FirmwareStatus, FirmwareUpdateInfo
from teltasync.gps import Gps, GpsStatusData
from teltasync.network import Network, WanStatusData
from teltasync.teltasync import Teltasync
from teltasync.wireless import Wireless, WirelessInterface

__version__ = "0.3.1"
__all__ = [
    "Teltasync",
    "TeltonikaException",
    "TeltonikaConnectionError",
    "TeltonikaAuthenticationError",
    "TeltonikaInvalidCredentialsError",
]

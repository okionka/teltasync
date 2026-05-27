"""Configuration backup and restore endpoint bindings for the Teltonika API.

Backup flow:
  1. POST /backup/actions/generate   → create backup on router
  2. GET  /backup/errors/status      → poll until done
  3. GET  /backup/actions/download   → download bytes

Restore flow:
  1. POST /backup/actions/upload     → upload backup file
  2. POST /backup/actions/validate   → returns backup metadata
  3. POST /backup/actions/apply      → apply restore (reboots router)
"""
import asyncio
import io
import logging
from typing import Any

import aiohttp
from pydantic import AliasChoices, Field

from teltasync.api_base import ApiResponse
from teltasync.auth import Auth
from teltasync.base_model import TeltasyncBaseModel

_LOGGER = logging.getLogger(__name__)

_POLL_INTERVAL = 2.0   # seconds between status polls
_POLL_TIMEOUT  = 60.0  # max seconds to wait for backup generation


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class BackupStatus(TeltasyncBaseModel):
    status: str | None = Field(
        None,
        validation_alias=AliasChoices("status", "state", "backup_status"),
        description="'done', 'generating', 'error', 'idle'",
    )
    error: str | None = Field(None)
    filename: str | None = Field(None)

    @property
    def is_done(self) -> bool:
        return (self.status or "").lower() in ("done", "complete", "ready", "success")

    @property
    def is_error(self) -> bool:
        return (self.status or "").lower() in ("error", "failed", "failure")


class BackupMetadata(TeltasyncBaseModel):
    """Metadata returned by /backup/actions/validate."""
    version: str | None = Field(
        None,
        validation_alias=AliasChoices("version", "fw_version", "firmware_version"),
    )
    date: str | None = Field(
        None,
        validation_alias=AliasChoices("date", "created_at", "timestamp", "backup_date"),
    )
    hostname: str | None = Field(None)
    model: str | None = Field(None)
    serial: str | None = Field(None)
    size: int | None = Field(None)
    valid: bool | None = Field(
        None,
        validation_alias=AliasChoices("valid", "is_valid", "success"),
    )

    def summary(self) -> str:
        parts = []
        if self.hostname:
            parts.append(f"Hostname: {self.hostname}")
        if self.model:
            parts.append(f"Modell: {self.model}")
        if self.version:
            parts.append(f"Firmware: {self.version}")
        if self.date:
            parts.append(f"Datum: {self.date}")
        if self.serial:
            parts.append(f"Seriennummer: {self.serial}")
        if self.size:
            parts.append(f"Größe: {self.size:,} Bytes")
        return "\n".join(parts) if parts else "Keine Metadaten verfügbar"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class Backup:
    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> aiohttp.ClientResponse:
        return await self.auth.request(method, path, **kwargs)

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    async def generate(self) -> ApiResponse[dict]:
        """POST /backup/actions/generate — trigger backup creation on router."""
        async with await self._request("POST", "backup/actions/generate") as resp:
            resp.raise_for_status()
            return ApiResponse[dict](**await resp.json())

    async def get_status(self) -> BackupStatus:
        """GET /backup/errors/status — poll backup generation status."""
        # Try both known status endpoints
        for path in ("backup/errors/status", "backup/status"):
            try:
                async with await self._request("GET", path) as resp:
                    if resp.status == 404:
                        continue
                    resp.raise_for_status()
                    raw = await resp.json()
                    data = raw.get("data", raw)
                    return BackupStatus(**(data if isinstance(data, dict) else {}))
            except aiohttp.ClientResponseError as err:
                if err.status == 404:
                    continue
                raise
        return BackupStatus(status="unknown")

    async def wait_until_ready(
        self,
        interval: float = _POLL_INTERVAL,
        timeout: float = _POLL_TIMEOUT,
    ) -> BackupStatus:
        """Poll status until done or error, raises TimeoutError if too long."""
        elapsed = 0.0
        while elapsed < timeout:
            status = await self.get_status()
            _LOGGER.debug("Backup status: %s", status.status)
            if status.is_done:
                return status
            if status.is_error:
                raise RuntimeError(f"Backup generation failed: {status.error or status.status}")
            await asyncio.sleep(interval)
            elapsed += interval
        raise TimeoutError(f"Backup not ready after {timeout}s")

    async def download(self) -> bytes:
        """GET /backup/actions/download — download backup as binary."""
        async with await self._request("GET", "backup/actions/download") as resp:
            resp.raise_for_status()
            data = await resp.read()
            _LOGGER.info("Backup downloaded: %d bytes", len(data))
            return data

    async def generate_and_download(self) -> bytes:
        """Full backup flow: generate → wait → download."""
        _LOGGER.info("Starting backup generation…")
        await self.generate()
        _LOGGER.info("Waiting for backup to complete…")
        await self.wait_until_ready()
        _LOGGER.info("Downloading backup…")
        return await self.download()

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    async def upload(self, data: bytes) -> ApiResponse[dict]:
        """POST /backup/actions/upload — upload backup file to router."""
        form = aiohttp.FormData()
        form.add_field(
            "file",
            io.BytesIO(data),
            filename="backup.tar.gz",
            content_type="application/octet-stream",
        )
        async with await self._request(
            "POST", "backup/actions/upload", data=form
        ) as resp:
            resp.raise_for_status()
            return ApiResponse[dict](**await resp.json())

    async def validate(self) -> BackupMetadata:
        """POST /backup/actions/validate — returns backup metadata."""
        async with await self._request("POST", "backup/actions/validate") as resp:
            resp.raise_for_status()
            raw = await resp.json()
            data = raw.get("data", raw)
            meta = BackupMetadata(**(data if isinstance(data, dict) else {}))
            _LOGGER.info("Backup metadata: %s", meta.summary())
            return meta

    async def apply(self) -> ApiResponse[dict]:
        """POST /backup/actions/apply — apply restore (router reboots)."""
        async with await self._request("POST", "backup/actions/apply") as resp:
            resp.raise_for_status()
            return ApiResponse[dict](**await resp.json())

    async def restore(self, data: bytes) -> BackupMetadata:
        """
        Full restore flow: upload → validate.

        Returns BackupMetadata so the caller can confirm before apply().
        Call apply() separately after user confirmation.
        """
        _LOGGER.info("Uploading backup for restore…")
        await self.upload(data)
        _LOGGER.info("Validating backup…")
        return await self.validate()

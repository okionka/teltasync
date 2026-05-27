"""Configuration backup and restore endpoint bindings for the Teltonika API.

Backup flow (from Teltonika developer examples):
  1. POST /backup/actions/generate   {data:{}}  → start backup creation
  2. GET  /backup/errors/status               → poll until status="done"
  3. GET  /backup/actions/download            → returns binary archive

Restore flow:
  1. POST /backup/actions/upload    (multipart file)
  2. POST /backup/actions/validate  → returns backup metadata
  3. POST /backup/actions/apply     → apply + reboot
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


from dataclasses import dataclass


@dataclass
class GenerateResult:
    """Result of POST /backup/actions/generate — contains file checksums."""
    sha256: str | None = None
    md5: str | None = None
    success: bool = True


_POLL_INTERVAL = 2.0
_POLL_TIMEOUT  = 120.0


class BackupStatus(TeltasyncBaseModel):
    status: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "status", "state", "backup_status", "errorStatus",
        ),
    )
    error: str | None = Field(
        None,
        validation_alias=AliasChoices("error", "message", "errorMessage"),
    )
    filename: str | None = None

    @property
    def is_done(self) -> bool:
        s = (self.status or "").lower()
        return s in ("done", "complete", "ready", "success", "0", "ok")

    @property
    def is_error(self) -> bool:
        s = (self.status or "").lower()
        return s in ("error", "failed", "failure") or (
            self.status is not None
            and self.status not in ("done", "complete", "ready", "success",
                                    "0", "ok", "generating", "pending", "running", "")
        )


class BackupMetadata(TeltasyncBaseModel):
    version: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "version", "fw_version", "firmware_version", "fwVersion",
        ),
    )
    date: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "date", "created_at", "timestamp", "backup_date", "createdAt",
        ),
    )
    hostname: str | None = None
    model: str | None = None
    serial: str | None = None
    size: int | None = None
    valid: bool | None = Field(
        None,
        validation_alias=AliasChoices("valid", "is_valid", "success", "isValid"),
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


class Backup:
    def __init__(self, auth: Auth) -> None:
        self.auth = auth

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    async def generate(self) -> "GenerateResult":
        """
        POST /backup/actions/generate  body={"data": {}}

        The router processes the backup synchronously and returns
        sha256 + md5 checksums when done. No status polling needed.

        Returns GenerateResult with the checksums for optional verification.
        """
        async with await self.auth.request(
            "POST", "backup/actions/generate",
            json={"data": {}},
        ) as resp:
            resp.raise_for_status()
            raw = await resp.json()
            _LOGGER.info("Backup generated: %s", raw)
            data = raw.get("data", raw) or {}
            return GenerateResult(
                sha256=data.get("sha256"),
                md5=data.get("md5"),
                success=raw.get("success", True),
            )

    async def get_status(self) -> BackupStatus:
        """GET /backup/errors/status — poll until done."""
        for path in ("backup/errors/status", "backup/status"):
            try:
                async with await self.auth.request("GET", path) as resp:
                    if resp.status == 404:
                        continue
                    resp.raise_for_status()
                    raw = await resp.json()
                    _LOGGER.debug("Backup status (%s): %s", path, raw)
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
        elapsed = 0.0
        while elapsed < timeout:
            status = await self.get_status()
            _LOGGER.debug("Backup poll: status=%s elapsed=%.0fs", status.status, elapsed)
            if status.is_done:
                return status
            if status.is_error:
                raise RuntimeError(
                    f"Backup generation failed: {status.error or status.status}"
                )
            await asyncio.sleep(interval)
            elapsed += interval
        raise TimeoutError(f"Backup not ready after {timeout:.0f}s")

    async def download(self, sha256: str | None = None) -> bytes:
        """
        POST /backup/actions/download  {"data": {}}
        Same pattern as generate — no parameters needed in the body.
        The sha256 from generate() is used for verification after download,
        NOT sent in the request body.
        """
        # Ordered by most-likely-to-work first
        candidates = [
            # Primary: same pattern as generate (confirmed working)
            ("POST", "backup/actions/download", {"data": {}}),
            # Fallbacks for other firmware versions
            ("POST", "backup/actions/download", {}),
            ("GET",  "backup/actions/download", None),
            ("GET",  "backup/download",         None),
            ("POST", "backup/download",         {"data": {}}),
        ]

        for method, path, body in candidates:
            try:
                kwargs = {"json": body} if body is not None else {}
                async with await self.auth.request(method, path, **kwargs) as resp:
                    _LOGGER.warning(
                        "Backup download: %s %s body=%s → HTTP %s content-type=%s",
                        method, path, body, resp.status,
                        resp.headers.get("Content-Type", "?"),
                    )
                    if resp.status in (404, 501, 405):
                        continue
                    if resp.status == 422:
                        _LOGGER.warning(
                            "Backup download: 422 on %s %s — trying next", method, path
                        )
                        continue
                    resp.raise_for_status()
                    data = await resp.read()
                    if len(data) < 100:
                        try:
                            import json
                            err_body = json.loads(data)
                            _LOGGER.warning(
                                "Backup download: short response, likely error JSON: %s",
                                err_body,
                            )
                        except Exception:
                            pass
                        continue
                    _LOGGER.warning(
                        "Backup download OK: %s %s → %d bytes",
                        method, path, len(data),
                    )
                    return data
            except aiohttp.ClientResponseError as err:
                _LOGGER.warning(
                    "Backup download: %s %s → HTTP %s", method, path, err.status
                )
                if err.status in (404, 501, 405, 422):
                    continue
                raise

        raise RuntimeError(
            "backup/actions/download: all attempts failed — "
            "check HA logs for HTTP status codes per attempt."
        )

    async def generate_and_download(self) -> "tuple[bytes, GenerateResult]":
        """
        Full backup flow: generate → download (no polling needed).
        Passes sha256 to download() for the POST body.
        """
        _LOGGER.info("Step 1/2: Generating backup on router…")
        result = await self.generate()
        _LOGGER.info("Step 2/2: Downloading backup (sha256=%s)…", result.sha256)
        data = await self.download(sha256=result.sha256)
        return data, result

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    async def upload(self, data: bytes) -> ApiResponse[dict]:
        """POST /backup/actions/upload — multipart upload."""
        form = aiohttp.FormData()
        form.add_field(
            "file", io.BytesIO(data),
            filename="backup.tar.gz",
            content_type="application/octet-stream",
        )
        async with await self.auth.request(
            "POST", "backup/actions/upload", data=form
        ) as resp:
            resp.raise_for_status()
            return ApiResponse[dict](**await resp.json())

    async def validate(self) -> BackupMetadata:
        """POST /backup/actions/validate → metadata."""
        async with await self.auth.request(
            "POST", "backup/actions/validate",
            json={"data": {}},
        ) as resp:
            resp.raise_for_status()
            raw = await resp.json()
            data = raw.get("data", raw)
            meta = BackupMetadata(**(data if isinstance(data, dict) else {}))
            _LOGGER.info("Backup metadata: %s", meta.summary())
            return meta

    async def apply(self) -> ApiResponse[dict]:
        """POST /backup/actions/apply → router reboots."""
        async with await self.auth.request(
            "POST", "backup/actions/apply",
            json={"data": {}},
        ) as resp:
            resp.raise_for_status()
            return ApiResponse[dict](**await resp.json())

    async def restore(self, data: bytes) -> BackupMetadata:
        """Upload + validate backup. Call apply() after user confirmation."""
        _LOGGER.info("Uploading backup…")
        await self.upload(data)
        _LOGGER.info("Validating backup…")
        return await self.validate()

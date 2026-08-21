"""Append-only storage for byte-exact provider responses."""

from __future__ import annotations

import gzip
import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from prem_engine_api.config import Settings


class RawResponseStorageError(RuntimeError):
    """Raised when a raw response cannot be stored or verified safely."""


@dataclass(frozen=True)
class StoredRawResponse:
    """Address and digest of one immutable compressed response."""

    object_key: str
    checksum: str


class RawResponseStore(Protocol):
    """Storage boundary shared by local development and durable deployments."""

    def store(
        self,
        *,
        provider: str,
        body: bytes,
        fetched_at: datetime | None = None,
        extension: str = "json",
    ) -> StoredRawResponse:
        """Compress and create a response object without overwriting an existing object."""

    def read(self, object_key: str, *, expected_checksum: str | None = None) -> bytes:
        """Read, decompress, and optionally checksum-verify one stored response."""

    def close(self) -> None:
        """Release any store-owned resources."""


def _stored_response(
    *, provider: str, body: bytes, fetched_at: datetime | None, extension: str
) -> tuple[StoredRawResponse, bytes]:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", provider):
        raise ValueError("provider must be a lowercase slug")
    if not re.fullmatch(r"[a-z0-9]+", extension):
        raise ValueError("extension must contain only lowercase letters and digits")
    observed_at = fetched_at or datetime.now(UTC)
    checksum = hashlib.sha256(body).hexdigest()
    relative = Path(
        provider,
        observed_at.strftime("%Y/%m/%d"),
        f"{observed_at.strftime('%H%M%S%f')}_{uuid4()}_{checksum[:12]}.{extension}.gz",
    )
    return (
        StoredRawResponse(object_key=relative.as_posix(), checksum=checksum),
        gzip.compress(body, compresslevel=9, mtime=0),
    )


def _verified_body(compressed: bytes, *, object_key: str, expected_checksum: str | None) -> bytes:
    try:
        body = gzip.decompress(compressed)
    except (EOFError, gzip.BadGzipFile) as error:
        raise RawResponseStorageError(
            f"raw response object is not valid gzip: {object_key}"
        ) from error
    checksum = hashlib.sha256(body).hexdigest()
    if expected_checksum is not None and not hmac.compare_digest(checksum, expected_checksum):
        raise RawResponseStorageError(f"raw response checksum mismatch: {object_key}")
    return body


class LocalRawResponseStore:
    """Append-only filesystem implementation used for local development."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def store(
        self,
        *,
        provider: str,
        body: bytes,
        fetched_at: datetime | None = None,
        extension: str = "json",
    ) -> StoredRawResponse:
        stored, compressed = _stored_response(
            provider=provider,
            body=body,
            fetched_at=fetched_at,
            extension=extension,
        )
        destination = self._root / Path(stored.object_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(compressed)
        return stored

    def read(self, object_key: str, *, expected_checksum: str | None = None) -> bytes:
        source = self._root / Path(object_key)
        return _verified_body(
            source.read_bytes(), object_key=object_key, expected_checksum=expected_checksum
        )

    def close(self) -> None:
        """Match the shared storage lifecycle; local storage owns no open resources."""


def create_raw_response_store(settings: Settings) -> RawResponseStore:
    """Build the installation-local append-only raw response store."""

    return LocalRawResponseStore(settings.raw_data_root)

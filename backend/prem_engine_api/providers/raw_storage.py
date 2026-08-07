"""Append-only storage for byte-exact provider responses."""

from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class StoredRawResponse:
    """Address and digest of one immutable compressed response."""

    object_key: str
    checksum: str


class LocalRawResponseStore:
    """Filesystem implementation used locally; R2 will implement the same boundary."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def store(
        self,
        *,
        provider: str,
        body: bytes,
        fetched_at: datetime | None = None,
    ) -> StoredRawResponse:
        """Compress and create a response object without ever overwriting a prior fetch."""

        observed_at = fetched_at or datetime.now(UTC)
        checksum = hashlib.sha256(body).hexdigest()
        relative = Path(
            provider,
            observed_at.strftime("%Y/%m/%d"),
            f"{observed_at.strftime('%H%M%S%f')}_{uuid4()}_{checksum[:12]}.json.gz",
        )
        destination = self._root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        compressed = gzip.compress(body, compresslevel=9, mtime=0)
        with destination.open("xb") as output:
            output.write(compressed)
        return StoredRawResponse(object_key=relative.as_posix(), checksum=checksum)

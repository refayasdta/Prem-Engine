"""Atomic manifest publication over local storage or Cloudflare R2."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

from prem_engine_api.config import Settings
from prem_engine_api.providers.raw_storage import R2RawResponseStore
from prem_engine_api.snapshots.contracts import PublicSnapshotManifest


class PublicSnapshotStorageError(RuntimeError):
    """Raised when a sanitized snapshot cannot be published atomically."""


class SnapshotObjectWriter(Protocol):
    def put_immutable(self, object_key: str, body: bytes, checksum: str) -> None: ...

    def put_manifest(self, object_key: str, body: bytes, checksum: str) -> None: ...

    def close(self) -> None: ...


class LocalSnapshotObjectWriter:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, object_key: str) -> Path:
        path = self._root / Path(object_key)
        if path.resolve().is_relative_to(self._root.resolve()):
            return path
        raise ValueError("snapshot object key escapes the configured root")

    def put_immutable(self, object_key: str, body: bytes, checksum: str) -> None:
        destination = self._path(object_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as handle:
                handle.write(body)
        except FileExistsError:
            try:
                existing_checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
            except OSError as error:
                raise PublicSnapshotStorageError(
                    "local snapshot object verification failed"
                ) from error
            if existing_checksum != checksum:
                raise PublicSnapshotStorageError(
                    "local immutable snapshot checksum mismatch"
                ) from None
            return
        except OSError as error:
            destination.unlink(missing_ok=True)
            raise PublicSnapshotStorageError("local snapshot object write failed") from error

    def put_manifest(self, object_key: str, body: bytes, checksum: str) -> None:
        destination = self._path(object_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4()}.tmp")
        try:
            temporary.write_bytes(body)
            os.replace(temporary, destination)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise PublicSnapshotStorageError("local snapshot manifest write failed") from error

    def close(self) -> None:
        """Local publication owns no open resources."""


class R2SnapshotObjectWriter:
    def __init__(self, store: R2RawResponseStore) -> None:
        self._store = store

    def put_immutable(self, object_key: str, body: bytes, checksum: str) -> None:
        try:
            self._store.put_object(
                object_key,
                body=body,
                content_type="application/json",
                checksum=checksum,
                immutable=True,
            )
        except FileExistsError:
            return
        except Exception as error:
            raise PublicSnapshotStorageError("R2 snapshot object write failed") from error

    def put_manifest(self, object_key: str, body: bytes, checksum: str) -> None:
        try:
            self._store.put_object(
                object_key,
                body=body,
                content_type="application/json",
                checksum=checksum,
                immutable=False,
            )
        except Exception as error:
            raise PublicSnapshotStorageError("R2 snapshot manifest write failed") from error

    def close(self) -> None:
        self._store.close()


@dataclass(frozen=True)
class PublishedSnapshot:
    manifest_key: str
    manifest: PublicSnapshotManifest


class PublicSnapshotStore:
    def __init__(self, writer: SnapshotObjectWriter) -> None:
        self._writer = writer

    def publish(
        self,
        *,
        logical_key: str,
        payload: bytes,
        published_at: datetime,
        expires_at: datetime,
        cache_seconds: int,
    ) -> PublishedSnapshot:
        checksum = hashlib.sha256(payload).hexdigest()
        timestamp = published_at.strftime("%Y%m%dt%H%M%S%fz")
        object_key = f"public/v1/objects/{logical_key}/{timestamp}-{checksum[:16]}.json"
        manifest_key = f"public/v1/manifests/{logical_key}.json"
        manifest = PublicSnapshotManifest(
            logical_key=logical_key,
            object_key=object_key,
            published_at=published_at,
            expires_at=expires_at,
            content_sha256=checksum,
            content_length=len(payload),
            cache_seconds=cache_seconds,
        )
        manifest_body = manifest.model_dump_json().encode()
        manifest_checksum = hashlib.sha256(manifest_body).hexdigest()
        self._writer.put_immutable(object_key, payload, checksum)
        self._writer.put_manifest(manifest_key, manifest_body, manifest_checksum)
        return PublishedSnapshot(manifest_key, manifest)

    def close(self) -> None:
        self._writer.close()


def create_public_snapshot_store(settings: Settings) -> PublicSnapshotStore | None:
    if settings.public_snapshot_store == "disabled":
        return None
    if settings.public_snapshot_store == "local":
        return PublicSnapshotStore(LocalSnapshotObjectWriter(settings.public_snapshot_root))
    endpoint = settings.r2_endpoint_url or (
        f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    )
    secret = settings.r2_snapshot_secret_access_key
    if secret is None:  # pragma: no cover - enforced by Settings
        raise PublicSnapshotStorageError("R2 snapshot secret is missing")
    r2 = R2RawResponseStore(
        endpoint_url=endpoint,
        bucket_name=cast(str, settings.r2_snapshot_bucket_name),
        access_key_id=cast(str, settings.r2_snapshot_access_key_id),
        secret_access_key=secret.get_secret_value(),
    )
    return PublicSnapshotStore(R2SnapshotObjectWriter(r2))

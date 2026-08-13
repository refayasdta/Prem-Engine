"""Integrity and atomicity requirements for public delivery snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from prem_engine_api.config import Settings
from prem_engine_api.snapshots.contracts import PublicSnapshotManifest
from prem_engine_api.snapshots.storage import (
    LocalSnapshotObjectWriter,
    PublicSnapshotStorageError,
    PublicSnapshotStore,
)
from pydantic import SecretStr, ValidationError


class RecordingWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes, str]] = []

    def put_immutable(self, object_key: str, body: bytes, checksum: str) -> None:
        self.calls.append(("object", object_key, body, checksum))

    def put_manifest(self, object_key: str, body: bytes, checksum: str) -> None:
        self.calls.append(("manifest", object_key, body, checksum))

    def close(self) -> None:
        return


def test_payload_is_immutable_and_precedes_atomic_manifest() -> None:
    writer = RecordingWriter()
    store = PublicSnapshotStore(writer)
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    body = b'{"rows":[]}'

    published = store.publish(
        logical_key="standings/default",
        payload=body,
        published_at=now,
        expires_at=now + timedelta(hours=5),
        cache_seconds=300,
    )

    assert [call[0] for call in writer.calls] == ["object", "manifest"]
    object_call, manifest_call = writer.calls
    assert object_call[2] == body
    assert object_call[3] == hashlib.sha256(body).hexdigest()
    manifest = PublicSnapshotManifest.model_validate_json(manifest_call[2])
    assert manifest == published.manifest
    assert manifest.object_key == object_call[1]
    assert manifest.content_length == len(body)
    assert manifest.content_sha256 == object_call[3]


def test_local_immutable_object_is_not_overwritten(tmp_path: Path) -> None:
    writer = LocalSnapshotObjectWriter(tmp_path)
    object_key = "public/v1/objects/example/version.json"
    first = b"first"
    writer.put_immutable(object_key, first, hashlib.sha256(first).hexdigest())
    writer.put_immutable(object_key, first, hashlib.sha256(first).hexdigest())

    assert (tmp_path / object_key).read_bytes() == first
    with pytest.raises(PublicSnapshotStorageError, match="checksum mismatch"):
        writer.put_immutable(object_key, b"second", hashlib.sha256(b"second").hexdigest())
    with pytest.raises(ValueError, match="escapes"):
        writer.put_manifest("../outside.json", b"unsafe", "unused")


def test_manifest_rejects_unversioned_or_inconsistent_content() -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        PublicSnapshotManifest(
            logical_key="standings/default",
            object_key="raw/provider-response.json",
            published_at=now,
            expires_at=now + timedelta(minutes=5),
            content_sha256="0" * 64,
            content_length=10,
            cache_seconds=300,
        )
    with pytest.raises(ValidationError):
        PublicSnapshotManifest(
            logical_key="standings/default",
            object_key="public/v1/objects/standings/default/version.json",
            published_at=now,
            expires_at=now,
            content_sha256="0" * 64,
            content_length=10,
            cache_seconds=300,
        )


def test_r2_snapshot_settings_require_separate_complete_credentials() -> None:
    with pytest.raises(ValueError, match="R2 public snapshot storage"):
        Settings(public_snapshot_store="r2", r2_account_id="account")

    settings = Settings(
        public_snapshot_store="r2",
        r2_account_id="account",
        r2_snapshot_bucket_name="prem-engine-public",
        r2_snapshot_access_key_id="snapshot-id",
        r2_snapshot_secret_access_key=SecretStr("snapshot-secret"),
    )
    assert settings.r2_snapshot_bucket_name == "prem-engine-public"
    assert json.loads(settings.model_dump_json())["public_snapshot_store"] == "r2"

    with pytest.raises(ValueError, match="separate bucket"):
        Settings(
            public_snapshot_store="r2",
            r2_account_id="account",
            r2_bucket_name="prem-engine-shared",
            r2_snapshot_bucket_name="prem-engine-shared",
            r2_snapshot_access_key_id="snapshot-id",
            r2_snapshot_secret_access_key=SecretStr("snapshot-secret"),
        )
    with pytest.raises(ValueError, match="separate credential"):
        Settings(
            public_snapshot_store="r2",
            r2_account_id="account",
            r2_bucket_name="prem-engine-raw",
            r2_access_key_id="shared-id",
            r2_snapshot_bucket_name="prem-engine-public",
            r2_snapshot_access_key_id="shared-id",
            r2_snapshot_secret_access_key=SecretStr("snapshot-secret"),
        )

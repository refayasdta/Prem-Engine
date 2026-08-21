"""Byte preservation and append-only behavior for local raw capture."""

import gzip
from pathlib import Path

import pytest
from prem_engine_api.config import Settings
from prem_engine_api.providers.raw_storage import (
    LocalRawResponseStore,
    RawResponseStorageError,
    create_raw_response_store,
)


def test_identical_responses_create_distinct_immutable_objects(tmp_path: Path) -> None:
    store = LocalRawResponseStore(tmp_path)
    body = b'{"data":[]}'
    first = store.store(provider="kickoffapi", body=body)
    second = store.store(provider="kickoffapi", body=body)

    assert first.checksum == second.checksum
    assert first.object_key != second.object_key
    assert gzip.decompress((tmp_path / first.object_key).read_bytes()) == body
    assert gzip.decompress((tmp_path / second.object_key).read_bytes()) == body


def test_raw_store_supports_safe_csv_artifacts(tmp_path: Path) -> None:
    store = LocalRawResponseStore(tmp_path)
    stored = store.store(provider="football-data", body=b"Date,HomeTeam\n", extension="csv")

    assert stored.object_key.endswith(".csv.gz")
    with pytest.raises(ValueError, match="extension"):
        store.store(provider="football-data", body=b"unsafe", extension="../csv")


def test_local_store_reads_and_verifies_checksum(tmp_path: Path) -> None:
    store = LocalRawResponseStore(tmp_path)
    stored = store.store(provider="kickoffapi", body=b'{"ok":true}')

    assert store.read(stored.object_key, expected_checksum=stored.checksum) == b'{"ok":true}'
    with pytest.raises(RawResponseStorageError, match="checksum mismatch"):
        store.read(stored.object_key, expected_checksum="0" * 64)


def test_factory_always_builds_installation_local_store(tmp_path: Path) -> None:
    settings = Settings(raw_data_root=tmp_path)
    store = create_raw_response_store(settings)
    assert isinstance(store, LocalRawResponseStore)
    store.close()

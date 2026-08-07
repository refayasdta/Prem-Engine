"""Byte preservation and append-only behavior for local raw capture."""

import gzip
from pathlib import Path

import pytest
from prem_engine_api.providers.raw_storage import LocalRawResponseStore


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

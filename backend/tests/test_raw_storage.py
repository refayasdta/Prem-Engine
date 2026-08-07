"""Byte preservation and append-only behavior for local raw capture."""

import gzip
from pathlib import Path

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

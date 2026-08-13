"""Byte preservation and append-only behavior for local raw capture."""

import gzip
import hashlib
from pathlib import Path

import httpx
import pytest
from prem_engine_api.config import Settings
from prem_engine_api.providers.raw_storage import (
    LocalRawResponseStore,
    R2RawResponseStore,
    RawResponseStorageError,
    create_raw_response_store,
)
from pydantic import SecretStr


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


def test_r2_store_uses_signed_conditional_writes_and_verifies_reads() -> None:
    captured: dict[str, object] = {}
    body = b'{"data":[]}'
    checksum = hashlib.sha256(body).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        captured[request.method] = request
        if request.method == "PUT":
            return httpx.Response(200, request=request)
        return httpx.Response(
            200,
            content=gzip.compress(body, mtime=0),
            headers={"x-amz-meta-sha256": checksum},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = R2RawResponseStore(
            endpoint_url="https://account.r2.cloudflarestorage.com",
            bucket_name="prem-engine-staging",
            access_key_id="access-key",
            secret_access_key="secret-key",
            http_client=client,
        )
        stored = store.store(provider="kickoffapi", body=body)
        assert store.read(stored.object_key, expected_checksum=stored.checksum) == body

    put_request = captured["PUT"]
    assert isinstance(put_request, httpx.Request)
    assert put_request.url.path.startswith("/prem-engine-staging/kickoffapi/")
    assert put_request.headers["if-none-match"] == "*"
    assert put_request.headers["x-amz-meta-sha256"] == checksum
    assert put_request.headers["authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=access-key/"
    )


def test_production_rejects_local_raw_storage() -> None:
    settings = Settings(
        app_env="production",
        database_ssl_required=True,
        api_origin_auth_enabled=True,
        api_origin_token=SecretStr("a" * 32),
    )

    with pytest.raises(RawResponseStorageError, match="must use R2"):
        create_raw_response_store(settings)


def test_r2_factory_requires_complete_credentials() -> None:
    settings = Settings(
        raw_response_store="r2",
        r2_account_id="account",
        r2_bucket_name="prem-engine-staging",
        r2_access_key_id="access",
        r2_secret_access_key=SecretStr("secret"),
    )

    store = create_raw_response_store(settings)
    assert isinstance(store, R2RawResponseStore)
    store.close()

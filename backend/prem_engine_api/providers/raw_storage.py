"""Append-only storage for byte-exact provider responses."""

from __future__ import annotations

import gzip
import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, Self, cast
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx

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


class R2RawResponseStore:
    """Private Cloudflare R2 implementation using signed S3-compatible requests."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket_name: str,
        access_key_id: str,
        secret_access_key: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        endpoint = endpoint_url.rstrip("/")
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("R2 endpoint must be an HTTPS origin without query or fragment")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket_name):
            raise ValueError("R2 bucket name is invalid")
        self._endpoint_url = endpoint
        self._host = parsed.netloc
        self._base_path = parsed.path.rstrip("/")
        self._bucket_name = bucket_name
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._http_client = http_client or httpx.Client(timeout=30, follow_redirects=False)
        self._owns_http_client = http_client is None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

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
        response = self._request(
            "PUT",
            stored.object_key,
            content=compressed,
            extra_headers={
                "content-type": "application/gzip",
                "if-none-match": "*",
                "x-amz-meta-sha256": stored.checksum,
            },
        )
        if response.status_code == 412:
            raise FileExistsError(f"raw response object already exists: {stored.object_key}")
        if not 200 <= response.status_code < 300:
            raise RawResponseStorageError(
                f"R2 raw response write failed with status {response.status_code}"
            )
        return stored

    def put_object(
        self,
        object_key: str,
        *,
        body: bytes,
        content_type: str,
        checksum: str,
        immutable: bool,
    ) -> None:
        """Write a checksum-labelled object through the shared signed R2 boundary."""

        headers = {
            "content-type": content_type,
            "x-amz-meta-sha256": checksum,
        }
        if immutable:
            headers["if-none-match"] = "*"
        response = self._request("PUT", object_key, content=body, extra_headers=headers)
        if immutable and response.status_code == 412:
            raise FileExistsError(f"R2 object already exists: {object_key}")
        if not 200 <= response.status_code < 300:
            raise RawResponseStorageError(
                f"R2 object write failed with status {response.status_code}"
            )

    def read(self, object_key: str, *, expected_checksum: str | None = None) -> bytes:
        response = self._request("GET", object_key)
        if response.status_code != 200:
            raise RawResponseStorageError(
                f"R2 raw response read failed with status {response.status_code}"
            )
        metadata_checksum = response.headers.get("x-amz-meta-sha256")
        required_checksum = expected_checksum or metadata_checksum
        if required_checksum is None:
            raise RawResponseStorageError("R2 raw response is missing checksum metadata")
        return _verified_body(
            response.content,
            object_key=object_key,
            expected_checksum=required_checksum,
        )

    def _request(
        self,
        method: str,
        object_key: str,
        *,
        content: bytes = b"",
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        canonical_uri = self._canonical_uri(object_key)
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(content).hexdigest()
        headers = {
            "host": self._host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            **(extra_headers or {}),
        }
        canonical_headers = "".join(
            f"{name.lower()}:{' '.join(value.strip().split())}\n"
            for name, value in sorted(headers.items())
        )
        signed_headers = ";".join(name.lower() for name in sorted(headers))
        canonical_request = "\n".join(
            [method, canonical_uri, "", canonical_headers, signed_headers, payload_hash]
        )
        scope = f"{date_stamp}/auto/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signing_key = self._signing_key(date_stamp)
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self._access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        try:
            return self._http_client.request(
                method,
                f"{self._endpoint_url}{canonical_uri}",
                headers=headers,
                content=content,
            )
        except httpx.HTTPError as error:
            raise RawResponseStorageError("R2 raw response request failed") from error

    def _canonical_uri(self, object_key: str) -> str:
        if not object_key or object_key.startswith("/") or ".." in Path(object_key).parts:
            raise ValueError("R2 object key must be relative and cannot traverse directories")
        parts = [self._bucket_name, *object_key.split("/")]
        encoded = "/".join(quote(part, safe="-_.~") for part in parts)
        return f"{self._base_path}/{encoded}" if self._base_path else f"/{encoded}"

    def _signing_key(self, date_stamp: str) -> bytes:
        date_key = hmac.new(
            f"AWS4{self._secret_access_key}".encode(), date_stamp.encode(), hashlib.sha256
        ).digest()
        region_key = hmac.new(date_key, b"auto", hashlib.sha256).digest()
        service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
        return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def create_raw_response_store(settings: Settings) -> RawResponseStore:
    """Build the configured store and reject ephemeral raw storage in production."""

    if settings.raw_response_store == "local":
        if settings.app_env.casefold() == "production":
            raise RawResponseStorageError("production raw response storage must use R2")
        return LocalRawResponseStore(settings.raw_data_root)

    required = {
        "R2_ACCOUNT_ID": settings.r2_account_id,
        "R2_BUCKET_NAME": settings.r2_bucket_name,
        "R2_ACCESS_KEY_ID": settings.r2_access_key_id,
        "R2_SECRET_ACCESS_KEY": (
            settings.r2_secret_access_key.get_secret_value()
            if settings.r2_secret_access_key is not None
            else None
        ),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RawResponseStorageError(
            f"R2 raw response storage is missing configuration: {', '.join(missing)}"
        )
    endpoint = settings.r2_endpoint_url or (
        f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    )
    return R2RawResponseStore(
        endpoint_url=endpoint,
        bucket_name=cast(str, settings.r2_bucket_name),
        access_key_id=cast(str, settings.r2_access_key_id),
        secret_access_key=cast(str, required["R2_SECRET_ACCESS_KEY"]),
    )

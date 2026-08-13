"""Verify a deployed public snapshot manifest and immutable object without exposing content."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen

MANIFEST_SCHEMA = "prem-engine-public-snapshot-manifest-v1"
LOGICAL_KEY_PATTERN = re.compile(r"[a-z0-9][a-z0-9/-]{0,199}")
OBJECT_KEY_PATTERN = re.compile(r"public/v1/objects/[a-z0-9][a-z0-9./-]*\.json")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
MAX_MANIFEST_BYTES = 8_192
MAX_PAYLOAD_BYTES = 2_000_000
MAX_FRESHNESS_SECONDS = 86_400
MAX_CACHE_SECONDS = 300
MAX_FUTURE_SKEW_SECONDS = 300


class SnapshotVerificationError(RuntimeError):
    """Raised when deployed snapshot content violates the public contract."""


@dataclass(frozen=True)
class VerifiedManifest:
    object_key: str
    checksum: str
    content_length: int
    lifecycle: str | None
    fresh: bool


def _parse_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise SnapshotVerificationError(f"{field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SnapshotVerificationError(f"{field} is not a valid timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotVerificationError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _required_integer(manifest: dict[str, Any], field: str, maximum: int) -> int:
    value = manifest.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > maximum:
        raise SnapshotVerificationError(f"{field} is outside the accepted range")
    return value


def verify_snapshot_bytes(
    manifest_body: bytes,
    object_body: bytes,
    *,
    logical_key: str,
    now: datetime,
    require_fresh: bool,
    expected_lifecycle: str | None,
) -> VerifiedManifest:
    if len(manifest_body) > MAX_MANIFEST_BYTES:
        raise SnapshotVerificationError("manifest exceeds the maximum size")
    try:
        manifest_value = json.loads(manifest_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SnapshotVerificationError("manifest is not valid UTF-8 JSON") from error
    if not isinstance(manifest_value, dict):
        raise SnapshotVerificationError("manifest must be a JSON object")
    manifest: dict[str, Any] = manifest_value
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise SnapshotVerificationError("manifest schema version is not supported")
    if manifest.get("logical_key") != logical_key:
        raise SnapshotVerificationError("manifest logical key does not match the request")

    object_key = manifest.get("object_key")
    if (
        not isinstance(object_key, str)
        or OBJECT_KEY_PATTERN.fullmatch(object_key) is None
        or ".." in object_key
    ):
        raise SnapshotVerificationError("manifest object key is unsafe")
    checksum = manifest.get("content_sha256")
    if not isinstance(checksum, str) or SHA256_PATTERN.fullmatch(checksum) is None:
        raise SnapshotVerificationError("manifest checksum is invalid")
    content_length = _required_integer(manifest, "content_length", MAX_PAYLOAD_BYTES)
    _required_integer(manifest, "cache_seconds", MAX_CACHE_SECONDS)

    published_at = _parse_datetime(manifest.get("published_at"), "published_at")
    expires_at = _parse_datetime(manifest.get("expires_at"), "expires_at")
    if expires_at <= published_at:
        raise SnapshotVerificationError("snapshot expiry must follow publication")
    if (expires_at - published_at).total_seconds() > MAX_FRESHNESS_SECONDS:
        raise SnapshotVerificationError("snapshot freshness window is too large")
    if (published_at - now).total_seconds() > MAX_FUTURE_SKEW_SECONDS:
        raise SnapshotVerificationError("snapshot publication time is in the future")
    fresh = now <= expires_at
    if require_fresh and not fresh:
        raise SnapshotVerificationError("snapshot is expired")

    if len(object_body) != content_length:
        raise SnapshotVerificationError("snapshot object length does not match the manifest")
    if hashlib.sha256(object_body).hexdigest() != checksum:
        raise SnapshotVerificationError("snapshot object checksum does not match the manifest")
    try:
        payload = json.loads(object_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SnapshotVerificationError("snapshot object is not valid UTF-8 JSON") from error

    lifecycle: str | None = None
    if logical_key.startswith("forecast/"):
        if not isinstance(payload, dict) or not isinstance(payload.get("lifecycle_state"), str):
            raise SnapshotVerificationError("forecast snapshot has no lifecycle state")
        lifecycle = payload["lifecycle_state"]
        if lifecycle in {"generating", "live"}:
            raise SnapshotVerificationError(
                "dynamic forecast state must not be served as a snapshot"
            )
        if lifecycle == "countdown":
            due_at = _parse_datetime(payload.get("prediction_due_at"), "prediction_due_at")
            if now >= due_at:
                raise SnapshotVerificationError(
                    "expired countdown must not be served as a snapshot"
                )
    if expected_lifecycle is not None and lifecycle != expected_lifecycle:
        raise SnapshotVerificationError(
            f"snapshot lifecycle {lifecycle!r} does not match {expected_lifecycle!r}"
        )
    return VerifiedManifest(object_key, checksum, content_length, lifecycle, fresh)


def _read_limited(url: str, maximum: int) -> bytes:
    request = Request(
        url, headers={"Accept": "application/json", "User-Agent": "prem-engine-acceptance/1"}
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310 - URL is validated HTTPS input
        final = urlsplit(response.geturl())
        requested = urlsplit(url)
        if (final.scheme, final.netloc) != (requested.scheme, requested.netloc):
            raise SnapshotVerificationError("snapshot request redirected to another origin")
        body = response.read(maximum + 1)
    if len(body) > maximum:
        raise SnapshotVerificationError("snapshot response exceeds the maximum size")
    return body


def _base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SnapshotVerificationError("snapshot base URL must be a bare HTTPS origin")
    return f"https://{parsed.netloc}/"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Public snapshot HTTPS origin")
    parser.add_argument("--logical-key", required=True, help="Snapshot logical key")
    parser.add_argument("--require-fresh", action="store_true")
    parser.add_argument("--expected-lifecycle")
    args = parser.parse_args()

    if LOGICAL_KEY_PATTERN.fullmatch(args.logical_key) is None or ".." in args.logical_key:
        raise SnapshotVerificationError("logical key is invalid")
    base_url = _base_url(args.base_url)
    encoded_key = quote(args.logical_key, safe="/")
    manifest_url = urljoin(base_url, f"public/v1/manifests/{encoded_key}.json")
    manifest_body = _read_limited(manifest_url, MAX_MANIFEST_BYTES)
    try:
        manifest_value = json.loads(manifest_body)
        object_key = manifest_value.get("object_key") if isinstance(manifest_value, dict) else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        object_key = None
    if (
        not isinstance(object_key, str)
        or OBJECT_KEY_PATTERN.fullmatch(object_key) is None
        or ".." in object_key
    ):
        raise SnapshotVerificationError("manifest object key is invalid")
    object_body = _read_limited(urljoin(base_url, object_key), MAX_PAYLOAD_BYTES)
    verified = verify_snapshot_bytes(
        manifest_body,
        object_body,
        logical_key=args.logical_key,
        now=datetime.now(UTC),
        require_fresh=args.require_fresh,
        expected_lifecycle=args.expected_lifecycle,
    )
    freshness = str(verified.fresh).lower()
    print(
        "snapshot_verified "
        f"logical_key={args.logical_key} bytes={verified.content_length} fresh={freshness}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SnapshotVerificationError as error:
        print(f"snapshot_verification_failed: {error}", file=sys.stderr)
        sys.exit(1)

"""Acceptance checks for the standalone deployed-snapshot verifier."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType


def _load_verifier() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts/deployment/verify_public_snapshot.py"
    spec = importlib.util.spec_from_file_location("deployment_snapshot_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VERIFIER = _load_verifier()


def _snapshot(lifecycle: str = "complete") -> tuple[bytes, bytes, datetime]:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    payload = json.dumps(
        {
            "lifecycle_state": lifecycle,
            "prediction_due_at": (now - timedelta(minutes=1)).isoformat(),
        },
        separators=(",", ":"),
    ).encode()
    manifest = {
        "schema_version": "prem-engine-public-snapshot-manifest-v1",
        "logical_key": "forecast/11111111-1111-4111-8111-111111111111",
        "object_key": "public/v1/objects/forecast/example/version.json",
        "published_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "content_length": len(payload),
        "cache_seconds": 300,
    }
    return json.dumps(manifest, separators=(",", ":")).encode(), payload, now


class SnapshotVerifierTests(unittest.TestCase):
    def test_accepts_fresh_complete_forecast(self) -> None:
        manifest, payload, now = _snapshot()

        verified = VERIFIER.verify_snapshot_bytes(
            manifest,
            payload,
            logical_key="forecast/11111111-1111-4111-8111-111111111111",
            now=now,
            require_fresh=True,
            expected_lifecycle="complete",
        )

        self.assertTrue(verified.fresh)
        self.assertEqual(verified.lifecycle, "complete")

    def test_rejects_checksum_mismatch(self) -> None:
        manifest, payload, now = _snapshot()
        mutated_payload = payload.replace(b'"complete"', b'"xomplete"', 1)

        with self.assertRaisesRegex(VERIFIER.SnapshotVerificationError, "checksum"):
            VERIFIER.verify_snapshot_bytes(
                manifest,
                mutated_payload,
                logical_key="forecast/11111111-1111-4111-8111-111111111111",
                now=now,
                require_fresh=True,
                expected_lifecycle="complete",
            )

    def test_rejects_dynamic_forecast_snapshot(self) -> None:
        manifest, payload, now = _snapshot("live")

        with self.assertRaisesRegex(VERIFIER.SnapshotVerificationError, "dynamic forecast"):
            VERIFIER.verify_snapshot_bytes(
                manifest,
                payload,
                logical_key="forecast/11111111-1111-4111-8111-111111111111",
                now=now,
                require_fresh=True,
                expected_lifecycle=None,
            )

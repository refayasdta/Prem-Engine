"""Versioned public snapshot manifest contract."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, PositiveInt, field_validator, model_validator

MANIFEST_SCHEMA_VERSION: Literal["prem-engine-public-snapshot-manifest-v1"] = (
    "prem-engine-public-snapshot-manifest-v1"
)
_OBJECT_KEY = re.compile(r"^public/v1/objects/[a-z0-9][a-z0-9./-]*\.json$")


class PublicSnapshotManifest(BaseModel):
    schema_version: Literal["prem-engine-public-snapshot-manifest-v1"] = MANIFEST_SCHEMA_VERSION
    logical_key: str
    object_key: str
    published_at: datetime
    expires_at: datetime
    content_sha256: str
    content_length: PositiveInt
    cache_seconds: PositiveInt

    @field_validator("logical_key")
    @classmethod
    def validate_logical_key(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9/-]{0,199}", value) or ".." in value:
            raise ValueError("snapshot logical key is invalid")
        return value

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        if not _OBJECT_KEY.fullmatch(value) or ".." in value:
            raise ValueError("snapshot object key is invalid")
        return value

    @field_validator("content_sha256")
    @classmethod
    def validate_checksum(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("snapshot checksum must be lowercase SHA256")
        return value

    @model_validator(mode="after")
    def validate_times(self) -> PublicSnapshotManifest:
        for value in (self.published_at, self.expires_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("snapshot timestamps must include a timezone")
        if self.expires_at <= self.published_at:
            raise ValueError("snapshot expiry must follow publication")
        return self

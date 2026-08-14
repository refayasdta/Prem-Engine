"""add local installation metadata

Revision ID: a6f2c9d4137b
Revises: f5c1b4d8a9e2
Create Date: 2026-08-14 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6f2c9d4137b"
down_revision: str | None = "f5c1b4d8a9e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "local_installations",
        sa.Column("installation_uuid", sa.Uuid(), nullable=False),
        sa.Column("singleton_key", sa.SmallInteger(), nullable=False),
        sa.Column("bootstrap_version", sa.String(length=80), nullable=False),
        sa.Column("goal_model_version", sa.String(length=120), nullable=False),
        sa.Column("goal_model_sha256", sa.String(length=64), nullable=False),
        sa.Column("statistics_model_version", sa.String(length=120), nullable=False),
        sa.Column("statistics_model_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "initialized_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(goal_model_sha256) = 64 AND length(statistics_model_sha256) = 64",
            name=op.f("ck_local_installations_model_checksums_are_sha256"),
        ),
        sa.CheckConstraint(
            "singleton_key = 1", name=op.f("ck_local_installations_singleton_key_is_one")
        ),
        sa.PrimaryKeyConstraint("installation_uuid"),
        sa.UniqueConstraint("singleton_key"),
    )


def downgrade() -> None:
    op.drop_table("local_installations")

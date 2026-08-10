"""add automated forecast lifecycle

Revision ID: d72d120a14aa
Revises: c81b946f0d1a
Create Date: 2026-08-10 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d72d120a14aa"
down_revision: str | None = "c81b946f0d1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_snapshots",
        sa.Column("feature_snapshot_uuid", sa.Uuid(), nullable=False),
        sa.Column("prediction_version_uuid", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("feature_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_source_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feature_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["prediction_version_uuid"],
            ["prediction_versions.prediction_version_uuid"],
            name=op.f("fk_feature_snapshots_prediction_version_uuid_prediction_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("feature_snapshot_uuid", name=op.f("pk_feature_snapshots")),
        sa.UniqueConstraint(
            "prediction_version_uuid",
            name=op.f("uq_feature_snapshots_prediction_version_uuid"),
        ),
    )
    op.add_column(
        "stored_simulations",
        sa.Column("presentation_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stored_simulations",
        sa.Column(
            "presentation_duration_seconds",
            sa.SmallInteger(),
            server_default="60",
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE stored_simulations AS simulation
        SET presentation_started_at = prediction.locked_at
        FROM prediction_versions AS prediction
        WHERE prediction.prediction_version_uuid = simulation.prediction_version_uuid
        """
    )
    op.execute(
        "UPDATE stored_simulations SET presentation_started_at = now() "
        "WHERE presentation_started_at IS NULL"
    )
    op.alter_column("stored_simulations", "presentation_started_at", nullable=False)
    op.create_check_constraint(
        op.f("ck_stored_simulations_positive_presentation_duration"),
        "stored_simulations",
        "presentation_duration_seconds > 0",
    )
    op.add_column("job_runs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_runs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))

    op.execute("DROP TRIGGER trg_predicted_lineup_immutable ON predicted_lineups")
    op.execute("DROP TRIGGER trg_stored_simulation_immutable ON stored_simulations")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_prediction_artifact() RETURNS trigger AS $$
        DECLARE
            owner_state prediction_state;
            owner_uuid uuid;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                owner_uuid := OLD.prediction_version_uuid;
            ELSE
                owner_uuid := NEW.prediction_version_uuid;
            END IF;
            SELECT state INTO owner_state
            FROM prediction_versions
            WHERE prediction_version_uuid = owner_uuid;
            IF owner_state IN ('active_locked', 'evaluated', 'voided') THEN
                RAISE EXCEPTION 'artifacts belonging to locked predictions are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_predicted_lineup_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON predicted_lineups
        FOR EACH ROW EXECUTE FUNCTION protect_prediction_artifact()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_stored_simulation_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON stored_simulations
        FOR EACH ROW EXECUTE FUNCTION protect_prediction_artifact()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_feature_snapshot_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON feature_snapshots
        FOR EACH ROW EXECUTE FUNCTION protect_prediction_artifact()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_feature_snapshot_immutable ON feature_snapshots")
    op.execute("DROP TRIGGER trg_stored_simulation_immutable ON stored_simulations")
    op.execute("DROP TRIGGER trg_predicted_lineup_immutable ON predicted_lineups")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_prediction_artifact() RETURNS trigger AS $$
        DECLARE owner_state prediction_state;
        BEGIN
            SELECT state INTO owner_state
            FROM prediction_versions
            WHERE prediction_version_uuid = OLD.prediction_version_uuid;
            IF owner_state IN ('active_locked', 'evaluated', 'voided') THEN
                RAISE EXCEPTION 'artifacts belonging to locked predictions are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_predicted_lineup_immutable
        BEFORE UPDATE OR DELETE ON predicted_lineups
        FOR EACH ROW EXECUTE FUNCTION protect_prediction_artifact()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_stored_simulation_immutable
        BEFORE UPDATE OR DELETE ON stored_simulations
        FOR EACH ROW EXECUTE FUNCTION protect_prediction_artifact()
        """
    )
    op.drop_column("job_runs", "finished_at")
    op.drop_column("job_runs", "started_at")
    op.drop_constraint(
        op.f("ck_stored_simulations_positive_presentation_duration"),
        "stored_simulations",
        type_="check",
    )
    op.drop_column("stored_simulations", "presentation_duration_seconds")
    op.drop_column("stored_simulations", "presentation_started_at")
    op.drop_table("feature_snapshots")

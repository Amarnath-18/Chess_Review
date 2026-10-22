"""analyze-all batches and cancellable jobs

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_jobs_status", "analysis_jobs", type_="check")
    op.create_check_constraint(
        "ck_jobs_status",
        "analysis_jobs",
        "status IN ('queued','running','completed','failed','cancelled')",
    )
    op.create_table(
        "analysis_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('running','completed','cancelled')", name="ck_batches_status"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_batches_owner_id", "analysis_batches", ["owner_id"])
    op.create_index(
        "uq_batches_one_running_per_owner",
        "analysis_batches",
        ["owner_id"],
        unique=True,
        postgresql_where="status = 'running'",
    )
    op.create_table(
        "batch_games",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("state", sa.String(10), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("message", sa.String(300), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending','queued','done','failed','skipped','cancelled')",
            name="ck_batch_games_state",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["analysis_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("batch_id", "game_id"),
    )
    op.create_index("ix_batch_games_batch_state", "batch_games", ["batch_id", "state"])


def downgrade() -> None:
    op.drop_table("batch_games")
    op.drop_table("analysis_batches")
    op.execute("UPDATE analysis_jobs SET status = 'failed' WHERE status = 'cancelled'")
    op.drop_constraint("ck_jobs_status", "analysis_jobs", type_="check")
    op.create_check_constraint(
        "ck_jobs_status", "analysis_jobs", "status IN ('queued','running','completed','failed')"
    )

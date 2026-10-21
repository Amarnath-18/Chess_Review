"""excellent move class and multi-line engine output

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

OLD = "('brilliant','great','best','good','inaccuracy','mistake','blunder')"
NEW = "('brilliant','great','best','excellent','good','inaccuracy','mistake','blunder')"


def upgrade() -> None:
    op.add_column(
        "analysis_positions", sa.Column("lines", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.drop_constraint("ck_pos_classification", "analysis_positions", type_="check")
    op.create_check_constraint(
        "ck_pos_classification",
        "analysis_positions",
        f"classification IS NULL OR classification IN {NEW}",
    )


def downgrade() -> None:
    op.execute("UPDATE analysis_positions SET classification = 'good' WHERE classification = 'excellent'")
    op.drop_constraint("ck_pos_classification", "analysis_positions", type_="check")
    op.create_check_constraint(
        "ck_pos_classification",
        "analysis_positions",
        f"classification IS NULL OR classification IN {OLD}",
    )
    op.drop_column("analysis_positions", "lines")

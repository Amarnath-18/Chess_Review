"""remembered Chess.com / Lichess accounts

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "linked_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("username", sa.String(30), nullable=False),
        sa.Column("username_key", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("source IN ('chesscom','lichess')", name="ck_sources_source"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_linked_sources_owner_id", "linked_sources", ["owner_id"])
    op.create_index(
        "uq_sources_owner_account",
        "linked_sources",
        ["owner_id", "source", "username_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("linked_sources")

"""puzzle trainer

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-24
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # which analysis run of a game has already been mined for puzzles
    op.add_column("games", sa.Column("puzzles_scanned_run", sa.Uuid(), nullable=True))
    op.create_table(
        "puzzles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("ply", sa.SmallInteger(), nullable=False),
        sa.Column("fen", sa.String(100), nullable=False),
        sa.Column("best_uci", sa.String(8), nullable=False),
        sa.Column("accepted_uci", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("played_uci", sa.String(8), nullable=False),
        sa.Column("loss_pct", sa.Float(), nullable=False),
        sa.Column("line", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("box", sa.SmallInteger(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_puzzles_owner_id", "puzzles", ["owner_id"])
    op.create_index("uq_puzzles_game_ply", "puzzles", ["game_id", "ply"], unique=True)
    op.create_index("ix_puzzles_owner_due", "puzzles", ["owner_id", "due_at"])
    op.create_table(
        "puzzle_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("puzzle_id", sa.Uuid(), nullable=False),
        sa.Column("answered_uci", sa.String(8), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["puzzle_id"], ["puzzles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_puzzle_attempts_puzzle_id", "puzzle_attempts", ["puzzle_id"])


def downgrade() -> None:
    op.drop_table("puzzle_attempts")
    op.drop_table("puzzles")
    op.drop_column("games", "puzzles_scanned_run")

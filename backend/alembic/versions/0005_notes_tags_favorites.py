"""favourites, notes and tags on games

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "games", sa.Column("favorite", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("games", sa.Column("note", sa.String(5000), nullable=True))
    op.create_table(
        "game_tags",
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("tag", sa.String(30), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("game_id", "tag"),
    )
    op.create_index("ix_game_tags_tag", "game_tags", ["tag"])
    op.create_table(
        "game_move_notes",
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("ply", sa.SmallInteger(), nullable=False),
        sa.Column("text", sa.String(2000), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("game_id", "ply"),
    )


def downgrade() -> None:
    op.drop_table("game_move_notes")
    op.drop_index("ix_game_tags_tag", table_name="game_tags")
    op.drop_table("game_tags")
    op.drop_column("games", "note")
    op.drop_column("games", "favorite")

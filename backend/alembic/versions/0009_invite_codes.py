"""per-friend invite codes

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.add_column("users", sa.Column("invite_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_users_invite", "users", "invite_codes", ["invite_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_users_invite_id", "users", ["invite_id"])


def downgrade() -> None:
    op.drop_index("ix_users_invite_id", table_name="users")
    op.drop_constraint("fk_users_invite", "users", type_="foreignkey")
    op.drop_column("users", "invite_id")
    op.drop_table("invite_codes")

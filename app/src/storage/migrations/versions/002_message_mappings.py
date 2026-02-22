"""Add message_mappings table

Revision ID: 002_message_mappings
Revises: 001_initial
Create Date: 2026-02-14
"""
from alembic import op
import sqlalchemy as sa

revision = "002_message_mappings"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("user_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("author_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["author_message_id"], ["author_messages.id"]),
        sa.UniqueConstraint("chat_id", "message_id", name="uq_mapping_chat_message"),
    )
    op.create_index("ix_message_mappings_chat_id", "message_mappings", ["chat_id"])


def downgrade() -> None:
    op.drop_table("message_mappings")

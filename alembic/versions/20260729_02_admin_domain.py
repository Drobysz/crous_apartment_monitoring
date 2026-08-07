"""Add administration identities, sessions, audits, and transaction mode.

Revision ID: 20260729_02_admin
Revises: 20260729_01_base
Create Date: 2026-07-29
"""

import sqlalchemy as sa

from alembic import op

revision = "20260729_02_admin"
down_revision = "20260729_01_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchases",
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_purchases_is_test", "purchases", ["is_test"])
    op.alter_column("purchases", "is_test", server_default=None)

    op.create_table(
        "admins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("username", sa.String(length=33), nullable=False),
        sa.Column("username_key", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("role IN ('admin', 'superadmin')", name="ck_admins_role"),
        sa.PrimaryKeyConstraint("id", name="pk_admins"),
    )
    op.create_index("ix_admins_role", "admins", ["role"])
    op.create_index("ix_admins_is_active", "admins", ["is_active"])
    op.create_index("ix_admins_username_key", "admins", ["username_key"], unique=True)

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admins.id"],
            name="fk_admin_sessions_admin_id_admins",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_sessions"),
    )
    op.create_index("ix_admin_sessions_admin_id", "admin_sessions", ["admin_id"])
    op.create_index(
        "ix_admin_sessions_refresh_token_hash",
        "admin_sessions",
        ["refresh_token_hash"],
        unique=True,
    )
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])

    op.create_table(
        "admin_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_admin_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["actor_admin_id"],
            ["admins.id"],
            name="fk_admin_audits_actor_admin_id_admins",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_audits"),
    )
    op.create_index("ix_admin_audits_actor_admin_id", "admin_audits", ["actor_admin_id"])
    op.create_index("ix_admin_audits_action", "admin_audits", ["action"])


def downgrade() -> None:
    op.drop_index("ix_admin_audits_action", table_name="admin_audits")
    op.drop_index("ix_admin_audits_actor_admin_id", table_name="admin_audits")
    op.drop_table("admin_audits")
    op.drop_index("ix_admin_sessions_expires_at", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_refresh_token_hash", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_admin_id", table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.drop_index("ix_admins_username_key", table_name="admins")
    op.drop_index("ix_admins_is_active", table_name="admins")
    op.drop_index("ix_admins_role", table_name="admins")
    op.drop_table("admins")
    op.drop_index("ix_purchases_is_test", table_name="purchases")
    op.drop_column("purchases", "is_test")

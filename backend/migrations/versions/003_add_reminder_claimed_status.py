"""add reminder claimed status

Revision ID: 003_add_reminder_claimed_status
Revises: 002_add_proposal_expires_at
Create Date: 2026-11-06 14:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "003_add_reminder_claimed_status"
down_revision: str | None = "002_add_proposal_expires_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Update chk_reminder_status to include 'claimed'
    with op.batch_alter_table("reminders", recreate="always") as batch_op:
        batch_op.drop_constraint("chk_reminder_status", type_="check")
        batch_op.create_check_constraint(
            "chk_reminder_status",
            "status IN ('scheduled', 'claimed', 'retrying', 'delivered', 'needs_attention', 'cancelled')",
        )


def downgrade() -> None:
    with op.batch_alter_table("reminders", recreate="always") as batch_op:
        batch_op.drop_constraint("chk_reminder_status", type_="check")
        batch_op.create_check_constraint(
            "chk_reminder_status",
            "status IN ('scheduled', 'retrying', 'delivered', 'needs_attention', 'cancelled')",
        )

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
    with op.batch_alter_table("reminders", recreate="always"):
        pass


def downgrade() -> None:
    with op.batch_alter_table("reminders", recreate="always"):
        pass

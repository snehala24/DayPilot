# DayPilot — Backend Schema
Nov 3, 2026 · @SNEHALA

The PostgreSQL schema makes commitments, proposals and audit events first-class rows, with constraints that make duplicate reminders and unapproved writes impossible.

## Conventions
- Primary keys are UUIDs; every table has `created_at` and `updated_at` as `timestamptz` in UTC.
- Every user-owned table carries `user_id`, even though the MVP is single-user, so multi-user support needs no migration.
- Statuses are PostgreSQL enums or CHECK constraints, not free text.
- Flexible payloads (proposal details, audit results) are `jsonb` validated by Pydantic before insert.
- Nothing is hard-deleted: commitments are `dropped`, proposals are `expired` or `rejected`, and audit events are append-only.
- Times that carry meaning for the person store the IANA zone name next to the UTC instant.

## Core tables
- **users**: `id`, `email`, `timezone` (IANA), `created_at`
- **projects**: `id`, `user_id`, `name`, `context` (text), `status`
- **notes**: `id`, `user_id`, `project_id`, `raw_text`, `captured_at`
- **commitments**: `id`, `user_id`, `project_id`, `title`, `description`, `owner`, `due_at`, `due_tz`, `priority` (1 to 4), `status` (`open`, `scheduled`, `in_progress`, `done`, `dropped`), `estimate_minutes`, `source_note_id`, `source_span` (jsonb), `extraction_confidence`, `follow_up_rule` (jsonb)

## Calendar and planning tables
- **commitment_dependencies**: `commitment_id`, `depends_on_id`; primary key on both; check that the two ids differ
- **preferences**: `id`, `user_id`, `key`, `value` (jsonb), unique on `(user_id, key)`
- **calendar_events**: `id`, `user_id`, `source` (`simulated`, `google`), `external_id`, `title`, `starts_at`, `ends_at`, `tz`, `is_fixed`, `recurrence_rule`; unique on `(source, external_id)`
- **plans**: `id`, `user_id`, `plan_date`, `status` (`draft`, `proposed`, `accepted`, `superseded`), `constraints_report` (jsonb), `generated_at`
- **plan_items**: `id`, `plan_id`, `commitment_id`, `starts_at`, `ends_at`, `locked`; check that starts_at is before ends_at
- **conflicts**: `id`, `plan_id`, `commitment_id`, `event_id`, `kind`, `alternatives` (jsonb), `resolved_by_proposal_id`

## Action tables
- **proposals**: `id`, `user_id`, `commitment_id`, `kind` (`calendar_create`, `calendar_update`, `calendar_delete`, `send_message`, `reschedule`), `payload` (jsonb), `reason`, `status` (`pending`, `approved`, `rejected`, `executed`, `verified`, `failed`, `expired`), `idempotency_key`, `result` (jsonb), `recovery_status`, `expires_at`
- **approvals**: `id`, `proposal_id`, `decision` (`approved`, `rejected`), `edited_payload` (jsonb), `decided_by`, `decided_at`, `reason`
- **reminders**: `id`, `commitment_id`, `due_at`, `channel`, `status` (`scheduled`, `claimed`, `retrying`, `delivered`, `needs_attention`, `cancelled`), `attempt_count`, `idempotency_key`
- **delivery_attempts**: `id`, `reminder_id`, `attempted_at`, `outcome`, `error`
- **audit_events**: `id`, `user_id`, `entity_type`, `entity_id`, `action`, `actor` (`person`, `agent`, `system`), `payload` (jsonb), `result` (jsonb), `recovery_status`, `created_at`

## Constraints, indexes and idempotency
- Unique index on `proposals.idempotency_key` and on `reminders.idempotency_key`.
- Unique index on `approvals.proposal_id`.
- Rejection of moving a proposal to executed unless an approval with decision `approved` exists for it.
- `audit_events` is append-only.
- Non-overlap of planned blocks and check that `starts_at < ends_at`.
- Self-dependency and cycle rejection for commitments.
- Indexes:
  - `commitments (user_id, status, due_at)`
  - `reminders (due_at)` where status is scheduled or retrying
  - `calendar_events (starts_at, ends_at)`
  - `audit_events (entity_type, entity_id, created_at)`

# Ground rules for Cursor and other coding LLMs

Copy this section into .cursor/rules or AGENTS.md in the repository.

## Hard rules (never break)

1. Never add a code path that writes to a calendar, sends a message or deletes user data without an approved proposal. External-write adapters are called only from the executor module.
2. Never weaken, skip or mock the approval gate in a test that claims to verify safety.
3. Never put secrets, tokens or personal data in code, fixtures, logs or traces.
4. Never let model output reach a tool, the database or the UI without Pydantic validation.
5. Never change a database schema without a migration and an updated schema doc.

## Conventions

- Python 3.11+, full type hints, Pydantic models for every boundary. Frontend is TypeScript with strict mode.
- Store all times in UTC with the IANA time zone alongside; never use naive datetimes.
- Every consequential action has an idempotency key and an audit event.
- Hard constraints live in deterministic code in the planner module, not in prompts.
- Keep the model client behind the LLMClient interface so a fake client can run in tests.
- Prefer small, reviewable changes; one concern per commit.

## Before finishing any task

- Run pytest and the safety suite; both must pass.
- Add or update a test for each behavior change, including a failure case.
- If a requirement is ambiguous or touches approval, scheduling or permissions, stop and ask rather than guess.
- State which files changed and which tests prove it.

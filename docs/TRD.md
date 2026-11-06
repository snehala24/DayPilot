# DayPilot — TRD and Architecture
Nov 3, 2026 · @SNEHALA

DayPilot runs as a FastAPI service with a LangGraph workflow, PostgreSQL as the source of truth, and an approval gate in front of every external write.

## Technical requirements

### Functional
- Store commitments, notes, preferences and project context durably in PostgreSQL.
- Extract structured commitments from free text with a schema-validated model output.
- Plan a day with deterministic constraint checks; the model may rank and explain but never overrides a hard constraint.
- Queue every external write as a proposal and execute it only after an approval record exists.
- Schedule reminders with idempotency keys, delivery status and bounded retries.
- Record an audit event for every request, approval, tool result and recovery.

### Non-functional
- Unauthorized write rate is 0 in the automated suite, including approval-bypass tests.
- Every scheduled job is safe to run twice.
- Time is stored in UTC with the person's IANA time zone alongside.
- Each workflow emits a trace covering latency, tool calls and model usage.

### Constraints
- One-week MVP, single user, simulated calendar first.
- Gemini API via the official free tier if eligible; the model client sits behind an interface so it can be swapped.

## Tech stack
- **API**: Python, FastAPI
- **Validation**: Pydantic
- **Workflow**: LangGraph
- **Database**: PostgreSQL / SQLite (with full constraints & foreign keys)
- **Jobs**: APScheduler
- **Model**: Gemini API / Fake client interface
- **Calendar**: Simulated calendar, then Google Calendar OAuth read-only, then writes
- **Frontend**: Next.js, TypeScript
- **Tests**: pytest
- **Tracing**: LangSmith or OpenTelemetry

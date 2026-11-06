# DayPilot — Implementation Plan
Nov 3, 2026 · @SNEHALA

The MVP is built in seven days, simulated calendar first, with every day ending in a passing test rather than a feature demo.

## Day-by-Day Plan
- **Day 1**: Repo, FastAPI skeleton, PostgreSQL/SQLite, SQLAlchemy models and migrations for core and action tables, seed data. (Exit check: Migrations apply cleanly; model tests pass).
- **Day 2**: Extraction node with Pydantic schema, LLMClient interface with a fake and a Gemini client, confirm endpoint. (Exit check: 20 labeled synthetic notes produce precision, recall, and F1 report).
- **Day 3**: Simulated calendar, planner with hard constraints, conflict detection with alternatives. (Exit check: Constraint tests show 0 violations; every seeded conflict is detected).
- **Day 4**: Proposals, approvals, executor, verification, audit events, approval trigger. (Exit check: Approved proposal is verified by read-back; bypass tests cannot write).
- **Day 5**: Reminder scheduler, idempotency keys, retry with backoff, delivery attempts. (Exit check: Injected failure then retry yields exactly one delivered reminder).
- **Day 6**: Next.js screens: Today, Inbox, Approvals, Commitments, History. (Exit check: Full loop runs in the browser).
- **Day 7**: Daily review, tracing, evaluation harness, demo script, README. (Exit check: Acceptance demo runs end to end; metrics report is generated).

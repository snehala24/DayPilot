# DayPilot — PRD
Nov 3, 2026 · @SNEHALA

DayPilot is a personal admin agent that turns messy requests into tracked commitments, plans around fixed events, and never writes to a calendar or sends a message without approval.

## Problem and users
Personal tasks, notes, calendar events and reminders live in separate places. Chat assistants can suggest a plan, but they do not reliably keep commitments, catch schedule conflicts or finish follow-up actions safely.

**Target users**: students, independent builders, job seekers and busy people running personal projects.

**Differentiator**: commitments are first-class objects with a due date, dependencies, provenance, status and follow-up rules. A task counts as remembered only when it is stored, actionable and verified after execution. Memory, tasks, calendar and reminders already exist in open-source assistants, so the defensible angle is constraint-validated planning, follow-through, permission-scoped integrations and measured evaluation of missed or wrong actions.

## Goals and non-goals
The MVP proves one loop end to end: text in, commitment stored, plan proposed, approval given, action verified.

### Goals
- Turn natural-language requests and messy notes into structured, persistent commitments.
- Produce a daily plan that respects deadlines, dependencies and fixed calendar events.
- Detect conflicts and propose alternatives instead of silently moving anything.
- Send reminders exactly once, with delivery status and safe retry.
- Gate every external write behind explicit approval, and record it in an audit history.

### Non-goals for the MVP
- Live Google Calendar writes (read-only mode comes first, OAuth after that).
- Multi-user teams, sharing or collaboration.
- Autonomous actions without approval.
- Claiming novelty for memory, tasks or reminders alone.

## User journeys
1. **Capture**: The person pastes messy notes or types a request.
   - The agent extracts tasks, owners, due dates, priorities and dependencies.
   - It shows the extracted commitments with their source text.
   - Anything ambiguous (a date, a time zone) becomes a question, not a guess.
   - The person confirms, and the commitments are saved.
2. **Plan the day**: The person asks for today's plan.
   - The planner places commitments around fixed events, deadlines and dependencies.
   - It lists any conflicts and offers at least one alternative for each.
   - The plan arrives as a proposal, with nothing written anywhere yet.
3. **Approve and act**: The person reviews a proposed calendar entry.
   - They approve or reject it in the approval queue.
   - On approval the system writes it, then reads it back to verify it exists.
   - The audit history records request, approval, tool result and recovery status.
4. **Follow up**: A reminder comes due.
   - The scheduler sends it once, keyed by an idempotency key.
   - If delivery fails, it retries without creating a duplicate.
   - Delivery status is visible on the commitment.
5. **Daily review**: The agent lists overdue commitments and asks what should change: reschedule, drop, split or mark done.

## Feature specs
| Feature | Phase | Acceptance criterion |
| :--- | :--- | :--- |
| Persistent store for tasks, notes, commitments, preferences, project context | MVP | Data survives a restart and every commitment keeps its source text |
| Text-to-commitment extraction | MVP | Task, owner, due date, priority and dependency fields are filled or flagged as unknown |
| Constraint-aware day planner | MVP | Zero violations of fixed events, deadlines and dependencies in the test suite |
| Conflict detection and alternatives | MVP | Every conflict is reported with at least one proposed alternative; nothing moves silently |
| Approval queue | MVP | No external write exists without an approved record |
| Simulated calendar with read-only integration | MVP | Planner reads events from the simulated calendar; one approved write is verified by reading it back |
| Reminder scheduler with idempotency keys | MVP | A forced failure and retry produces exactly one delivered reminder |
| Audit history | MVP | Each action shows request, approval, tool result and recovery status |
| Daily review of overdue commitments | MVP | Overdue items are listed and the person is asked what should change |
| Google Calendar OAuth | Post-MVP | Starts only after read-only mode passes all tests |
| Message sending | Post-MVP | Uses the same approval queue as calendar writes |

## Success metrics
- Extraction: F1 ≥ 0.85 on synthetic benchmark
- Planning hard-constraint violation rate: 0
- Seeded conflicts detected: 100%
- Duplicate action rate: 0
- Reminder delivery success after retry: ≥ 99% in simulation
- Overdue commitment recall in daily review: 100%
- Unauthorized write rate (including approval-bypass tests): 0

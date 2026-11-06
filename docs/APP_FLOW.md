# DayPilot — App Flow
Nov 3, 2026 · @SNEHALA

Every flow ends the same way: the agent proposes, the person approves, the system acts, then verifies and records the result.

## Proposal lifecycle
`pending` -> `approved` -> `executed` -> `verified`
Alternative terminal states: `rejected`, `expired`, `failed`.
Only a verified proposal counts as done.

## Five Key Flows
1. **Flow 1: Capture and Extract**: Paste notes in Inbox -> Extract structured commitments -> Review source text highlights & clarify unknown fields -> Confirm to save.
2. **Flow 2: Plan the Day and Resolve a Conflict**: Open Today -> Planner places commitments around fixed events respecting deadlines & dependencies -> Conflicts flagged with 2-3 alternatives -> Pick alternative to create a proposal.
3. **Flow 3: Approve a Calendar Write and Verify It**: Review proposal in Approvals -> Approve -> Executor calls calendar adapter with idempotency key -> Read-back verification -> Transition to `verified`.
4. **Flow 4: Reminders and Daily Review**: Scheduler claims due reminders -> Idempotent dispatch -> Bounded backoff retry on failure -> Delivery status updated.
5. **Flow 5: Daily Review**: Each morning agent lists overdue/due commitments -> Review actions (reschedule, split, drop, done) -> Audit event recorded.

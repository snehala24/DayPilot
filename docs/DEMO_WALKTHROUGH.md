# DayPilot — End-to-End Demo Walkthrough Guide

This document describes how to execute and verify the complete 10-step DayPilot MVP user story, demonstrating its core safety invariant:

> **The agent proposes. The person approves. The system executes and verifies.**

All simulated external systems (Google Calendar, Twilio/Push Notifications) are clearly identified as **(SIMULATED)**.

---

## Quick Automated Runner

You can execute the entire 10-step sequence with a single command:

```bash
python demo/run_demo_scenario.py
```

---

## 10-Step Interactive Walkthrough

### Step 1: User Submits a Messy Note
* **UI Screen**: `/inbox`
* **Input Text**:
  ```text
  Prep executive summary for board meeting next Friday. Sync with Priya first for budget numbers. Takes about 90 mins.
  ```
* **What Happens**:
  - The note is saved to the `notes` table with a timestamp for audit provenance.
  - **Hard Safety Rule**: Zero commitments are confirmed or saved to the `commitments` table at this stage.

### Step 2: Extraction Engine Parses Commitments & Identifies Uncertainty
* **API Call**: `POST /api/v1/inputs`
* **Observation**:
  - DayPilot extracts candidate: `Prepare executive summary for board meeting`.
  - Distinguishes stated facts from uncertain fields: flags `due_date` and `due_time` as ambiguous.
  - Generates clarifying question: *"Which date did you intend for 'next friday'?"*.
  - `can_confirm_all` is `false`, requiring human clarification.

### Step 3: User Resolves Ambiguity & Confirms Commitment
* **UI Screen**: `/inbox` (Review Drawer)
* **User Action**:
  - Selects explicit date: `2026-11-20`, time: `16:00 Asia/Kolkata`.
  - Confirms priority: `P1`, duration: `90 minutes`.
* **API Call**: `POST /api/v1/commitments/confirm`
* **Observation**:
  - Commitment is saved to persistent SQLite/PostgreSQL storage with status `open`.
  - Dependency on prerequisite task is mapped.

### Step 4: Deterministic Planner Builds Daily Schedule
* **UI Screen**: `/` (Today)
* **API Call**: `POST /api/v1/plans`
* **Observation**:
  - The planner computes non-overlapping focus blocks respecting working hours (09:00 - 18:00), lunch break (13:00 - 14:00), and fixed calendar meetings.
  - Invariant: LLMs never decide whether a schedule satisfies hard constraints; hard constraints are validated 100% deterministically in Python.

### Step 5: Conflict Appears with Safe Alternatives
* **UI Screen**: `/` (Today - Visible Conflicts Card)
* **Trigger**: A fixed calendar event (e.g. `Emergency Board Briefing`) blocks the planned time.
* **Observation**:
  - Conflict is visibly highlighted as `overlap_fixed_event`.
  - The agent **never** silently moves or shortens the user's task.
  - 3 non-destructive alternatives are offered:
    1. *Reschedule to next available business day*
    2. *Split into 45m and 45m blocks preserving total effort*
    3. *Extend deadline by 24 hours*
  - Each alternative explicitly displays `Requires Approval`.

### Step 6: Proposal Generation & Human Approval Gate
* **UI Screen**: `/approvals`
* **Action**: User clicks "Propose Alternative" or creates a calendar proposal.
* **API Call**: `POST /api/v1/proposals`
* **Observation**:
  - Proposal is placed in the approval queue with status `pending` and an expiration timer.
  - **Hard Safety Boundary**: Zero calendar events are created while the proposal is pending.

### Step 7 & 8: Human Approval, Isolated Execution & Read-Back Verification
* **UI Screen**: `/approvals`
* **Action**: User reviews the exact JSON payload, optionally edits time/title, and clicks "Approve".
* **API Call**: `POST /api/v1/proposals/{id}/approve`
* **Observation**:
  - The backend re-validates the approved payload using Pydantic.
  - Only the isolated `ProposalExecutor` invokes the write adapter.
  - `SimulatedCalendarWriteAdapter` creates the event in the simulated calendar store.
  - Executor immediately performs a read-back fetch to confirm exact title and timestamp match.
  - Status transitions to `verified`. If read-back failed, status would transition to `failed: needs_attention`.

### Step 9: User Schedules and Dispatches a Simulated Reminder
* **UI Screen**: `/commitments`
* **API Call**: `POST /api/v1/reminders`
* **Observation**:
  - Reminder is scheduled with an idempotency key.
  - Worker acquires lease via atomic CAS claiming.
  - Dispatched via `SimulatedNotificationAdapter` **(SIMULATED)**.
  - Delivery attempt is permanently audited.

### Step 10: History & Daily Review Reflect Verified State
* **UI Screen**: `/history` and `/` (Today - Daily Review)
* **Observation**:
  - Daily review card updates immediately with factual counts: Completed Today, Scheduled Remaining, Overdue, and Pending Proposals.
  - The audit log displays an immutable, user-scoped sequence:
    `confirm_extraction` $\rightarrow$ `generate_plan` $\rightarrow$ `create_proposal` $\rightarrow$ `approve_proposal` $\rightarrow$ `execute_and_verify` $\rightarrow$ `deliver_reminder`.

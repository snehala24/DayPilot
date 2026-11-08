# DayPilot

> **Personal admin agent that turns messy requests into tracked commitments, plans around fixed events, and never writes to a calendar or sends a message without explicit human approval.**

---

## 1. Product Overview & Core Principle

Personal tasks, notes, calendar events, and reminders often live in disconnected silos. While modern chat assistants can suggest plans, they fail to reliably enforce commitments, miss schedule conflicts, or silently alter external systems.

DayPilot solves this through a non-negotiable safety invariant:

$$\text{\bf The agent proposes. The person approves. The system executes and verifies.}$$

### Key Features
- **Structured Extraction with Explicit Uncertainty**: Converts raw, unstructured notes into schema-validated commitments with ambiguity questions instead of hallucinated facts.
- **Deterministic Constraint-Validated Planning**: Enforces working hours, lunch buffers, deadline feasibility, and multi-day dependency chains without silent task rescheduling.
- **Visible Conflict Diagnostics & Alternatives**: Flags schedule overlaps transparently and presents non-destructive alternatives requiring human decision.
- **Approval Gate & Isolated Executor**: Consequential external calendar writes are strictly quarantined behind human approvals with Pydantic payload re-validation and post-execution read-back verification.
- **Idempotent Reminder Delivery Engine**: Atomic database CAS leasing prevents concurrent delivery races, paired with exponential backoff retries and crash recovery.
- **Factual Daily Review**: Synthesizes verified completed tasks, remaining obligations, overdue deadlines, and pending proposals without phantom productivity metrics.
- **Immutable Append-Only Audit Trail**: Every extraction, proposal, decision, execution, and delivery attempt is logged with full user scoping.

---

## 2. Architecture & System Flow

```
                                      [Unstructured Note]
                                               │
                                               ▼
                                   ┌───────────────────────┐
                                   │   Extraction Engine   │  (Gemini 2.5 Flash / FakeLLM)
                                   └───────────┬───────────┘
                                               │ Candidate & Ambiguity Questions
                                               ▼
                                   ┌───────────────────────┐
                                   │  User Review Drawer   │  (Explicit Confirmation)
                                   └───────────┬───────────┘
                                               │ Confirmed Commitment
                                               ▼
                                   ┌───────────────────────┐
                                   │ Deterministic Planner │  (Python Hard-Constraint Engine)
                                   └───────────┬───────────┘
                                               │ Daily Plan & Non-Destructive Alternatives
                                               ▼
                                   ┌───────────────────────┐
                                   │     Proposal Queue    │  (Status: Pending)
                                   └───────────┬───────────┘
                                               │ Human Decision
                                               ▼
                                   ┌───────────────────────┐
                                   │     Approval Gate     │  (Pydantic Payload Re-validation)
                                   └───────────┬───────────┘
                                               │ Authorized Write
                                               ▼
                                   ┌───────────────────────┐
                                   │   Isolated Executor   │  (SimulatedCalendarWriteAdapter)
                                   └───────────┬───────────┘
                                               │ Read-Back Fetch
                                               ▼
                                   ┌───────────────────────┐
                                   │ Read-Back Verification│  (Status: Verified)
                                   └───────────────────────┘
```

---

## 3. Tech Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0 (ORM), Pydantic v2 (Validation), Alembic (Migrations), SQLite / PostgreSQL.
- **Frontend**: Next.js 14 (App Router), TypeScript (Strict Mode), Tailwind CSS, Lucide React Icons.
- **Task Scheduling & Worker**: APScheduler 3.x with atomic CAS database claims.
- **Testing & Benchmarks**: Pytest, Vitest, React Testing Library, Ruff.

---

## 4. Prerequisites

- **Python**: `>= 3.11` (Python 3.12 recommended)
- **Node.js**: `>= 18.18` (Node 20 or 22 recommended)
- **Package Managers**: `pip` / `virtualenv`, `npm`

---

## 5. Environment Configuration

### Backend (`backend/.env`)
```bash
ENVIRONMENT=development
PROJECT_NAME="DayPilot"
DATABASE_URL="sqlite:///./daypilot.db"

# LLM Configuration
LLM_PROVIDER="gemini"
LLM_MODEL="gemini-2.5-flash"
GEMINI_API_KEY="your-google-gemini-api-key"

# Scheduler & Worker Settings
APS_SCHEDULER_AUTOSTART=true
REMINDER_DISPATCH_INTERVAL_SECONDS=30
REMINDER_MAX_ATTEMPTS=3
CLAIM_TIMEOUT_SECONDS=300
```

### Frontend (`frontend/.env.local`)
```bash
NEXT_PUBLIC_API_URL="http://localhost:8000/api/v1"
```

---

## 6. PostgreSQL Setup & Database Migrations

DayPilot runs on SQLite out of the box. To connect to PostgreSQL:

1. Create database and user:
   ```sql
   CREATE USER daypilot WITH PASSWORD 'daypilot_secret';
   CREATE DATABASE daypilot OWNER daypilot;
   ```
2. Set in `backend/.env`:
   ```bash
   DATABASE_URL="postgresql://daypilot:daypilot_secret@localhost:5432/daypilot"
   ```
3. Run Alembic migrations:
   ```bash
   cd backend
   alembic upgrade head
   ```

---

## 7. Starting DayPilot Locally

### Backend API Server
```bash
cd backend
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python -m app.models.seed        # Seeds default user, project, and preferences
uvicorn app.main:app --reload --port 8000
```
API Documentation will be available at: `http://localhost:8000/docs`

### Frontend Application
```bash
cd frontend
npm install
npm run dev
```
Open your browser at: `http://localhost:3000`

---

## 8. Test Suites & Benchmarks

Run all verification suites:

```bash
# 1. Full Backend Test Suite (79 passing tests)
pytest backend/tests -v

# 2. Acceptance Workflow Tests (A - G)
pytest backend/tests/test_acceptance_suite.py -v

# 3. System Evaluation Benchmark Runner
python eval/run_comprehensive_benchmark.py

# 4. Frontend Vitest Tests
npm --prefix frontend test

# 5. Frontend Strict TypeScript Typecheck
npx --prefix frontend tsc --project frontend/tsconfig.json --noEmit

# 6. Python Code Formatting & Linting
ruff check backend
```

---

## 9. Reproducible Demo Walkthrough

Run the automated 10-step demo script in your terminal:
```bash
python demo/run_demo_scenario.py
```
Or explore the five UI screens:
1. **Inbox** (`/inbox`): Paste a messy note and resolve ambiguities.
2. **Today** (`/`): View the time-blocked plan, review conflicts, and check the factual Daily Review.
3. **Approvals** (`/approvals`): Review, edit, approve, or reject pending calendar actions.
4. **Commitments** (`/commitments`): Inspect status, edit tasks, and schedule reminders.
5. **History** (`/history`): Review the append-only, user-scoped audit trail.

---

## 10. Known Limitations & Reliability Considerations

1. **Simulated External Adapters (MVP Scope)**:
   - Google Calendar and Twilio notification adapters are implemented as simulated in-database stores with realistic fault injection to verify contracts safely without incurring external charges or side effects.
2. **At-Least-Once External Delivery**:
   - Database operations are strictly idempotent via unique keys and atomic CAS leasing. However, physical network message delivery is at-least-once: in a network crash occurring after provider acceptance but before database acknowledgment, the worker will safely re-attempt delivery upon lease recovery.
3. **Single-User MVP**:
   - The initial MVP is configured for a single authenticated personal admin user (`snehala@daypilot.local`). Multi-tenant session authentication can be enabled by wiring JWT middleware to `User.id`.
4. **Synthetic Benchmark Scope**:
   - Benchmark evaluations reflect synthetic datasets with labeled ground truth. Real-world noisy audio or multi-turn speech transcripts may require additional domain-specific prompt tuning.

---

## 11. Security & Safety Caveats

- **External-Write Isolation**: Only `ProposalExecutor` in `backend/app/executor/` is permitted to invoke calendar write adapters.
- **Approval Gate Immutability**: Proposing is separate from execution. Edits to proposals are re-validated through strict Pydantic schemas before any action can occur.
- **Append-Only Auditing**: Audit records cannot be updated or deleted by normal application workflows.
- **Secrets Management**: No API keys or tokens are sent to or stored in frontend bundles.

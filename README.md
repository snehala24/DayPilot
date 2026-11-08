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

## 10. Limitation Audit & Reliability Hardening

### 10.1 Notification Delivery Reliability: At-Least-Once Physical Delivery
- **Database-Level Idempotency**: All reminders possess a unique `idempotency_key` constraint and use atomic Compare-And-Swap (`CAS`) state transitions (`status='pending'` -> `'claimed'`). Concurrent workers cannot claim the same reminder.
- **Provider-Level Idempotency & Crash Recovery**:
  - If a worker process crashes *after* the external provider accepts a message but *before* the database commits `'delivered'`, the reminder remains in `'claimed'` state until its lease expires (`CLAIM_TIMEOUT_SECONDS=300`).
  - Upon lease expiration, the recovery worker resets the reminder to `'retrying'` and re-dispatches it.
  - If the external delivery channel supports provider-level deduplication (such as Twilio Message deduplication or Stripe idempotency keys), passing `idempotency_key=reminder.idempotency_key` prevents physical duplicate delivery.
  - For standard protocols lacking provider-side idempotency (e.g. SMTP email or standard SMS gateways), DayPilot provides **at-least-once physical delivery**, never claiming false "exactly-once" delivery.
  - This behavior is proven by regression tests in `backend/tests/test_reminder_delivery_suite.py`.

### 10.2 Single-User Model & Explicit Public Deployment Prohibition
> [!WARNING]
> **PROHIBITION AGAINST UNPROTECTED PUBLIC DEPLOYMENT**
> DayPilot MVP is designed as a single-user personal administration agent. The backend endpoints default-scope operations to the primary seeded user (`snehala@daypilot.local`). While query-level tenant isolation is strictly enforced (as proven by `backend/tests/test_user_isolation.py`), the MVP **does not include session JWT or OAuth2 bearer token authentication middleware**.
> **DO NOT deploy this MVP directly to public-facing networks or production internet environments without placing it behind an authenticating reverse proxy or implementing JWT session middleware.**

### 10.3 Simulated External Adapters
- All calendar operations utilize `SimulatedCalendarAdapter` and all notifications utilize `SimulatedNotificationAdapter`.
- These adapters reproduce realistic latency, transient failures, dead-letter exhaustion, and read-back verification contracts without creating live third-party account side effects or billing charges.
- The UI explicitly tags these integrations with visual `(SIMULATED ADAPTER)` badges.

### 10.4 Synthetic vs. Real-World Benchmark Scope
- System benchmarks (`eval/run_comprehensive_benchmark.py`) evaluate 21 structured test scenarios covering standard deadlines, relative times, ambiguity flagging, boundary durations (>24h tasks), and prompt injection resistance.
- Performance on real-world noisy voice transcripts or highly ambiguous jargon may require domain-specific fine-tuning or few-shot examples.

---

## 11. Production Hardening Checklist

Before promoting DayPilot from MVP to multi-tenant production:

- [ ] **Authentication Middleware**: Implement OAuth2 / JWT authentication (e.g. Auth0, Supabase, or FastAPI OAuth2 with PKCE) and inject `current_user: User` into every API dependency.
- [ ] **PostgreSQL Migration**: Move from local SQLite to PostgreSQL with `pgbouncer` connection pooling.
- [ ] **Production CORS Whitelist**: Replace development CORS wildcard with explicit HTTPS production domains.
- [ ] **Live Integration Adapters**: Implement `GoogleCalendarOAuthAdapter` (using Google Calendar API v3) and `TwilioNotificationAdapter` (using Twilio REST API) adhering to `NotificationAdapter` and `CalendarAdapter` contracts.
- [ ] **External-Write Isolation**: Maintain the hard invariant that external adapters are invoked exclusively by `ProposalExecutor` upon human approval.
- [ ] **Distributed Task Queue**: For high-volume multi-tenant notifications, replace in-process APScheduler with Redis/Celery or Temporal.io with durable worker leasing.

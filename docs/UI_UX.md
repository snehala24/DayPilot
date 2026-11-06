# DayPilot — UI/UX and Design System
Nov 3, 2026 · @SNEHALA

The interface is built so a person can see what the agent plans to do, approve or reject it in one step, and later see what actually happened.

## Design principles
1. **Proposal before action**. Anything that changes the outside world is shown as a proposal first, with a clear approve or reject control.
2. **Show the source**. Every commitment links back to the text it came from.
3. **Conflicts are visible, never silent**. A conflict gets its own highlighted treatment and always comes with alternatives.
4. **Status is honest**. The interface distinguishes proposed, approved, executed and verified, so a request is never presented as done before it is verified.
5. **Calm by default**. One primary action per card, low visual noise, and no urgency styling except for overdue or failed items.

## Design tokens
Tokens are CSS variables in the Next.js app; dark mode overrides the color tokens only.

| Token | Light | Dark | Use |
| :--- | :--- | :--- | :--- |
| `--bg` | `#FAFAF7` | `#14161A` | Page background |
| `--surface` | `#FFFFFF` | `#1C1F25` | Cards, panels |
| `--border` | `#E3E5E8` | `#2B2F37` | Dividers, card outlines |
| `--text` | `#1B1F24` | `#ECEEF1` | Body text |
| `--text-muted` | `#5B6470` | `#9AA3AF` | Secondary text, metadata |
| `--primary` | `#2F5BEA` | `#6C8CFF` | Approve, primary buttons, links |
| `--success` | `#1E8E5A` | `#4CC38A` | Verified |
| `--warning` | `#B7791F` | `#E0A94A` | Conflict, needs attention |
| `--danger` | `#C0392B` | `#FF6B5E` | Failed, overdue |

## Key screens
1. **Today**: Timeline with fixed events and planned blocks, conflicts panel, overdue list, Replan button, and pending approval badge.
2. **Inbox**: Large text input, extraction review with source text highlights, questions for ambiguous/unknown fields, Confirm All.
3. **Approvals**: Stack of approval cards (oldest first). Approve, Edit before approving, Reject. In-place transition to Executed and Verified.
4. **Commitments**: Filterable table (status, project, due date). Detail view showing dependencies, provenance, reminders, and history.
5. **History**: Filterable audit trail of requests, approvals, tool results, and recoveries. Retries generate new proposals safely.

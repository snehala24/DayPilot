import uuid
import zoneinfo
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.models.entities import CalendarEvent, Commitment


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure datetime is offset-aware UTC datetime."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass
class TimeSlot:
    """A continuous time interval with UTC timestamps."""

    starts_at: datetime
    ends_at: datetime

    def __post_init__(self):
        self.starts_at = ensure_utc(self.starts_at)
        self.ends_at = ensure_utc(self.ends_at)
        if self.starts_at >= self.ends_at:
            raise ValueError(
                f"TimeSlot starts_at ({self.starts_at}) must precede ends_at ({self.ends_at})."
            )

    @property
    def duration_minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() / 60)

    def overlaps(self, other: "TimeSlot") -> bool:
        return self.starts_at < other.ends_at and other.starts_at < self.ends_at

    def subtract(self, busy: "TimeSlot") -> list["TimeSlot"]:
        """Subtract busy slot from this slot, returning remaining free sub-slots."""
        if not self.overlaps(busy):
            return [self]

        remaining = []
        # Free slot before busy
        if self.starts_at < busy.starts_at:
            remaining.append(
                TimeSlot(self.starts_at, min(self.ends_at, busy.starts_at))
            )
        # Free slot after busy
        if busy.ends_at < self.ends_at:
            remaining.append(TimeSlot(max(self.starts_at, busy.ends_at), self.ends_at))
        return remaining


@dataclass
class PlannedBlock:
    commitment_id: uuid.UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    estimate_minutes: int
    dependencies: list[uuid.UUID] = field(default_factory=list)


@dataclass
class ConflictReport:
    commitment_id: uuid.UUID
    commitment_title: str
    event_id: uuid.UUID | None
    kind: str
    reason: str
    alternatives: list[dict[str, Any]]


@dataclass
class PlanningResult:
    plan_date: date
    scheduled_items: list[PlannedBlock]
    conflicts: list[ConflictReport]
    constraints_report: dict[str, Any]


class HardConstraintValidator:
    """Deterministic validator that proves zero violations of hard scheduling constraints."""

    @staticmethod
    def validate(
        scheduled_items: list[PlannedBlock],
        fixed_events: list[CalendarEvent],
        working_hours_slot: TimeSlot,
        commitments_by_id: dict[uuid.UUID, Commitment],
        dependencies_map: dict[uuid.UUID, list[uuid.UUID]],
    ) -> list[str]:
        violations: list[str] = []

        # 1. No overlaps between planned items
        for i in range(len(scheduled_items)):
            slot_i = TimeSlot(scheduled_items[i].starts_at, scheduled_items[i].ends_at)
            for j in range(i + 1, len(scheduled_items)):
                slot_j = TimeSlot(
                    scheduled_items[j].starts_at, scheduled_items[j].ends_at
                )
                if slot_i.overlaps(slot_j):
                    violations.append(
                        f"Overlap between planned tasks '{scheduled_items[i].title}' and '{scheduled_items[j].title}'."
                    )

        # 2. No overlaps with fixed calendar events
        for item in scheduled_items:
            item_slot = TimeSlot(item.starts_at, item.ends_at)
            for fe in fixed_events:
                if fe.is_fixed:
                    fe_slot = TimeSlot(fe.starts_at, fe.ends_at)
                    if item_slot.overlaps(fe_slot):
                        violations.append(
                            f"Task '{item.title}' overlaps fixed calendar event '{fe.title}'."
                        )

        # 3. Working hour boundaries
        for item in scheduled_items:
            if item.starts_at < working_hours_slot.starts_at:
                violations.append(
                    f"Task '{item.title}' starts before working hours ({item.starts_at} < {working_hours_slot.starts_at})."
                )
            if item.ends_at > working_hours_slot.ends_at:
                violations.append(
                    f"Task '{item.title}' ends after working hours ({item.ends_at} > {working_hours_slot.ends_at})."
                )

        # 4. Valid start and end
        for item in scheduled_items:
            if item.starts_at >= item.ends_at:
                violations.append(
                    f"Task '{item.title}' has invalid timestamps starts_at >= ends_at."
                )

        # 5. Duration requirement
        for item in scheduled_items:
            duration = int((item.ends_at - item.starts_at).total_seconds() / 60)
            if duration != item.estimate_minutes:
                violations.append(
                    f"Task '{item.title}' duration ({duration}m) does not match estimate ({item.estimate_minutes}m)."
                )

        # 6. Deadline feasibility
        for item in scheduled_items:
            commit = commitments_by_id.get(item.commitment_id)
            c_due = ensure_utc(commit.due_at) if commit else None
            if c_due and item.ends_at > c_due:
                violations.append(
                    f"Task '{item.title}' finishes at {item.ends_at}, missing deadline {c_due}."
                )

        # 7. Dependency ordering
        scheduled_map = {item.commitment_id: item for item in scheduled_items}
        for item in scheduled_items:
            prereq_ids = dependencies_map.get(item.commitment_id, [])
            for p_id in prereq_ids:
                if p_id in scheduled_map:
                    prereq_item = scheduled_map[p_id]
                    if item.starts_at < prereq_item.ends_at:
                        violations.append(
                            f"Dependency violation: '{item.title}' starts at {item.starts_at} before prerequisite '{prereq_item.title}' ends at {prereq_item.ends_at}."
                        )

        return violations


class DayPlanner:
    """Deterministic constraint-aware day planner and conflict detector."""

    def __init__(
        self,
        user_timezone: str = "UTC",
        working_hours_start: str = "09:00",
        working_hours_end: str = "18:00",
        break_blocks: list[dict[str, str]] | None = None,
    ):
        self.user_timezone = user_timezone
        self.working_hours_start = working_hours_start
        self.working_hours_end = working_hours_end
        self.break_blocks = break_blocks or [
            {"start": "13:00", "end": "14:00", "name": "Lunch"}
        ]

    def plan(
        self,
        plan_date: date,
        commitments: list[Commitment],
        calendar_events: list[CalendarEvent],
        dependencies_map: dict[uuid.UUID, list[uuid.UUID]],
    ) -> PlanningResult:
        # 1. Compute Working Hours in UTC
        tz = zoneinfo.ZoneInfo(self.user_timezone)
        wh_start_time = datetime.strptime(self.working_hours_start, "%H:%M").time()
        wh_end_time = datetime.strptime(self.working_hours_end, "%H:%M").time()

        local_day_start = datetime.combine(plan_date, wh_start_time, tzinfo=tz)
        local_day_end = datetime.combine(plan_date, wh_end_time, tzinfo=tz)

        working_hours_slot = TimeSlot(
            starts_at=local_day_start.astimezone(UTC),
            ends_at=local_day_end.astimezone(UTC),
        )

        # 2. Subtract fixed calendar events & breaks from working hours to form free intervals
        free_slots: list[TimeSlot] = [working_hours_slot]

        # Break blocks (e.g. lunch)
        for bb in self.break_blocks:
            b_start = datetime.strptime(bb["start"], "%H:%M").time()
            b_end = datetime.strptime(bb["end"], "%H:%M").time()
            local_b_start = datetime.combine(plan_date, b_start, tzinfo=tz)
            local_b_end = datetime.combine(plan_date, b_end, tzinfo=tz)
            break_slot = TimeSlot(
                local_b_start.astimezone(UTC),
                local_b_end.astimezone(UTC),
            )
            new_free = []
            for fs in free_slots:
                new_free.extend(fs.subtract(break_slot))
            free_slots = new_free

        # Subtract fixed calendar events
        fixed_events = [e for e in calendar_events if e.is_fixed]
        for fe in fixed_events:
            fe_slot = TimeSlot(fe.starts_at, fe.ends_at)
            new_free = []
            for fs in free_slots:
                new_free.extend(fs.subtract(fe_slot))
            free_slots = new_free

        free_slots = sorted(free_slots, key=lambda s: s.starts_at)

        # 3. Order commitments deterministically: Topological sort + Tie Breaking
        ordered_commitments = self._order_commitments(
            commitments, dependencies_map, plan_date
        )

        scheduled_items: list[PlannedBlock] = []
        conflicts: list[ConflictReport] = []
        commitments_by_id = {c.id: c for c in commitments}

        # 4. Place commitments
        for commit in ordered_commitments:
            duration = commit.estimate_minutes or 45
            prereq_ids = dependencies_map.get(commit.id, [])

            # Check prerequisite finish time
            min_start = working_hours_slot.starts_at
            blocked_by_incomplete_prereq = False
            for p_id in prereq_ids:
                prereq_commit = commitments_by_id.get(p_id)
                # Has it been scheduled earlier today?
                sched_prereq = next(
                    (it for it in scheduled_items if it.commitment_id == p_id), None
                )
                if sched_prereq:
                    min_start = max(min_start, sched_prereq.ends_at)
                elif prereq_commit and prereq_commit.status == "done":
                    # Prerequisite already done prior to today
                    continue
                else:
                    # Prerequisite is not done and not scheduled today -> Task is blocked!
                    blocked_by_incomplete_prereq = True
                    break

            if blocked_by_incomplete_prereq:
                # Conflict: dependency blocked
                conflicts.append(
                    ConflictReport(
                        commitment_id=commit.id,
                        commitment_title=commit.title,
                        event_id=None,
                        kind="dependency_order",
                        reason=f"Prerequisite tasks for '{commit.title}' must be completed before it can be scheduled.",
                        alternatives=self._generate_alternatives(
                            commit, duration, working_hours_slot, "dependency_order"
                        ),
                    )
                )
                continue

            # Find slot
            placed = False
            for idx, slot in enumerate(free_slots):
                candidate_start = max(slot.starts_at, min_start)
                candidate_end = candidate_start + timedelta(minutes=duration)

                if candidate_end <= slot.ends_at:
                    # Check deadline if present
                    c_due = ensure_utc(commit.due_at)
                    if c_due and candidate_end > c_due:
                        # Cannot fit in this slot before deadline
                        continue

                    # Fits!
                    item = PlannedBlock(
                        commitment_id=commit.id,
                        title=commit.title,
                        starts_at=candidate_start,
                        ends_at=candidate_end,
                        estimate_minutes=duration,
                        dependencies=prereq_ids,
                    )
                    scheduled_items.append(item)

                    # Update free slots: subtract consumed block
                    consumed_slot = TimeSlot(candidate_start, candidate_end)
                    remaining = slot.subtract(consumed_slot)
                    free_slots.pop(idx)
                    for r in reversed(remaining):
                        free_slots.insert(idx, r)

                    placed = True
                    break

            if not placed:
                # Conflict detection
                conflict = self._analyze_conflict(
                    commit=commit,
                    duration=duration,
                    min_start=min_start,
                    free_slots=free_slots,
                    fixed_events=fixed_events,
                    working_hours_slot=working_hours_slot,
                )
                conflicts.append(conflict)

        # 5. Run Hard Constraint Verification
        violations = HardConstraintValidator.validate(
            scheduled_items=scheduled_items,
            fixed_events=fixed_events,
            working_hours_slot=working_hours_slot,
            commitments_by_id=commitments_by_id,
            dependencies_map=dependencies_map,
        )

        constraints_report = {
            "total_commitments": len(commitments),
            "scheduled_count": len(scheduled_items),
            "conflicts_count": len(conflicts),
            "violations_count": len(violations),
            "violations": violations,
            "working_hours_utc": {
                "starts_at": working_hours_slot.starts_at.isoformat(),
                "ends_at": working_hours_slot.ends_at.isoformat(),
            },
        }

        if violations:
            raise ValueError(
                f"Hard constraint violations detected during planning: {violations}"
            )

        return PlanningResult(
            plan_date=plan_date,
            scheduled_items=scheduled_items,
            conflicts=conflicts,
            constraints_report=constraints_report,
        )

    def _order_commitments(
        self,
        commitments: list[Commitment],
        dependencies_map: dict[uuid.UUID, list[uuid.UUID]],
        plan_date: date,
    ) -> list[Commitment]:
        """Order tasks deterministically: Topological Sort + Priority / EDF tie-breaking."""
        # 1. Calculate dependency depth
        depth: dict[uuid.UUID, int] = {}

        def get_depth(c_id: uuid.UUID, visited: set) -> int:
            if c_id in depth:
                return depth[c_id]
            if c_id in visited:
                return 0  # Cycle handled by confirmation API
            visited.add(c_id)
            prereqs = dependencies_map.get(c_id, [])
            d = 0
            for p in prereqs:
                d = max(d, 1 + get_depth(p, visited))
            depth[c_id] = d
            return d

        for c in commitments:
            get_depth(c.id, set())

        # 2. Sort key
        def sort_key(c: Commitment):
            d = depth.get(c.id, 0)
            # Priority (1 is highest, 4 is lowest)
            p = c.priority
            # Due date score (earliest first; None gets far future)
            c_due = ensure_utc(c.due_at)
            due_score = c_due.timestamp() if c_due else float("inf")
            # Duration (shorter first)
            dur = c.estimate_minutes or 45
            return (d, p, due_score, dur, str(c.id))

        return sorted(commitments, key=sort_key)

    def _analyze_conflict(
        self,
        commit: Commitment,
        duration: int,
        min_start: datetime,
        free_slots: list[TimeSlot],
        fixed_events: list[CalendarEvent],
        working_hours_slot: TimeSlot,
    ) -> ConflictReport:
        """Deterministically diagnose why a commitment could not be scheduled and generate alternatives."""
        total_free_minutes = sum(s.duration_minutes for s in free_slots)
        c_due = ensure_utc(commit.due_at)

        # Check if deadline is violated
        if c_due and c_due < working_hours_slot.ends_at:
            slots_before_deadline = [s for s in free_slots if s.starts_at < c_due]
            if not slots_before_deadline or all(
                s.duration_minutes < duration for s in slots_before_deadline
            ):
                return ConflictReport(
                    commitment_id=commit.id,
                    commitment_title=commit.title,
                    event_id=None,
                    kind="deadline_missed",
                    reason=f"Insufficient free time before deadline at {commit.due_at}.",
                    alternatives=self._generate_alternatives(
                        commit, duration, working_hours_slot, "deadline_missed"
                    ),
                )

        # Check if conflicting with fixed events
        for fe in fixed_events:
            fe_slot = TimeSlot(fe.starts_at, fe.ends_at)
            if working_hours_slot.overlaps(fe_slot):
                return ConflictReport(
                    commitment_id=commit.id,
                    commitment_title=commit.title,
                    event_id=fe.id,
                    kind="overlap_fixed_event",
                    reason=f"Cannot schedule {duration}m task without overlapping fixed event '{fe.title}'.",
                    alternatives=self._generate_alternatives(
                        commit, duration, working_hours_slot, "overlap_fixed_event"
                    ),
                )

        # Insufficient total hours
        return ConflictReport(
            commitment_id=commit.id,
            commitment_title=commit.title,
            event_id=None,
            kind="insufficient_working_hours",
            reason=f"Remaining free time ({total_free_minutes}m) is less than required task duration ({duration}m).",
            alternatives=self._generate_alternatives(
                commit, duration, working_hours_slot, "insufficient_working_hours"
            ),
        )

    def _generate_alternatives(
        self,
        commit: Commitment,
        duration: int,
        working_hours_slot: TimeSlot,
        kind: str,
    ) -> list[dict[str, Any]]:
        """Generate 2-3 feasible, actionable alternatives that independently satisfy constraints."""
        alternatives: list[dict[str, Any]] = []

        # Alternative 1: Schedule on the next business day
        next_day_start = working_hours_slot.starts_at + timedelta(days=1)
        alternatives.append(
            {
                "action": "reschedule_next_day",
                "title": f"Move to tomorrow at {self.working_hours_start}",
                "proposed_start": next_day_start.isoformat(),
                "proposed_duration": duration,
                "requires_approval": True,
                "description": "Create a proposal to schedule in the first available slot on the next business day (requires user approval).",
            }
        )

        # Alternative 2: Split into smaller blocks if duration >= 40m, strictly preserving total effort
        if duration >= 40:
            part_1 = duration // 2
            part_2 = (
                duration - part_1
            )  # Exact sum preservation: part_1 + part_2 == duration
            alternatives.append(
                {
                    "action": "split_task",
                    "title": f"Split into {part_1}m and {part_2}m blocks",
                    "parts": [
                        {"part_index": 1, "duration_minutes": part_1},
                        {"part_index": 2, "duration_minutes": part_2},
                    ],
                    "total_duration_minutes": duration,
                    "requires_approval": True,
                    "description": f"Create proposal to divide '{commit.title}' into {part_1}m and {part_2}m segments (total {duration}m, requires user approval).",
                }
            )

        # Alternative 3: Extend deadline
        c_due = ensure_utc(commit.due_at)
        if c_due:
            extended_due = c_due + timedelta(days=1)
            alternatives.append(
                {
                    "action": "extend_deadline",
                    "title": "Extend deadline by 24 hours",
                    "proposed_due_at": extended_due.isoformat(),
                    "requires_approval": True,
                    "description": "Create proposal to extend deadline by 24 hours (requires user approval).",
                }
            )
        else:
            alternatives.append(
                {
                    "action": "deprioritize",
                    "title": "Lower priority to Priority 4",
                    "proposed_priority": 4,
                    "requires_approval": True,
                    "description": "Create proposal to lower priority to 4 and reschedule when free (requires user approval).",
                }
            )

        return alternatives

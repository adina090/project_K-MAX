import json
from datetime import datetime, time, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Literal
from uuid import uuid4

from pydantic import BaseModel


SCHEDULE_HOURS = (8, 10, 12, 14, 16, 18, 20)
CLAIM_GRACE_SECONDS = 15 * 60


class SchedulerEvent(BaseModel):
    id: str
    type: str = "scheduled_health_check"
    scheduled_at: str
    scheduled_hour: int
    routine_order: Literal["morning", "periodic"]
    claimed_at: str


class SchedulerStatus(BaseModel):
    enabled: bool = True
    routine_type: str = "scheduled_health_check"
    interval_seconds: int = 2 * 60 * 60
    window_seconds: int = 2 * 60 * 60
    last_check_at: str | None = None
    next_check_at: str | None = None
    next_check_hour: int | None = None
    remaining_seconds: int | None = None
    due: bool = False
    last_event_id: str | None = None
    last_event_hour: int | None = None


class SchedulerClaim(BaseModel):
    event: SchedulerEvent | None = None
    status: SchedulerStatus


Clock = Callable[[], datetime]


class PeriodicScheduler:
    def __init__(self, state_file: Path, clock: Clock | None = None):
        self.state_file = state_file
        self.clock = clock or (lambda: datetime.now().astimezone())
        self._lock = Lock()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "version": 2,
            "last_check_at": None,
            "last_scheduled_at": None,
            "last_event_id": None,
            "last_event_hour": None,
        }

    def _read_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return self._empty_state()
        with self.state_file.open(encoding="utf-8") as file:
            state = json.load(file)
        if not isinstance(state, dict):
            raise ValueError("Scheduler state must contain a JSON object")
        if state.get("version") != 2:
            return self._empty_state()
        return {**self._empty_state(), **state}

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = self.state_file.with_suffix(".tmp")
        temporary_file.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_file.replace(self.state_file)

    @staticmethod
    def _slot(day, hour: int, tzinfo) -> datetime:
        return datetime.combine(day, time(hour=hour), tzinfo=tzinfo)

    def _today_slots(self, now: datetime) -> list[datetime]:
        return [self._slot(now.date(), hour, now.tzinfo) for hour in SCHEDULE_HOURS]

    def _due_slot(self, state: dict[str, Any], now: datetime) -> datetime | None:
        elapsed_slots = [slot for slot in self._today_slots(now) if slot <= now]
        if not elapsed_slots:
            return None
        latest = elapsed_slots[-1]
        if (now - latest).total_seconds() > CLAIM_GRACE_SECONDS:
            return None
        if state.get("last_scheduled_at") == latest.isoformat(timespec="seconds"):
            return None
        return latest

    def _next_slot(self, now: datetime) -> datetime:
        future = [slot for slot in self._today_slots(now) if slot > now]
        if future:
            return future[0]
        return self._slot(now.date() + timedelta(days=1), SCHEDULE_HOURS[0], now.tzinfo)

    def _previous_slot(self, slot: datetime) -> datetime:
        earlier = [hour for hour in SCHEDULE_HOURS if hour < slot.hour]
        if earlier:
            return self._slot(slot.date(), earlier[-1], slot.tzinfo)
        return self._slot(slot.date() - timedelta(days=1), SCHEDULE_HOURS[-1], slot.tzinfo)

    def start_after_morning(self) -> SchedulerStatus:
        return self.get_status()

    def get_status(self) -> SchedulerStatus:
        now = self.clock()
        with self._lock:
            return self._status_from_state(self._read_state(), now)

    def claim_due_event(self) -> SchedulerClaim:
        now = self.clock()
        with self._lock:
            state = self._read_state()
            scheduled = self._due_slot(state, now)
            if scheduled is None:
                return SchedulerClaim(event=None, status=self._status_from_state(state, now))

            event = SchedulerEvent(
                id=uuid4().hex,
                scheduled_at=scheduled.isoformat(timespec="seconds"),
                scheduled_hour=scheduled.hour,
                routine_order="morning" if scheduled.hour == 8 else "periodic",
                claimed_at=now.isoformat(timespec="seconds"),
            )
            state.update({
                "last_check_at": event.claimed_at,
                "last_scheduled_at": event.scheduled_at,
                "last_event_id": event.id,
                "last_event_hour": event.scheduled_hour,
            })
            self._write_state(state)
            return SchedulerClaim(event=event, status=self._status_from_state(state, now))

    def _status_from_state(self, state: dict[str, Any], now: datetime) -> SchedulerStatus:
        due_slot = self._due_slot(state, now)
        next_slot = due_slot or self._next_slot(now)
        previous_slot = self._previous_slot(next_slot)
        window_seconds = max(1, int((next_slot - previous_slot).total_seconds()))
        remaining = 0 if due_slot else max(0, int((next_slot - now).total_seconds()))
        return SchedulerStatus(
            window_seconds=window_seconds,
            last_check_at=state.get("last_check_at"),
            next_check_at=next_slot.isoformat(timespec="seconds"),
            next_check_hour=next_slot.hour,
            remaining_seconds=remaining,
            due=due_slot is not None,
            last_event_id=state.get("last_event_id"),
            last_event_hour=state.get("last_event_hour"),
        )

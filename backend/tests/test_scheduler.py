import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.scheduler import PeriodicScheduler, SCHEDULE_HOURS


KST = timezone(timedelta(hours=9))


class MutableClock:
    def __init__(self, current: datetime):
        self.current = current

    def __call__(self) -> datetime:
        return self.current


class PeriodicSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temporary_directory.name) / "scheduler" / "state.json"
        self.clock = MutableClock(datetime(2026, 9, 19, 7, 0, tzinfo=KST))
        self.scheduler = PeriodicScheduler(self.state_file, clock=self.clock)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_schedule_uses_fixed_two_hour_slots(self) -> None:
        self.assertEqual(SCHEDULE_HOURS, (8, 10, 12, 14, 16, 18, 20))
        status = self.scheduler.get_status()
        self.assertEqual(status.next_check_hour, 8)
        self.assertEqual(status.remaining_seconds, 3600)
        self.assertFalse(status.due)

    def test_eight_oclock_event_uses_morning_order(self) -> None:
        self.clock.current = datetime(2026, 9, 19, 8, 0, tzinfo=KST)
        claimed = self.scheduler.claim_due_event()
        self.assertIsNotNone(claimed.event)
        self.assertEqual(claimed.event.routine_order, "morning")
        self.assertEqual(claimed.status.next_check_hour, 10)

    def test_later_event_uses_voice_first_order(self) -> None:
        self.clock.current = datetime(2026, 9, 19, 10, 0, tzinfo=KST)
        claimed = self.scheduler.claim_due_event()
        self.assertEqual(claimed.event.routine_order, "periodic")
        self.assertEqual(claimed.event.scheduled_hour, 10)

    def test_due_event_is_claimed_only_once(self) -> None:
        self.clock.current = datetime(2026, 9, 19, 12, 0, tzinfo=KST)
        first = self.scheduler.claim_due_event()
        second = self.scheduler.claim_due_event()
        self.assertIsNotNone(first.event)
        self.assertIsNone(second.event)
        self.assertFalse(second.status.due)

    def test_missed_slot_waits_for_next_schedule(self) -> None:
        self.clock.current = datetime(2026, 9, 19, 20, 16, tzinfo=KST)
        status = self.scheduler.get_status()
        self.assertFalse(status.due)
        self.assertEqual(status.next_check_hour, 8)
        self.assertEqual(status.remaining_seconds, 11 * 3600 + 44 * 60)

    def test_restart_does_not_duplicate_claimed_event(self) -> None:
        self.clock.current = datetime(2026, 9, 19, 14, 0, tzinfo=KST)
        claimed = self.scheduler.claim_due_event()
        restarted = PeriodicScheduler(self.state_file, clock=self.clock)
        after_restart = restarted.claim_due_event()
        self.assertIsNotNone(claimed.event)
        self.assertIsNone(after_restart.event)
        self.assertEqual(after_restart.status.last_event_id, claimed.event.id)


if __name__ == "__main__":
    unittest.main()

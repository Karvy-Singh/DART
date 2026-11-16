import unittest

from dart.scheduler import DeadlineScheduler


class DeadlineSchedulerTests(unittest.TestCase):
    def test_deadlines_come_before_messages_without_deadlines(self):
        scheduler = DeadlineScheduler()
        scheduler.add(b"no deadline", "reliable", priority=100)
        scheduler.add(b"later", "partial", deadline_at_ms=200)
        scheduler.add(b"earlier", "partial", deadline_at_ms=100)

        self.assertEqual(scheduler.pop_next(0).data, b"earlier")
        self.assertEqual(scheduler.pop_next(0).data, b"later")
        self.assertEqual(scheduler.pop_next(0).data, b"no deadline")

    def test_priority_then_insertion_order_break_ties(self):
        scheduler = DeadlineScheduler()
        scheduler.add(b"first low", "partial", deadline_at_ms=100, priority=1)
        scheduler.add(b"first high", "partial", deadline_at_ms=100, priority=2)
        scheduler.add(b"second high", "partial", deadline_at_ms=100, priority=2)

        self.assertEqual(scheduler.pop_next(0).data, b"first high")
        self.assertEqual(scheduler.pop_next(0).data, b"second high")
        self.assertEqual(scheduler.pop_next(0).data, b"first low")

    def test_expire_removes_deadlines_at_or_before_now(self):
        scheduler = DeadlineScheduler()
        scheduler.add(b"past", "partial", deadline_at_ms=9)
        scheduler.add(b"now", "partial", deadline_at_ms=10)
        scheduler.add(b"future", "partial", deadline_at_ms=11)
        scheduler.add(b"reliable", "reliable")

        expired = scheduler.expire(10)

        self.assertEqual([message.data for message in expired], [b"past", b"now"])
        self.assertEqual(len(scheduler), 2)
        self.assertEqual(scheduler.pop_next(10).data, b"future")

    def test_pop_next_returns_none_when_empty(self):
        self.assertIsNone(DeadlineScheduler().pop_next(0))


if __name__ == "__main__":
    unittest.main()

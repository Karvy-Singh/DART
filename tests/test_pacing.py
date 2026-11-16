import unittest

from dart.pacing import Pacer


class FakeTime:
    def __init__(self):
        self.now = 10.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class PacerTests(unittest.TestCase):
    def test_first_send_is_immediate_and_later_sends_are_spaced(self):
        fake_time = FakeTime()
        pacer = Pacer(clock=fake_time.monotonic, sleeper=fake_time.sleep)

        pacer.wait(100)
        pacer.wait(100)
        pacer.wait(100)

        self.assertEqual(len(fake_time.sleeps), 2)
        self.assertAlmostEqual(fake_time.sleeps[0], 0.1)
        self.assertAlmostEqual(fake_time.sleeps[1], 0.1)
        self.assertAlmostEqual(pacer.next_send_at, 10.3)

    def test_late_send_does_not_sleep(self):
        fake_time = FakeTime()
        pacer = Pacer(clock=fake_time.monotonic, sleeper=fake_time.sleep)
        pacer.wait(100)

        fake_time.now = 10.25
        pacer.wait(100)

        self.assertEqual(fake_time.sleeps, [])
        self.assertAlmostEqual(pacer.next_send_at, 10.35)


if __name__ == "__main__":
    unittest.main()

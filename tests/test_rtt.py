import unittest

from dart.rtt import RttEstimator


class RttEstimatorTests(unittest.TestCase):
    def test_first_measurement_replaces_initial_guess(self):
        rtt = RttEstimator(initial_rtt_ms=100, initial_timeout_ms=250)

        rtt.add_measurement(40)

        self.assertEqual(rtt.rtt_ms, 40)
        self.assertEqual(rtt.variation_ms, 20)
        self.assertEqual(rtt.timeout_ms, 120)

    def test_new_measurements_are_smoothed(self):
        rtt = RttEstimator()
        rtt.add_measurement(40)

        rtt.add_measurement(80)

        self.assertEqual(rtt.rtt_ms, 45)
        self.assertEqual(rtt.variation_ms, 25)
        self.assertEqual(rtt.timeout_ms, 145)

    def test_timeout_doubles_wait_time(self):
        rtt = RttEstimator(initial_timeout_ms=250)

        rtt.packet_timed_out()

        self.assertEqual(rtt.timeout_ms, 500)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from dart.network import NetworkSimulator


class NetworkSimulatorTests(unittest.TestCase):
    def test_drop_first_drops_each_key_only_once(self):
        network = NetworkSimulator(loss=0, drop_first=True)

        self.assertTrue(network.drop_data("packet-1"))
        self.assertFalse(network.drop_data("packet-1"))
        self.assertTrue(network.drop_data("packet-2"))
        self.assertFalse(network.drop_data("packet-2"))

    def test_seed_makes_random_loss_deterministic(self):
        first = NetworkSimulator(loss=0.5, ack_loss=0.5, seed=12)
        second = NetworkSimulator(loss=0.5, ack_loss=0.5, seed=12)

        first_results = [first.drop_data(index) for index in range(5)]
        second_results = [second.drop_data(index) for index in range(5)]

        self.assertEqual(first_results, second_results)
        self.assertEqual(first.drop_ack(), second.drop_ack())

    def test_delay_is_deterministic_and_never_negative(self):
        first = NetworkSimulator(delay_ms=2, jitter_ms=5, seed=3)
        second = NetworkSimulator(delay_ms=2, jitter_ms=5, seed=3)

        first_delays = [first.sample_delay_ms() for _ in range(5)]
        second_delays = [second.sample_delay_ms() for _ in range(5)]

        self.assertEqual(first_delays, second_delays)
        self.assertTrue(all(delay >= 0 for delay in first_delays))

    def test_wait_sleeps_in_seconds(self):
        network = NetworkSimulator(delay_ms=25)

        with patch("dart.network.time.sleep") as sleep:
            self.assertEqual(network.wait(), 25)

        sleep.assert_called_once_with(0.025)

    def test_invalid_settings_are_rejected(self):
        for settings in (
            {"loss": -0.1},
            {"ack_loss": 1.1},
            {"delay_ms": -1},
            {"jitter_ms": -1},
        ):
            with self.subTest(settings=settings):
                with self.assertRaises(ValueError):
                    NetworkSimulator(**settings)


if __name__ == "__main__":
    unittest.main()

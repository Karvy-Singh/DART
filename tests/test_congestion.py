import unittest

from dart.congestion import CongestionController


class CongestionControllerTests(unittest.TestCase):
    def test_window_starts_at_one_and_grows(self):
        congestion = CongestionController(maximum_window=4)

        congestion.packets_acked(1)
        congestion.packets_acked(2)

        self.assertEqual(congestion.window, 3)

    def test_window_does_not_pass_maximum(self):
        congestion = CongestionController(maximum_window=2)

        congestion.packets_acked(10)
        congestion.packets_acked(10)

        self.assertEqual(congestion.window, 2)

    def test_loss_halves_window(self):
        congestion = CongestionController(maximum_window=8)
        congestion.window = 6

        congestion.packet_loss()

        self.assertEqual(congestion.window, 3)


if __name__ == "__main__":
    unittest.main()

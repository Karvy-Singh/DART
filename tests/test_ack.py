import unittest

from dart.ack import AckTracker
from dart.packet import AckPacket


class AckTrackerTests(unittest.TestCase):
    def test_acknowledges_out_of_order_packets(self):
        tracker = AckTracker()
        tracker.add(2)
        tracker.add(0)
        largest, bitmap = tracker.add(1)
        ack = AckPacket(1, 0, largest, bitmap)

        self.assertTrue(ack.acknowledges(0))
        self.assertTrue(ack.acknowledges(1))
        self.assertTrue(ack.acknowledges(2))
        self.assertFalse(ack.acknowledges(3))

    def test_old_packets_fall_out_of_bitmap_range(self):
        tracker = AckTracker()
        tracker.add(0)
        largest, bitmap = tracker.add(65)
        ack = AckPacket(1, 0, largest, bitmap)

        self.assertTrue(ack.acknowledges(65))
        self.assertFalse(ack.acknowledges(0))

    def test_old_retransmission_is_acknowledged_by_itself(self):
        tracker = AckTracker()
        tracker.add(65)

        largest, bitmap = tracker.add(0)
        ack = AckPacket(1, 0, largest, bitmap)

        self.assertTrue(ack.acknowledges(0))


if __name__ == "__main__":
    unittest.main()

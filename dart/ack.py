"""Build small selective acknowledgements for received packet numbers."""


class AckTracker:
    def __init__(self):
        self.received = set()

    def add(self, packet_number):
        """Remember a packet and return the largest number plus ACK bitmap."""
        if self.received and packet_number < max(self.received) - 64:
            # An old retransmission no longer fits in the bitmap. ACK it alone.
            return packet_number, 0

        self.received.add(packet_number)
        largest = max(self.received)
        bitmap = 0

        for distance in range(1, 65):
            if largest - distance in self.received:
                bitmap |= 1 << (distance - 1)

        # The packet format can only report the largest 65 packet numbers.
        self.received = {
            number for number in self.received if number >= largest - 64
        }
        return largest, bitmap

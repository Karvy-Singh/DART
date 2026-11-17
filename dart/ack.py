"""Build selective acknowledgements and remember received packet ranges."""


class AckTracker:
    def __init__(self):
        self.ranges = []

    def add(self, packet_number):
        """Remember a packet and return the largest number plus ACK bitmap."""
        self._remember(packet_number)
        largest = self.ranges[-1][1]

        # An old retransmission no longer fits in the bitmap. ACK it alone.
        if packet_number < largest - 64:
            return packet_number, 0

        bitmap = 0
        for distance in range(1, 65):
            if self.has_received(largest - distance):
                bitmap |= 1 << (distance - 1)
        return largest, bitmap

    def has_received(self, packet_number):
        """Return True only when this exact packet was previously received."""
        return any(start <= packet_number <= end for start, end in self.ranges)

    def _remember(self, packet_number):
        """Store packet numbers as merged ranges to keep long runs compact."""
        self.ranges.append((packet_number, packet_number))
        self.ranges.sort()

        merged = []
        for start, end in self.ranges:
            if merged and start <= merged[-1][1] + 1:
                old_start, old_end = merged[-1]
                merged[-1] = (old_start, max(old_end, end))
            else:
                merged.append((start, end))
        self.ranges = merged

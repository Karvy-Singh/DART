"""Minimal AIMD congestion window for the learning transport."""


class CongestionController:
    def __init__(self, maximum_window):
        self.maximum_window = maximum_window
        self.window = 1
        self.acks_since_growth = 0

    def packets_acked(self, count):
        """Grow by one after one current window of successful ACKs."""
        self.acks_since_growth += count
        if self.window < self.maximum_window and self.acks_since_growth >= self.window:
            self.acks_since_growth -= self.window
            self.window += 1

    def packet_loss(self):
        """Cut the window in half after a retransmission timeout."""
        self.window = max(1, self.window // 2)
        self.acks_since_growth = 0

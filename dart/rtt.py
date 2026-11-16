"""Small RTT estimator used to choose retransmission timeouts."""


class RttEstimator:
    def __init__(self, initial_rtt_ms=100, initial_timeout_ms=250):
        self.rtt_ms = float(initial_rtt_ms)
        self.variation_ms = self.rtt_ms / 2
        self.timeout_ms = float(initial_timeout_ms)
        self.has_measurement = False

    def add_measurement(self, measured_rtt_ms):
        """Learn from the time between sending a packet and receiving its ACK."""
        measured_rtt_ms = max(1.0, float(measured_rtt_ms))

        if not self.has_measurement:
            self.rtt_ms = measured_rtt_ms
            self.variation_ms = measured_rtt_ms / 2
            self.has_measurement = True
        else:
            difference = abs(self.rtt_ms - measured_rtt_ms)
            self.variation_ms = 0.75 * self.variation_ms + 0.25 * difference
            self.rtt_ms = 0.875 * self.rtt_ms + 0.125 * measured_rtt_ms

        self.timeout_ms = self.rtt_ms + 4 * self.variation_ms
        self.timeout_ms = min(60000, max(50, self.timeout_ms))

    def packet_timed_out(self):
        """Wait longer after a timeout instead of retrying too quickly."""
        self.timeout_ms = min(60000, self.timeout_ms * 2)

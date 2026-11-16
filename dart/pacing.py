"""Simple spacing between outgoing packets."""

import time


class Pacer:
    def __init__(self, clock=time.monotonic, sleeper=time.sleep):
        self.clock = clock
        self.sleeper = sleeper
        self.next_send_at = None

    def wait(self, interval_ms):
        """Wait until the next send time, with the first send immediate."""
        if interval_ms < 0:
            raise ValueError("Interval must be zero or greater")

        now = self.clock()
        if self.next_send_at is None:
            self.next_send_at = now

        delay = self.next_send_at - now
        if delay > 0:
            self.sleeper(delay)

        self.next_send_at = max(self.next_send_at, self.clock()) + interval_ms / 1000

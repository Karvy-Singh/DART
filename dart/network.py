"""Deterministic network conditions for demos and tests."""

import random
import time


class NetworkSimulator:
    def __init__(
        self,
        loss=0,
        ack_loss=0,
        delay_ms=0,
        jitter_ms=0,
        drop_first=False,
        seed=7,
    ):
        if not 0 <= loss <= 1 or not 0 <= ack_loss <= 1:
            raise ValueError("Loss rates must be between 0 and 1")
        if delay_ms < 0 or jitter_ms < 0:
            raise ValueError("Delay and jitter must be zero or greater")

        self.loss = loss
        self.ack_loss = ack_loss
        self.delay_ms = delay_ms
        self.jitter_ms = jitter_ms
        self.drop_first = drop_first
        self.random = random.Random(seed)
        self.dropped_keys = set()

    def drop_data(self, key):
        """Return whether this data item should be dropped."""
        if self.drop_first and key not in self.dropped_keys:
            self.dropped_keys.add(key)
            return True
        return self.random.random() < self.loss

    def drop_ack(self):
        """Return whether an acknowledgement should be dropped."""
        return self.random.random() < self.ack_loss

    def sample_delay_ms(self):
        """Choose a delay around the configured base delay."""
        jitter = self.random.uniform(-self.jitter_ms, self.jitter_ms)
        return max(0, self.delay_ms + jitter)

    def wait(self):
        """Sleep for one sampled network delay and return that delay."""
        delay_ms = self.sample_delay_ms()
        if delay_ms > 0:
            time.sleep(delay_ms / 1000)
        return delay_ms

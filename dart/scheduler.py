"""Small deadline-aware message scheduler."""

from dataclasses import dataclass
from typing import Any


@dataclass
class ScheduledMessage:
    data: Any
    reliability: Any
    deadline_at_ms: int | None = None
    priority: int = 0
    insertion_order: int = 0


class DeadlineScheduler:
    """Store messages and choose the most urgent one when asked."""

    def __init__(self):
        self.messages = []
        self.next_insertion_order = 0

    def add(self, data, reliability, deadline_at_ms=None, priority=0):
        message = ScheduledMessage(
            data=data,
            reliability=reliability,
            deadline_at_ms=deadline_at_ms,
            priority=priority,
            insertion_order=self.next_insertion_order,
        )
        self.next_insertion_order += 1
        self.messages.append(message)
        return message

    def pop_next(self, now_ms):
        """Remove expired messages, then return the next message to send."""
        self.expire(now_ms)
        if not self.messages:
            return None

        message = min(self.messages, key=self._sort_key)
        self.messages.remove(message)
        return message

    def expire(self, now_ms):
        """Remove and return messages whose deadlines have passed."""
        expired = [
            message
            for message in self.messages
            if message.deadline_at_ms is not None
            and message.deadline_at_ms <= now_ms
        ]
        self.messages = [message for message in self.messages if message not in expired]
        return expired

    def __len__(self):
        return len(self.messages)

    @staticmethod
    def _sort_key(message):
        if message.deadline_at_ms is None:
            return (1, 0, -message.priority, message.insertion_order)
        return (
            0,
            message.deadline_at_ms,
            -message.priority,
            message.insertion_order,
        )

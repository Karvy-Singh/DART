"""DART sender for text, files, and deadline-aware JSON batches."""

import argparse
import json
import os
from pathlib import Path
import socket
import time

from dart import DeadlineScheduler, Reliability, encode_file, encode_text
from dart.client import DartClient
from dart.security import SecurityError, parse_key


MODE_NAMES = {
    "unreliable": Reliability.UNRELIABLE,
    "partial": Reliability.PARTIAL,
    "reliable": Reliability.RELIABLE,
}


def make_item(data, label, mode, deadline_ms, priority):
    if mode not in MODE_NAMES:
        raise ValueError(f"Unknown mode: {mode}")
    if not 0 <= priority <= 255:
        raise ValueError("Priority must be between 0 and 255")
    if mode == "partial" and (deadline_ms is None or deadline_ms <= 0):
        raise ValueError("Partial messages need a positive deadline_ms")

    created_at_ms = int(time.time() * 1000)
    local_now_ms = int(time.monotonic() * 1000)
    return {
        "data": data,
        "label": label,
        "reliability": MODE_NAMES[mode],
        "deadline_ms": deadline_ms if mode == "partial" else None,
        "deadline_at_ms": (
            local_now_ms + deadline_ms if mode == "partial" else None
        ),
        "priority": priority,
        "created_at_ms": created_at_ms,
    }


def load_batch(path):
    """Load text/file messages from a small JSON array."""
    batch_path = Path(path)
    entries = json.loads(batch_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ValueError("Batch must be a non-empty JSON array")

    items = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Every batch entry must be an object")
        has_text = "text" in entry
        has_file = "file" in entry
        if has_text == has_file:
            raise ValueError("Each batch entry needs either text or file")

        if has_text:
            data = encode_text(str(entry["text"]))
            label = f"text {entry['text']!r}"
        else:
            file_path = batch_path.parent / entry["file"]
            data = encode_file(file_path.name, file_path.read_bytes())
            label = f"file {file_path.name!r}"

        items.append(
            make_item(
                data,
                label,
                entry.get("mode", "reliable"),
                entry.get("deadline_ms"),
                int(entry.get("priority", 0)),
            )
        )
    return items


def main():
    parser = argparse.ArgumentParser(description="DART v4 sender")
    parser.add_argument("message", nargs="?", help="Text to send")
    parser.add_argument("--file", help="File to send instead of text")
    parser.add_argument("--batch", help="JSON file containing multiple messages")
    parser.add_argument("--mode", choices=MODE_NAMES, default="partial")
    parser.add_argument("--priority", type=int, default=0)
    parser.add_argument("--deadline-ms", type=int, default=1500)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--timeout-ms", type=int, default=250)
    parser.add_argument("--estimated-rtt-ms", type=int, default=100)
    parser.add_argument("--max-attempts", type=int, default=10)
    parser.add_argument("--window-size", type=int, default=8)
    parser.add_argument(
        "--key",
        default=os.environ.get("DART_PSK"),
        help="64-hex-character pre-shared key (or set DART_PSK)",
    )
    args = parser.parse_args()

    source_count = sum(
        source is not None for source in (args.message, args.file, args.batch)
    )
    if source_count != 1:
        parser.error("Provide exactly one of message, --file, or --batch")
    if not args.key:
        parser.error("Provide --key or set DART_PSK")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    if min(
        args.timeout_ms,
        args.estimated_rtt_ms,
        args.max_attempts,
        args.window_size,
    ) <= 0:
        parser.error("Timing, retry, and window settings must be positive")
    if args.window_size > 65:
        parser.error("Window size cannot exceed the 65-packet ACK range")

    try:
        pre_shared_key = parse_key(args.key)
        if args.batch:
            items = load_batch(args.batch)
        elif args.file:
            file_path = Path(args.file)
            items = [
                make_item(
                    encode_file(file_path.name, file_path.read_bytes()),
                    f"file {file_path.name!r}",
                    args.mode,
                    args.deadline_ms,
                    args.priority,
                )
            ]
        else:
            items = [
                make_item(
                    encode_text(args.message),
                    f"text {args.message!r}",
                    args.mode,
                    args.deadline_ms,
                    args.priority,
                )
            ]

        scheduler = DeadlineScheduler()
        for item in items:
            scheduler.add(
                item,
                item["reliability"],
                item["deadline_at_ms"],
                item["priority"],
            )

        destination = (socket.gethostbyname(args.host), args.port)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            client = DartClient(
                sock,
                destination,
                pre_shared_key,
                maximum_window=args.window_size,
                timeout_ms=args.timeout_ms,
                estimated_rtt_ms=args.estimated_rtt_ms,
                max_attempts=args.max_attempts,
            )
            client.connect()

            failed = False
            while len(scheduler):
                now_ms = int(time.monotonic() * 1000)
                for expired in scheduler.expire(now_ms):
                    print(f"[SENDER  ] expired in queue: {expired.data['label']}")

                scheduled = scheduler.pop_next(now_ms)
                if scheduled is None:
                    break
                item = scheduled.data
                print(f"[SENDER  ] sending {item['label']}")
                result = client.send(
                    item["data"],
                    item["reliability"],
                    item["deadline_ms"],
                    item["priority"],
                    item["created_at_ms"],
                    item["deadline_at_ms"],
                )
                print(f"[SENDER  ] {item['label']}: {result}")
                failed = failed or result == "failed"
                if failed:
                    break

            client.close()
            return 1 if failed else 0
    except (
        ConnectionError,
        OSError,
        SecurityError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(f"[SENDER  ] ERROR: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

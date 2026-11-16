"""Simple DART v2 receiver. Run this before sender.py."""

import argparse
from pathlib import Path
import random
import socket
import time

from dart import (
    MAX_DATAGRAM_BYTES,
    AckTracker,
    AckPacket,
    DataPacket,
    MessageReassembler,
    PacketError,
    Reliability,
    decode_message,
    decode_packet,
    encode_packet,
)


def main():
    parser = argparse.ArgumentParser(description="Simple DART v2 receiver")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--loss", type=float, default=0.0)
    parser.add_argument("--ack-loss", type=float, default=0.0)
    parser.add_argument(
        "--drop-first",
        action="store_true",
        help="Drop the first copy of every fragment",
    )
    parser.add_argument("--delay-ms", type=int, default=0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--output-dir",
        default="received",
        help="Directory where received files are saved",
    )
    args = parser.parse_args()

    if not (0 <= args.loss <= 1 and 0 <= args.ack_loss <= 1):
        parser.error("Loss values must be between 0 and 1")
    if args.delay_ms < 0:
        parser.error("Delay must be zero or greater")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")

    random_generator = random.Random(args.seed)
    reassembler = MessageReassembler()
    dropped_once = set()
    next_ack_number = {}
    ack_trackers = {}

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((args.host, args.port))
        print(f"[RECEIVER] listening on {args.host}:{args.port} (UDP)", flush=True)

        try:
            while True:
                raw, address = sock.recvfrom(MAX_DATAGRAM_BYTES + 1)

                try:
                    packet = decode_packet(raw)
                except PacketError as error:
                    print(f"[RECEIVER] ignored invalid packet: {error}", flush=True)
                    continue

                if not isinstance(packet, DataPacket):
                    continue

                packet_key = (packet.connection_id, packet.packet_number)
                if args.drop_first and packet_key not in dropped_once:
                    dropped_once.add(packet_key)
                    print(
                        f"[NETWORK ] dropped fragment {packet.fragment_index + 1}",
                        flush=True,
                    )
                    continue
                if random_generator.random() < args.loss:
                    print(
                        f"[NETWORK ] randomly dropped packet {packet.packet_number}",
                        flush=True,
                    )
                    continue
                if args.delay_ms:
                    time.sleep(args.delay_ms / 1000)

                message_key = (packet.connection_id, packet.message_id)
                was_already_complete = message_key in reassembler.completed

                try:
                    complete_message = reassembler.add(packet)
                except PacketError as error:
                    print(f"[RECEIVER] rejected fragment: {error}", flush=True)
                    continue

                if was_already_complete:
                    print("[RECEIVER] duplicate fragment; not delivered again", flush=True)
                elif complete_message is not None:
                    try:
                        kind, filename, content = decode_message(complete_message)
                        if kind == "text":
                            print(
                                f"[RECEIVER] delivered text: {content!r}",
                                flush=True,
                            )
                        else:
                            output_dir = Path(args.output_dir)
                            output_dir.mkdir(parents=True, exist_ok=True)
                            output_path = output_dir / filename
                            output_path.write_bytes(content)
                            print(
                                f"[RECEIVER] saved file: {output_path} "
                                f"({len(content)} bytes)",
                                flush=True,
                            )
                    except (OSError, UnicodeError, ValueError) as error:
                        print(
                            f"[RECEIVER] could not deliver message: {error}",
                            flush=True,
                        )
                else:
                    print(
                        f"[RECEIVER] stored fragment "
                        f"{packet.fragment_index + 1}/{packet.fragment_count}",
                        flush=True,
                    )

                if packet.reliability == Reliability.UNRELIABLE:
                    continue

                tracker = ack_trackers.setdefault(packet.connection_id, AckTracker())
                largest, bitmap = tracker.add(packet.packet_number)
                if random_generator.random() < args.ack_loss:
                    print("[NETWORK ] ACK lost", flush=True)
                    continue

                ack_number = next_ack_number.get(packet.connection_id, 0)
                next_ack_number[packet.connection_id] = ack_number + 1
                ack = AckPacket(
                    connection_id=packet.connection_id,
                    packet_number=ack_number,
                    largest_acknowledged=largest,
                    ack_bitmap=bitmap,
                )
                sock.sendto(encode_packet(ack), address)
                print(
                    f"[RECEIVER] ACK sent for packet {packet.packet_number}",
                    flush=True,
                )
        except KeyboardInterrupt:
            print("\n[RECEIVER] stopped")


if __name__ == "__main__":
    main()

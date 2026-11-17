"""DART receiver with handshake, expiration, flow control, and simulation."""

import argparse
import os
from pathlib import Path
import secrets
import socket
import time

from dart import (
    MAX_DATAGRAM_BYTES,
    AckPacket,
    AckTracker,
    ClosePacket,
    Connection,
    ConnectionState,
    DataPacket,
    HelloAckPacket,
    HelloPacket,
    MessageReassembler,
    NetworkSimulator,
    PacketError,
    Reliability,
    decode_message,
    decode_packet,
    encode_packet,
)
from dart.security import (
    SecurityError,
    decrypt_data,
    derive_session_key,
    parse_key,
    sign_ack,
    sign_close,
    sign_hello_ack,
    verify_close,
    verify_hello,
)


def main():
    parser = argparse.ArgumentParser(description="DART v4 receiver")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--receive-window", type=int, default=8)
    parser.add_argument("--loss", type=float, default=0.0)
    parser.add_argument("--ack-loss", type=float, default=0.0)
    parser.add_argument("--delay-ms", type=float, default=0)
    parser.add_argument("--jitter-ms", type=float, default=0)
    parser.add_argument("--drop-first", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output-dir", default="received")
    parser.add_argument("--max-message-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--reassembly-timeout-ms", type=int, default=30000)
    parser.add_argument(
        "--key",
        default=os.environ.get("DART_PSK"),
        help="64-hex-character pre-shared key (or set DART_PSK)",
    )
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    if not 1 <= args.receive_window <= 65:
        parser.error("Receive window must be between 1 and 65")
    if args.max_message_bytes <= 0:
        parser.error("Maximum message size must be positive")
    if args.reassembly_timeout_ms <= 0:
        parser.error("Reassembly timeout must be positive")
    if not args.key:
        parser.error("Provide --key or set DART_PSK")
    try:
        pre_shared_key = parse_key(args.key)
        network = NetworkSimulator(
            loss=args.loss,
            ack_loss=args.ack_loss,
            delay_ms=args.delay_ms,
            jitter_ms=args.jitter_ms,
            drop_first=args.drop_first,
            seed=args.seed,
        )
    except ValueError as error:
        parser.error(str(error))

    reassembler = MessageReassembler()
    connections = {}
    ack_trackers = {}
    next_ack_number = {}
    session_keys = {}
    client_nonces = {}
    server_nonces = {}
    closed_keys = {}

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((args.host, args.port))
        sock.settimeout(0.1)
        print(
            f"[RECEIVER] listening on {args.host}:{args.port}; "
            f"receive-window={args.receive_window}",
            flush=True,
        )

        try:
            while True:
                try:
                    raw, address = sock.recvfrom(MAX_DATAGRAM_BYTES + 1)
                except socket.timeout:
                    now_ms = int(time.time() * 1000)
                    for connection_id, message_id in reassembler.expire(
                        now_ms,
                        args.reassembly_timeout_ms,
                    ):
                        print(
                            f"[RECEIVER] expired incomplete message {message_id} "
                            f"on connection {connection_id}",
                            flush=True,
                        )
                    continue
                try:
                    packet = decode_packet(raw)
                except PacketError as error:
                    print(f"[RECEIVER] ignored invalid packet: {error}", flush=True)
                    continue

                if isinstance(packet, HelloPacket):
                    try:
                        verify_hello(packet, pre_shared_key)
                    except SecurityError:
                        print("[RECEIVER] rejected unauthenticated HELLO", flush=True)
                        continue

                    if packet.connection_id in closed_keys:
                        response = sign_close(
                            ClosePacket(packet.connection_id, packet.packet_number),
                            closed_keys[packet.connection_id],
                            role=b"server",
                        )
                        sock.sendto(encode_packet(response), address)
                        continue

                    connection = connections.get(packet.connection_id)
                    if connection is None:
                        server_nonce = secrets.token_bytes(16)
                        session_key = derive_session_key(
                            pre_shared_key,
                            packet.connection_id,
                            packet.nonce,
                            server_nonce,
                        )
                        connection = Connection(packet.connection_id)
                        connection.start_handshake()
                        connection.establish(packet.receive_window)
                        connections[packet.connection_id] = connection
                        client_nonces[packet.connection_id] = packet.nonce
                        server_nonces[packet.connection_id] = server_nonce
                        session_keys[packet.connection_id] = session_key
                        next_ack_number[packet.connection_id] = 1
                        print(
                            f"[RECEIVER] connection {packet.connection_id} established",
                            flush=True,
                        )

                    network.wait()
                    if network.drop_ack():
                        print("[NETWORK ] HELLO_ACK lost", flush=True)
                        continue
                    reply = sign_hello_ack(
                        HelloAckPacket(
                            connection_id=packet.connection_id,
                            packet_number=0,
                            receive_window=args.receive_window,
                            nonce=server_nonces[packet.connection_id],
                        ),
                        pre_shared_key,
                        client_nonces[packet.connection_id],
                    )
                    sock.sendto(encode_packet(reply), address)
                    continue

                if isinstance(packet, ClosePacket):
                    connection = connections.get(packet.connection_id)
                    session_key = session_keys.get(
                        packet.connection_id,
                        closed_keys.get(packet.connection_id),
                    )
                    if session_key is None:
                        continue
                    try:
                        verify_close(packet, session_key, role=b"client")
                    except SecurityError:
                        print("[RECEIVER] rejected unauthenticated CLOSE", flush=True)
                        continue
                    if connection is not None:
                        connection.start_close()
                        connection.finish_close()
                        del connections[packet.connection_id]
                        ack_trackers.pop(packet.connection_id, None)
                        next_ack_number.pop(packet.connection_id, None)
                        reassembler.remove_connection(packet.connection_id)
                        session_keys.pop(packet.connection_id, None)
                        client_nonces.pop(packet.connection_id, None)
                        server_nonces.pop(packet.connection_id, None)
                        closed_keys[packet.connection_id] = session_key
                        if len(closed_keys) > 1024:
                            closed_keys.pop(next(iter(closed_keys)))
                        print(
                            f"[RECEIVER] connection {packet.connection_id} closed",
                            flush=True,
                        )
                    network.wait()
                    if not network.drop_ack():
                        response = sign_close(
                            ClosePacket(packet.connection_id, packet.packet_number),
                            session_key,
                            role=b"server",
                        )
                        sock.sendto(encode_packet(response), address)
                    continue

                connection = connections.get(packet.connection_id)
                if connection is None or connection.state is not ConnectionState.ESTABLISHED:
                    print("[RECEIVER] ignored packet without handshake", flush=True)
                    continue

                if not isinstance(packet, DataPacket):
                    continue

                packet_key = (packet.connection_id, packet.packet_number)
                if network.drop_data(packet_key):
                    print(f"[NETWORK ] dropped packet {packet.packet_number}", flush=True)
                    continue
                network.wait()

                try:
                    packet = decrypt_data(packet, session_keys[packet.connection_id])
                except SecurityError:
                    print("[RECEIVER] rejected unauthenticated DATA", flush=True)
                    continue

                now_ms = int(time.time() * 1000)
                message_key = (packet.connection_id, packet.message_id)
                was_complete = message_key in reassembler.completed
                is_incomplete = message_key in reassembler.incomplete
                for connection_id, message_id in reassembler.expire(
                    now_ms,
                    args.reassembly_timeout_ms,
                ):
                    print(
                        f"[RECEIVER] expired incomplete message {message_id} "
                        f"on connection {connection_id}",
                        flush=True,
                    )
                if (
                    packet.reliability == Reliability.PARTIAL
                    and packet.created_at_ms + packet.deadline_ms <= now_ms
                    and not was_complete
                ):
                    print(
                        f"[RECEIVER] dropped expired message {packet.message_id}",
                        flush=True,
                    )
                    continue

                tracker = ack_trackers.setdefault(packet.connection_id, AckTracker())
                packet_already_received = tracker.has_received(packet.packet_number)

                if packet_already_received:
                    print("[RECEIVER] replayed packet ignored", flush=True)
                else:
                    buffered_bytes = reassembler.message_buffered_bytes(
                        packet.connection_id,
                        packet.message_id,
                    )
                    is_duplicate = reassembler.has_fragment(
                        packet.connection_id,
                        packet.message_id,
                        packet.fragment_index,
                    )
                    new_bytes = 0 if is_duplicate else len(packet.payload)
                    if buffered_bytes + new_bytes > args.max_message_bytes:
                        print("[RECEIVER] rejected message larger than limit", flush=True)
                        continue
                    if (
                        not was_complete
                        and not is_incomplete
                        and reassembler.incomplete_messages(packet.connection_id)
                        >= args.receive_window
                    ):
                        print("[RECEIVER] receive window is full", flush=True)
                        continue

                    try:
                        complete_message = reassembler.add(packet, now_ms)
                    except PacketError as error:
                        print(f"[RECEIVER] rejected fragment: {error}", flush=True)
                        continue

                    if was_complete:
                        print("[RECEIVER] duplicate fragment ignored", flush=True)
                    elif complete_message is not None:
                        deliver_message(complete_message, args.output_dir)

                largest, bitmap = tracker.add(packet.packet_number)

                if packet.reliability == Reliability.UNRELIABLE:
                    continue

                incomplete_count = reassembler.incomplete_messages(packet.connection_id)
                available_window = max(1, args.receive_window - incomplete_count)
                network.wait()
                if network.drop_ack():
                    print("[NETWORK ] ACK lost", flush=True)
                    continue

                ack_number = next_ack_number[packet.connection_id]
                next_ack_number[packet.connection_id] += 1
                ack = sign_ack(
                    AckPacket(
                        connection_id=packet.connection_id,
                        packet_number=ack_number,
                        largest_acknowledged=largest,
                        ack_bitmap=bitmap,
                        receive_window=available_window,
                    ),
                    session_keys[packet.connection_id],
                )
                sock.sendto(encode_packet(ack), address)
        except KeyboardInterrupt:
            print("\n[RECEIVER] stopped")


def deliver_message(data, output_directory):
    """Deliver one complete application message."""
    try:
        kind, filename, content = decode_message(data)
        if kind == "text":
            print(f"[RECEIVER] delivered text: {content!r}", flush=True)
            return

        output_dir = Path(output_directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename
        output_path.write_bytes(content)
        print(
            f"[RECEIVER] saved file: {output_path} ({len(content)} bytes)",
            flush=True,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"[RECEIVER] could not deliver message: {error}", flush=True)


if __name__ == "__main__":
    main()

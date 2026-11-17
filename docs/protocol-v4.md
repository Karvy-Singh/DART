# DART Protocol Version 4 (Draft)

## Status

This document defines the target behavior for DART v4. The repository currently
implements the five packet types, connection state machine, fragmentation and
reassembly, selective ACKs, adaptive timeouts, EDF message scheduling,
receiver-side expiration, dynamic receiver-window updates, packet pacing,
pre-shared-key authenticated encryption, and minimal AIMD congestion-window
adjustment. Production-grade congestion control remains future work.

## Purpose

DART is a message-oriented transport over UDP for applications where data can
lose value with time. Its primary objective is to maximize useful, on-time
delivery rather than to deliver every application byte regardless of age.

DART does not claim to replace TCP or QUIC. Its research contribution is the
use of message deadlines and reliability classes in scheduling and loss
recovery decisions.

## Application Service

Applications submit independent messages with these properties:

```text
payload
channel_id
reliability
deadline_ms (PARTIAL only)
priority
```

Submitting a message eventually produces one terminal outcome:

```text
DELIVERED          Complete message accepted by the remote application.
EXPIRED            Delivery was abandoned because its deadline became infeasible.
CONNECTION_FAILED  Delivery could not continue because the connection failed.
```

`UNRELIABLE` messages complete locally after their one transmission and do not
produce confirmed `DELIVERED` outcomes.

Messages are independent and unordered by default. Loss of one message must not
prevent a complete unrelated message from being delivered. Ordered channels are
outside the initial v4 scope.

## Reliability Classes

### UNRELIABLE

- Transmit each packet at most once.
- Do not request acknowledgements or retransmit loss.
- Do not confirm remote delivery.

### PARTIAL

- Request acknowledgements.
- Retransmit only while complete delivery is predicted to be feasible before
  the message deadline.
- Stop transmitting all remaining fragments after expiration.
- Discard incomplete receiver reassembly state after expiration.

### RELIABLE

- Request acknowledgements and recover detected loss while the connection is
  operational.
- Complete as `DELIVERED` only after the remote endpoint confirms complete
  message acceptance.
- Complete as `CONNECTION_FAILED` if recovery can no longer continue.

Like TCP and QUIC, `RELIABLE` does not promise delivery after an endpoint or
connection failure.

## Deadline Semantics

A partial message's deadline is the maximum elapsed time from local application
submission to complete delivery at the remote application:

```text
deadline_at = submission_time + deadline_ms
```

The sender uses a monotonic clock for scheduling. A packet is eligible for an
initial transmission or retransmission only when:

```text
predicted_complete_delivery_time <= deadline_at
```

The prediction may include queueing delay, serialization time, estimated
one-way delay, and the time needed to send the message's remaining fragments.

Cross-device receiver-side deadline enforcement requires a clock-offset
estimate or synchronized clocks. Until DART implements clock-offset estimation,
real-device experiments must synchronize clocks and report their expected clock
error. Deterministic simulations use one shared experiment clock.

## Connection State

The initial connection state machine is:

```text
CLOSED -> HANDSHAKING -> ESTABLISHED -> DRAINING -> CLOSED
```

A handshake establishes a connection ID, protocol version, maximum datagram
size, random nonces, and initial packet numbers. Path migration, forward secrecy,
automatic key rotation, and zero-RTT establishment are not part of v4.

## Packet Types

The initial packet types are:

```text
HELLO      Starts a connection and advertises transport parameters.
HELLO_ACK  Accepts a connection and returns transport parameters.
DATA       Carries one message fragment.
ACK        Acknowledges received packet numbers.
CLOSE      Closes a connection and communicates a reason code.
```

## Common Header

Every v4 packet carries:

```text
version
packet_type
flags
connection_id
packet_number
```

A `DATA` packet additionally carries:

```text
message_id
channel_id
fragment_index
fragment_count
reliability
priority
deadline metadata (PARTIAL only)
creation timestamp
payload_length
payload
```

An `ACK` packet identifies acknowledged packet numbers using ranges or a bitmap.
Acknowledgements refer to packets, not only message IDs, so individual fragments
can be recovered without resending a complete message.

The implemented `DATA` and `ACK` codec uses network byte order and the following
24-byte common header:

| Field | Width |
| --- | ---: |
| Magic (`DART`) | 4 bytes |
| Version | 1 byte |
| Packet type | 1 byte |
| Flags | 2 bytes |
| Connection ID | 8 bytes |
| Packet number | 8 bytes |

The implemented `DATA` header adds 38 bytes:

| Field | Width |
| --- | ---: |
| Message ID | 16 bytes |
| Channel ID | 2 bytes |
| Fragment index | 2 bytes |
| Fragment count | 2 bytes |
| Reliability | 1 byte |
| Priority | 1 byte |
| Deadline in milliseconds | 4 bytes |
| Creation time in Unix milliseconds | 8 bytes |
| Payload length | 2 bytes |

A zero deadline means no deadline and is valid only for `UNRELIABLE` and
`RELIABLE` packets. A `PARTIAL` packet requires a positive deadline.

The implemented `ACK` body contains an 8-byte largest acknowledged packet
number, an 8-byte bitmap, a 2-byte available receive window, and a 32-byte HMAC.
The largest packet is acknowledged implicitly. Bitmap bit zero represents
`largest - 1`, bit one represents `largest - 2`, and so on through the 64
immediate predecessors.

Packet type values 1 through 5 represent `HELLO`, `HELLO_ACK`, `DATA`, `ACK`,
and `CLOSE`. Handshake packets carry a 2-byte receive window, a 16-byte random
nonce, and a 32-byte HMAC. ACK packets carry a dynamic 2-byte receive window and
a 32-byte HMAC. CLOSE packets carry a 32-byte HMAC.

Encoded datagrams must not exceed 1200 bytes unless a later path-MTU mechanism
negotiates a different limit. With the current 62-byte `DATA` headers, one
packet carries at most 1138 encrypted bytes or 1122 plaintext bytes after the
ChaCha20-Poly1305 tag.

## Fragmentation And Delivery

- A message larger than one packet is split into numbered fragments.
- Fragments may arrive out of order.
- Duplicate fragments are acknowledged but stored only once.
- The receiver delivers a message only after all required fragments have been
  received and validated.
- Message identity is scoped by connection ID.
- Receiver reassembly and duplicate-detection state must be bounded and expire.

## Scheduling

The current sender accepts multiple messages through a JSON batch. It removes
expired messages, selects partial messages by earliest deadline, then uses
priority and insertion order as tie breakers. Messages without deadlines follow
the deadline-bearing messages and are ordered by priority. Scheduling is
non-preemptive: once transmission of a message starts, it finishes or expires
before the scheduler selects another message.

## Congestion And Flow Control

The current learning controller starts with one packet in flight. After one
window of successful acknowledgements it increases the window by one. A timeout
halves the window, with a minimum of one packet. The `--window-size` setting is
the maximum congestion window.

The handshake advertises the receiver's maximum accepted in-flight window. Each
authenticated ACK updates the currently available window based on buffered
messages. The receiver bounds concurrent incomplete messages, per-message bytes,
and duplicate-history state. The sender immediately applies only the newest
authenticated window update. Packets are paced
using the current RTT divided by the active congestion window.

The following pieces remain future work:

- More accurate congestion detection and recovery.
- Fairness evaluation against established transports.

## Security

Both endpoints are configured with the same 32-byte pre-shared key. HELLO and
HELLO_ACK exchange random nonces authenticated with HMAC-SHA256. The connection
ID and both nonces derive a unique 32-byte session key.

DATA payloads use ChaCha20-Poly1305. Packet metadata is additional authenticated
data, so changing a deadline, priority, message ID, fragment number, or packet
number causes authentication failure. ACK and CLOSE packets use HMAC-SHA256 to
prevent forged delivery acknowledgements, window updates, or teardown.

Performance comparisons without these controls must not claim fairness against
TCP or QUIC.

## Initial Non-Goals

- A compatible implementation of HTTP, TCP, or QUIC.
- Transparent support for arbitrary byte-stream applications.
- Forward secrecy or certificate-based identity.
- NAT traversal or path migration.
- Kernel integration.
- Production deployment guarantees.

Applications can build request/response, file-transfer, and real-time protocols
on DART's message API. A future HTTP gateway may translate between HTTP and DART,
but HTTP is not itself the DART wire protocol.

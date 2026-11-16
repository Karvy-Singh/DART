# DART Protocol Version 2 (Draft)

## Status

This document defines the target behavior for DART v2. The repository currently
implements binary `DATA` and `ACK` packets, message fragmentation and reassembly,
a sliding window with selective ACKs, measured RTT with an adaptive timeout, and
minimal AIMD congestion-window adjustment. The connection, scheduling,
flow-control, pacing, and production-grade congestion-control sections remain
targets for later milestones.

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
outside the initial v2 scope.

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
size, and initial packet numbers. Security, identity authentication, path
migration, and zero-RTT establishment are not part of the initial v2 scope.

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

Every v2 packet carries:

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

The implemented `DATA` header adds 30 bytes:

| Field | Width |
| --- | ---: |
| Message ID | 16 bytes |
| Channel ID | 2 bytes |
| Fragment index | 2 bytes |
| Fragment count | 2 bytes |
| Reliability | 1 byte |
| Priority | 1 byte |
| Deadline in milliseconds | 4 bytes |
| Payload length | 2 bytes |

A zero deadline means no deadline and is valid only for `UNRELIABLE` and
`RELIABLE` packets. A `PARTIAL` packet requires a positive deadline.

The implemented `ACK` body contains an 8-byte largest acknowledged packet
number followed by an 8-byte bitmap. The largest packet is acknowledged
implicitly. Bitmap bit zero represents `largest - 1`, bit one represents
`largest - 2`, and so on through the 64 immediate predecessors.

Packet type values 3 and 4 currently represent `DATA` and `ACK`. `HELLO`,
`HELLO_ACK`, and `CLOSE` encodings remain to be defined with the connection
state machine.

Encoded datagrams must not exceed 1200 bytes unless a later path-MTU mechanism
negotiates a different limit. With the current 54-byte `DATA` headers, one
packet can carry at most 1146 payload bytes.

## Fragmentation And Delivery

- A message larger than one packet is split into numbered fragments.
- Fragments may arrive out of order.
- Duplicate fragments are acknowledged but stored only once.
- The receiver delivers a message only after all required fragments have been
  received and validated.
- Message identity is scoped by connection ID.
- Receiver reassembly and duplicate-detection state must be bounded and expire.

## Scheduling

The first v2 implementation will support these policies:

```text
FIFO
Earliest Deadline First (EDF)
Deadline-Aware EDF
```

Deadline-Aware EDF removes infeasible partial messages before selecting the
feasible message with the earliest deadline. Reliable traffic must receive a
minimum scheduling share so that partial traffic cannot starve connection
control or reliable messages.

## Congestion And Flow Control

The current learning controller starts with one packet in flight. After one
window of successful acknowledgements it increases the window by one. A timeout
halves the window, with a minimum of one packet. The `--window-size` setting is
the maximum congestion window.

The following pieces remain future work:

- Receiver-advertised flow-control capacity.
- Packet pacing.
- More accurate congestion detection and recovery.
- Fairness evaluation against established transports.

Performance comparisons without these controls must not claim fairness against
TCP or QUIC.

## Initial Non-Goals

- A compatible implementation of HTTP, TCP, or QUIC.
- Transparent support for arbitrary byte-stream applications.
- Encryption or endpoint authentication.
- NAT traversal or path migration.
- Kernel integration.
- Production deployment guarantees.

Applications can build request/response, file-transfer, and real-time protocols
on DART's message API. A future HTTP gateway may translate between HTTP and DART,
but HTTP is not itself the DART wire protocol.

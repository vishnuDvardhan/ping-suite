"""icmp_ping.py - real ICMP echo ping using a raw socket (needs root).

This is what the system `ping` command does.

ICMP Echo Request/Reply header (RFC 792), 8 bytes:
    0      7 8     15 16             31
   +--------+--------+----------------+
   |  type  |  code  |    checksum    |    type 8 = echo request
   +--------+--------+----------------+    type 0 = echo reply
   |   identifier    | sequence number|    code   = 0
   +-----------------+----------------+
   |           payload ...            |

Steps:
  1. Build header with checksum = 0, add payload.
  2. Compute the Internet checksum over header+payload, put it in.
  3. Send via a raw socket. The kernel adds the IP header for us.
  4. Receive. On a raw socket we get the FULL IP packet, so we must skip
     the IP header first. Its length is (first byte & 0x0F) * 4 bytes.
  5. A raw ICMP socket receives EVERY ICMP packet arriving at the host
     (other pings, errors, ...). Keep only type 0 with OUR identifier
     and the sequence number we are waiting for.

Why root? A raw socket lets you write arbitrary packets (spoofing, scans).
So Linux needs CAP_NET_RAW. (Modern Linux also has unprivileged
SOCK_DGRAM ICMP sockets, controlled by net.ipv4.ping_group_range.
`--dgram` uses that mode; then the kernel sets the ID and strips the IP header.)

Run:  sudo python3 icmp_ping.py 127.0.0.1 -c 10
"""
import argparse
import os
import select
import socket
import struct
import time

from stats import summarize

ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY = 0
ICMP_HDR = struct.Struct("!BBHHH")  # type, code, checksum, id, seq
TS = struct.Struct("!d")


def checksum(data: bytes) -> int:
    """Internet checksum (RFC 1071).

    1. Treat data as 16-bit big-endian words (pad odd length with a 0 byte).
    2. Add them all up with 32-bit+ arithmetic.
    3. Fold carries: add the high 16 bits into the low 16 bits (twice is
       enough to absorb every carry).
    4. Take the one's complement (~), keep 16 bits.

    Receiver check: the checksum of a packet that INCLUDES a correct
    checksum field comes out to 0.
    """
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return ~total & 0xFFFF


def build_echo(ident, seq, size):
    payload = TS.pack(time.perf_counter())
    payload += b"Q" * max(0, size - len(payload))
    hdr = ICMP_HDR.pack(ICMP_ECHO_REQUEST, 0, 0, ident, seq)
    csum = checksum(hdr + payload)
    return ICMP_HDR.pack(ICMP_ECHO_REQUEST, 0, csum, ident, seq) + payload


def parse_reply(packet, raw):
    """Return (type, code, id, seq, ttl, icmp_bytes) or None."""
    ttl = None
    if raw:
        ihl = (packet[0] & 0x0F) * 4  # IP header length in bytes (usually 20)
        ttl = packet[8]  # TTL is byte 8 of the IPv4 header
        packet = packet[ihl:]
    if len(packet) < ICMP_HDR.size:
        return None
    typ, code, _csum, ident, seq = ICMP_HDR.unpack_from(packet)
    return typ, code, ident, seq, ttl, packet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("-c", "--count", type=int, default=10)
    ap.add_argument("-i", "--interval", type=float, default=0.2)
    ap.add_argument("-W", "--timeout", type=float, default=1.0)
    ap.add_argument("-s", "--size", type=int, default=56)  # same default as ping
    ap.add_argument("--dgram", action="store_true",
                    help="use unprivileged SOCK_DGRAM ICMP socket")
    a = ap.parse_args()

    dst = socket.gethostbyname(a.host)  # DNS resolve once, up front
    kind = socket.SOCK_DGRAM if a.dgram else socket.SOCK_RAW
    try:
        sock = socket.socket(socket.AF_INET, kind, socket.IPPROTO_ICMP)
    except PermissionError:
        raise SystemExit("raw socket needs root (sudo) - or try --dgram")
    raw = not a.dgram
    ident = os.getpid() & 0xFFFF  # 16-bit id so we can find OUR replies

    print(f"PING {a.host} ({dst}) {a.size} bytes of data")
    rtts = []
    for seq in range(a.count):
        pkt = build_echo(ident, seq, a.size)
        t0 = time.perf_counter()
        sock.sendto(pkt, (dst, 0))  # port is meaningless for ICMP; use 0

        deadline = t0 + a.timeout
        got = False
        while not got:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            # select() waits until the socket is readable or time runs out.
            ready, _, _ = select.select([sock], [], [], remaining)
            if not ready:
                break
            data, (src, _) = sock.recvfrom(65535)
            t1 = time.perf_counter()
            r = parse_reply(data, raw)
            if r is None:
                continue
            typ, code, rid, rseq, ttl, icmp = r
            # In --dgram mode the kernel rewrites the id, so skip that check.
            if typ != ICMP_ECHO_REPLY or rseq != seq or (raw and rid != ident):
                if typ == 3:  # destination unreachable
                    print(f"from {src}: destination unreachable (code {code})")
                continue
            if checksum(icmp) != 0:
                print(f"seq={seq} bad checksum, dropped")
                continue
            rtt = (t1 - t0) * 1000
            rtts.append(rtt)
            ttl_s = f" ttl={ttl}" if ttl is not None else ""
            print(f"{len(icmp)} bytes from {src}: icmp_seq={seq}{ttl_s} time={rtt:.3f} ms")
            got = True
        if not got:
            print(f"icmp_seq={seq} timeout")
        time.sleep(max(0, a.interval - (time.perf_counter() - t0)))

    sock.close()
    summarize(f"{a.host} (icmp)", a.count, rtts)


if __name__ == "__main__":
    main()

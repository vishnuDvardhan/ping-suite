# Ping Suite — build and learn guide

Python UDP, TCP and ICMP ping tools, a multithreaded TCP server, and tc netem
loss experiments. Every file is short and heavily commented. Read the code
in the order below.

```
stats.py        shared stats: loss %, min/avg/max/stddev, p50/p99, jitter
udp_server.py   UDP echo server (+ optional software --drop)
udp_ping.py     UDP ping client
tcp_server.py   multithreaded TCP echo server (timeouts + error handling)
tcp_ping.py     TCP ping: --mode connect (handshake) or --mode echo
icmp_ping.py    real ICMP ping with a raw socket (root)
netem.sh        add/remove loss, delay, jitter with tc netem
experiment.sh   runs all tools under several netem settings
```

Requires Python 3.8+ and Linux. ICMP raw sockets and tc need `sudo`.

---

## Stage 1 — UDP ping (1–2 hours)

**Run**
```
python3 udp_server.py --port 9000
python3 udp_ping.py 127.0.0.1 --port 9000 -c 10
```

**Concepts**
- `SOCK_DGRAM` = UDP. No connection, no delivery guarantee, no ordering.
- `recvfrom` returns the sender address. The server uses it to reply.
- `settimeout` turns a blocking `recvfrom` into "wait at most N seconds".
  A timeout = lost probe.
- Use `time.perf_counter()` for RTT. It is monotonic. `time.time()` can jump.
- Each packet carries a sequence number. A late reply to probe 3 must not
  count as the reply to probe 4. That is why the client checks `rseq != seq`.
- `struct.pack("!Id", ...)`: `!` = network byte order (big-endian).

**Exercises**
1. Start the server with `--drop 0.2`. Send 500 probes. Is loss near 20%?
2. Remove the `rseq != seq` check. Use a small timeout (`-W 0.0005`) so
   replies arrive late. What goes wrong with the RTTs?
3. Send to a port with no server. What happens? (Hint: the kernel sends back
   ICMP Port Unreachable. A *connected* UDP socket reports it as
   `ConnectionRefusedError`. An unconnected one just times out.)

---

## Stage 2 — Multithreaded TCP server (2–3 hours)

**Run**
```
python3 tcp_server.py --port 9001
python3 tcp_ping.py 127.0.0.1 --port 9001 --mode echo -c 10
```

**Concepts**
- `listen()` → `accept()` loop. `accept()` returns a new socket per client.
- Thread-per-client. Each thread blocks in `recv()` on its own socket.
- **GIL**: a thread blocked on a socket releases the GIL, so I/O-bound
  threads overlap well. CPU-bound threads would not.
- **TCP is a byte stream, not messages.** One `send()` can arrive as two
  `recv()`s. So messages use a 4-byte length prefix, and `recv_exact()`
  loops until it has every byte.
- `recv()` returning `b""` means the peer closed the connection (FIN).
- `sendall()` loops until every byte is sent. Plain `send()` may send fewer.
- Timeouts: `conn.settimeout(idle)` drops idle clients so they don't hold a
  thread forever.
- Errors handled: `socket.timeout`, `ConnectionResetError` (peer sent RST),
  `BrokenPipeError` (write to a closed peer). `finally: conn.close()` always
  frees the file descriptor.
- `threading.Lock` protects the shared `active` counter. `active += 1` is
  not atomic: it is read, add, write.
- `TCP_NODELAY` turns off Nagle's algorithm. Otherwise small messages can
  stall ~40 ms waiting for a delayed ACK.

**Exercises**
1. Run 20 clients at once:
   `for i in $(seq 20); do python3 tcp_ping.py 127.0.0.1 --mode echo -c 5 & done; wait`
   Watch `active=` in the server log.
2. Connect with `nc 127.0.0.1 9001` and type nothing. See the idle timeout.
3. Remove the lock. Can you make the counter go wrong? (Hard to see in
   CPython, but the code is still incorrect.)
4. Rewrite the server with `concurrent.futures.ThreadPoolExecutor(max_workers=8)`.
   What happens to client 9?
5. Stretch: rewrite with `selectors` (epoll) or `asyncio`. One thread, many clients.

---

## Stage 3 — TCP ping (1 hour)

**Run**
```
python3 tcp_ping.py 127.0.0.1 --port 9001                # connect mode
python3 tcp_ping.py 127.0.0.1 --port 9999                # closed port
python3 tcp_ping.py example.com --port 443 -c 5          # any real server
```

**Concepts**
- `connect()` returns after the 3-way handshake (SYN, SYN-ACK, ACK).
  So connect time ≈ 1 RTT. No special server needed.
- Host availability from the result:

  | Result | Meaning |
  |---|---|
  | connected | host up, port open |
  | `ConnectionRefusedError` | host up, port closed (it sent RST) |
  | timeout | host down, or firewall drops SYNs silently |

- Useful where ICMP is blocked (many clouds and firewalls block ping).
- **TCP retransmits.** Under loss, a TCP ping rarely fails. Its RTT jumps
  instead: a lost data segment waits for the RTO (Linux minimum 200 ms),
  a lost SYN waits 1 s. So loss shows up as **latency spikes**, not as
  missing replies. This is the key result of the netem experiment.

---

## Stage 4 — ICMP ping (3–4 hours, the hardest part)

**Run**
```
sudo python3 icmp_ping.py 127.0.0.1 -c 10
sudo python3 icmp_ping.py 8.8.8.8 -c 5
python3 icmp_ping.py 127.0.0.1 --dgram     # unprivileged, if allowed
```

**Concepts**
- Echo header: type (8 request / 0 reply), code 0, checksum, identifier,
  sequence. 8 bytes, then payload.
- **Internet checksum (RFC 1071)**: sum 16-bit words, fold the carries back
  in, take the one's complement. Compute it with the checksum field set to 0.
  A correct packet checksums to 0 on the receiver.
- **Raw socket** (`SOCK_RAW`) needs root (`CAP_NET_RAW`), because raw
  sockets can forge packets.
- On receive you get the **whole IP packet**. Skip the IP header:
  `ihl = (packet[0] & 0x0F) * 4`. TTL is byte 8 of the IP header.
- A raw ICMP socket sees **every** ICMP packet on the host. Filter by
  type 0, your identifier (`os.getpid() & 0xFFFF`) and sequence number.
- `select()` waits for "readable or timeout", so stray packets don't reset
  your timer.
- Type 3 = destination unreachable. Type 11 = time exceeded (how traceroute works).
- Linux also has unprivileged `SOCK_DGRAM` ICMP sockets
  (`net.ipv4.ping_group_range`). The kernel then sets the id and strips the
  IP header for you.

**Exercises**
1. Run `sudo tcpdump -i lo -X icmp` while pinging. Find type, code,
   checksum, id and seq in the hex dump.
2. Put a wrong checksum in the request. Does the reply still come back?
   (The receiver kernel drops it.)
3. Compare with the system tool: `ping -c 20 127.0.0.1`. Are the numbers close?
4. Stretch: build traceroute. Send with `IP_TTL` = 1, 2, 3, ... and read the
   type 11 replies.

---

## Stage 5 — tc netem (1–2 hours)

```
sudo modprobe sch_netem
sudo ./netem.sh on lo "loss 20%"
sudo ./netem.sh show lo
sudo ./netem.sh off lo            # ALWAYS remove it when done
sudo ./experiment.sh              # full run of all tools
```

**Concepts**
- `tc` manages the queue (qdisc) on an interface. netem is a qdisc that
  drops, delays, duplicates, corrupts or reorders packets on purpose.
- netem acts on **outgoing** packets only.
- **Loopback trap**: request and reply both leave through `lo`. With 20%
  loss each, round-trip loss = 1 − 0.8² = **36%**. For 20% round-trip
  loss on `lo`, set `loss 10.6%`. Or test between two machines/VMs and
  apply netem on one side only.
- Use enough probes. With 200 probes and p = 0.2, the standard deviation of
  measured loss is about √(0.2·0.8/200) ≈ 2.8 percentage points. 20 probes
  is far too few.

**What you should see**

| Tool | Under loss |
|---|---|
| UDP | Loss % matches the round-trip drop rate. RTT of survivors unchanged. |
| ICMP | Same as UDP. |
| TCP echo | ~0% "loss", but p99 RTT jumps to 200 ms+ (retransmissions). |
| TCP connect | Some connects take ~1 s+ (SYN retransmit). |

That table is the main finding of the project. Be able to explain it.

**Exercises**
1. `delay 50ms 10ms`: does jitter in your stats match?
2. `corrupt 5%`: what happens to UDP vs TCP? (Corrupted packets fail the
   checksum and are dropped by the kernel. TCP retransmits; UDP just loses them.)
3. `reorder 25% 50% delay 10ms`: does the UDP seq check save you?

---

## Interview questions to practice

1. Why does ICMP need root? What is `CAP_NET_RAW`?
2. Walk through the Internet checksum. Why does a valid packet sum to 0?
3. Why skip 20 bytes on a raw ICMP receive? When is it not 20?
4. What exactly does a TCP connect ping measure?
5. Why does TCP show ~0% loss under 20% netem loss? What shows the loss instead?
6. Why threads, if Python has a GIL?
7. Thread-per-client: when does it break? What would you use instead?
8. Why the length prefix? What bug happens without it?
9. With 20% netem loss on `lo`, why did you measure ~36%?
10. Why `perf_counter()` and not `time.time()`?
11. How do you tell "host down" from "port closed" with TCP?
12. Why check the sequence number in UDP replies?

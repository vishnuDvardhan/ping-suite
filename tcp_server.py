"""tcp_server.py - multithreaded TCP echo server.

Design: thread-per-client.
  * Main thread: loop on accept(). Each accept() returns a NEW socket for
    one client. Hand it to a new thread and go back to accept().
  * Worker thread: read a message, echo it back, repeat until the client
    closes, goes idle longer than --idle seconds, or errors.

Why threads work in Python despite the GIL: a thread blocked in recv() or
accept() releases the GIL. This server is I/O-bound, so threads overlap fine.

Limits (good interview point): one OS thread per client costs memory
(~8 MB virtual stack each by default) and context switches. Thousands of
clients -> use a thread pool, select/epoll, or asyncio instead.

TCP is a BYTE STREAM, not messages. One send() may arrive as two recv()s,
or two sends as one recv(). So we frame each message with a 4-byte length
prefix and read exactly that many bytes (recv_exact).

Run:  python3 tcp_server.py --port 9001
"""
import argparse
import socket
import struct
import threading

LEN = struct.Struct("!I")  # 4-byte length prefix
active = 0
lock = threading.Lock()  # protects `active` (shared between threads)


def recv_exact(conn, n):
    """Read exactly n bytes, or return None if the peer closed."""
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:  # empty bytes = orderly close (FIN received)
            return None
        buf += chunk
    return bytes(buf)


def handle(conn, addr, idle):
    global active
    with lock:
        active += 1
        print(f"[+] {addr} connected  (active={active})")
    conn.settimeout(idle)  # recv() raises socket.timeout after `idle` seconds
    try:
        while True:
            hdr = recv_exact(conn, LEN.size)
            if hdr is None:
                break
            (n,) = LEN.unpack(hdr)
            if n > 1 << 20:  # refuse absurd sizes (1 MB) - basic input checking
                print(f"[!] {addr} bad length {n}")
                break
            body = recv_exact(conn, n)
            if body is None:
                break
            conn.sendall(hdr + body)  # sendall loops until all bytes are sent
    except socket.timeout:
        print(f"[!] {addr} idle timeout")
    except (ConnectionResetError, BrokenPipeError) as e:
        print(f"[!] {addr} {type(e).__name__}")  # client vanished (RST)
    except OSError as e:
        print(f"[!] {addr} error: {e}")
    finally:
        conn.close()  # always release the file descriptor
        with lock:
            active -= 1
            print(f"[-] {addr} closed     (active={active})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--idle", type=float, default=10.0, help="idle timeout (s)")
    a = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((a.host, a.port))
    srv.listen(128)  # backlog: queued connections not yet accept()ed
    print(f"TCP echo server on {a.host}:{a.port}")

    while True:
        conn, addr = srv.accept()
        # Disable Nagle's algorithm: send small messages immediately instead
        # of waiting to batch them. Without this, small pings can see ~40 ms
        # extra delay from Nagle + delayed ACK interacting.
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # daemon=True: these threads won't block Ctrl+C shutdown.
        threading.Thread(target=handle, args=(conn, addr, a.idle),
                         daemon=True).start()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

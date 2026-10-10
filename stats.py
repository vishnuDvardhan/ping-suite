"""stats.py - shared statistics for all three ping tools.

Every ping tool collects a list of RTTs (in ms) for the replies that came
back, plus a count of how many probes it sent. This module turns that into
the same summary the system `ping` prints.
"""
import math


def summarize(target, sent, rtts):
    """Print a ping-style summary.

    sent : number of probes sent
    rtts : list of RTTs in milliseconds, one per reply received
    """
    recv = len(rtts)
    loss = 100.0 * (sent - recv) / sent if sent else 0.0
    print(f"\n--- {target} ping statistics ---")
    print(f"{sent} sent, {recv} received, {loss:.1f}% loss")
    if not rtts:
        print("no successful replies")
        return {"sent": sent, "recv": 0, "loss": loss}

    mn, mx = min(rtts), max(rtts)
    avg = sum(rtts) / recv
    # Population standard deviation, same as Linux ping's "mdev".
    sd = math.sqrt(sum((r - avg) ** 2 for r in rtts) / recv)
    # Jitter = mean absolute difference between consecutive RTTs (RFC 3550 idea).
    jitter = (sum(abs(rtts[i] - rtts[i - 1]) for i in range(1, recv)) / (recv - 1)
              if recv > 1 else 0.0)
    p50 = percentile(rtts, 50)
    p99 = percentile(rtts, 99)
    print(f"rtt min/avg/max/stddev = {mn:.3f}/{avg:.3f}/{mx:.3f}/{sd:.3f} ms")
    print(f"p50 = {p50:.3f} ms, p99 = {p99:.3f} ms, jitter = {jitter:.3f} ms")
    return {"sent": sent, "recv": recv, "loss": loss, "min": mn, "avg": avg,
            "max": mx, "stddev": sd, "p50": p50, "p99": p99, "jitter": jitter}


def percentile(values, p):
    """Nearest-rank percentile. Simple and good enough for ping data."""
    s = sorted(values)
    k = max(0, math.ceil(p / 100 * len(s)) - 1)
    return s[k]
